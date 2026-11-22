"""Download company documents (PDFs), extract their text and split it into chunks.

- Only PDFs are processed (checked by the file's first bytes, not its name).
- The file's SHA-256 is stored; an unchanged file is not processed again, a
  changed one is re-extracted and its chunks replaced.
- Scanned PDFs (almost no extractable text) are marked `needs_ocr` rather
  than stored as empty text. OCR itself is not part of this phase.
- Chunks follow page boundaries so every piece of text can be traced to its
  pages in the original document.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import UUID

import httpx
from pypdf import PdfReader
from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 60_000_000
MIN_CHARS_PER_PAGE = 200      # below this on average, the PDF is probably scanned images
CHUNK_TARGET_WORDS = 1500
DOCUMENT_TYPES = ("annual_report", "quarterly_results", "investor_presentation",
                  "exchange_filing", "earnings_transcript", "other_disclosure")


@dataclass
class Chunk:
    chunk_no: int
    page_from: int
    page_to: int
    content: str

    @property
    def word_count(self) -> int:
        return len(self.content.split())


@dataclass
class IngestResult:
    processed: int = 0
    extracted: int = 0
    unchanged: int = 0
    needs_ocr: int = 0
    not_pdf: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def chunk_pages(pages: list[str], target_words: int = CHUNK_TARGET_WORDS) -> list[Chunk]:
    """Group consecutive pages into chunks of roughly `target_words` words.
    A single very long page becomes its own chunk; pages are never split."""
    chunks: list[Chunk] = []
    buffer: list[str] = []
    start = 1
    words = 0
    for number, page in enumerate(pages, start=1):
        page = page.strip()
        page_words = len(page.split())
        if buffer and words + page_words > target_words:
            chunks.append(Chunk(len(chunks), start, number - 1, "\n\n".join(buffer)))
            buffer, words, start = [], 0, number
        if page:
            buffer.append(page)
            words += page_words
        elif not buffer:
            start = number + 1
    if buffer:
        chunks.append(Chunk(len(chunks), start, len(pages), "\n\n".join(buffer)))
    return chunks


def extract_pages(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [(page.extract_text() or "") for page in reader.pages]


class DocumentService:
    def __init__(self, engine: Engine, client: httpx.Client | None = None) -> None:
        self.engine = engine
        self.client = client or httpx.Client(
            timeout=60, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; stock-intelligence-platform; educational project)"},
        )

    # ---------- registering ----------

    def add(self, company_id: UUID, url: str, document_type: str, title: str,
            publication_date: date | None = None, fiscal_period: str | None = None,
            source_code: str = "manual_document") -> UUID:
        if document_type not in DOCUMENT_TYPES:
            raise ValueError(f"document_type must be one of {', '.join(DOCUMENT_TYPES)}")
        if not url.lower().startswith(("https://", "http://")):
            raise ValueError("url must start with http:// or https://")
        with self.engine.begin() as conn:
            return conn.execute(text(
                """
                insert into app.company_documents
                  (company_id, source_id, document_type, document_title, document_url, publication_date, fiscal_period)
                select :c, source_id, :t, :title, :url, :pub, :fp from app.data_sources where source_code = :src
                on conflict (company_id, document_url) do update
                  set document_title = excluded.document_title,
                      document_type = excluded.document_type,
                      publication_date = coalesce(excluded.publication_date, app.company_documents.publication_date),
                      fiscal_period = coalesce(excluded.fiscal_period, app.company_documents.fiscal_period)
                returning document_id
                """
            ), {"c": company_id, "t": document_type, "title": title, "url": url, "pub": publication_date,
                "fp": fiscal_period, "src": source_code}).scalar_one()

    # ---------- processing ----------

    def ingest_pending(self, limit: int = 20, include_failed: bool = False) -> IngestResult:
        statuses = ["pending", "failed"] if include_failed else ["pending"]
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                """
                select document_id, document_url, file_sha256 from app.company_documents
                where extraction_status = any(:st)
                order by publication_date desc nulls last, collected_at
                limit :limit
                """
            ), {"st": statuses, "limit": limit}).mappings().all()
        result = IngestResult()
        for row in rows:
            self.ingest(row["document_id"], row["document_url"], row["file_sha256"], result)
        return result

    def ingest(self, document_id: UUID, url: str, previous_sha: str | None, result: IngestResult) -> None:
        result.processed += 1
        try:
            data = self._download(url)
        except Exception as exc:  # noqa: BLE001 - record any download failure on the row
            self._set_status(document_id, "failed", error=f"download: {str(exc)[:300]}")
            result.failed += 1
            result.errors.append(f"{url}: {exc}")
            return

        if not data.startswith(b"%PDF"):
            self._set_status(document_id, "not_pdf", error="the link does not lead to a PDF file")
            result.not_pdf += 1
            return

        sha = hashlib.sha256(data).hexdigest()
        if sha == previous_sha:
            self._set_status(document_id, "extracted")
            result.unchanged += 1
            return

        try:
            pages = extract_pages(data)
        except Exception as exc:  # noqa: BLE001 - damaged or encrypted PDFs
            self._set_status(document_id, "failed", sha=sha, error=f"pdf: {type(exc).__name__}: {str(exc)[:200]}")
            result.failed += 1
            return

        total_chars = sum(len(p.strip()) for p in pages)
        if not pages or total_chars / len(pages) < MIN_CHARS_PER_PAGE:
            self._set_status(document_id, "needs_ocr", sha=sha, pages=len(pages),
                             error="little or no text layer; likely a scanned document")
            result.needs_ocr += 1
            return

        chunks = chunk_pages(pages)
        with self.engine.begin() as conn:
            conn.execute(text("delete from app.document_chunks where document_id = :d"), {"d": document_id})
            conn.execute(text(
                """
                insert into app.document_chunks
                  (document_id, chunk_no, page_from, page_to, content, word_count, content_hash)
                values (:d, :n, :pf, :pt, :content, :wc, :h)
                """
            ), [{"d": document_id, "n": c.chunk_no, "pf": c.page_from, "pt": c.page_to, "content": c.content,
                 "wc": c.word_count, "h": hashlib.sha256(c.content.encode()).hexdigest()} for c in chunks])
            self._set_status(document_id, "extracted", sha=sha, pages=len(pages), conn=conn)
        result.extracted += 1

    # ---------- helpers ----------

    def _download(self, url: str) -> bytes:
        with self.client.stream("GET", url) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for part in response.iter_bytes():
                size += len(part)
                if size > MAX_PDF_BYTES:
                    raise ValueError(f"file larger than {MAX_PDF_BYTES // 1_000_000} MB")
                chunks.append(part)
        return b"".join(chunks)

    def _set_status(self, document_id: UUID, status: str, sha: str | None = None, pages: int | None = None,
                    error: str | None = None, conn=None) -> None:  # noqa: ANN001
        stmt = text(
            """
            update app.company_documents set
              extraction_status = :status,
              extraction_error = :error,
              file_sha256 = coalesce(:sha, file_sha256),
              page_count = coalesce(:pages, page_count),
              extracted_at = case when :status = 'extracted' then :now else extracted_at end
            where document_id = :d
            """
        )
        params = {"status": status, "error": error, "sha": sha, "pages": pages, "d": document_id,
                  "now": datetime.now(UTC)}
        if conn is not None:
            conn.execute(stmt, params)
        else:
            with self.engine.begin() as c:
                c.execute(stmt, params)
