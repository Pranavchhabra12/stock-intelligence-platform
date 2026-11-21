"""Document download, text extraction, chunking and the reports API."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from backend.services.document_service import DocumentService, IngestResult, chunk_pages
from backend.tests.pdf_factory import make_pdf
from backend.tests.test_news import clean_news

TEXT_PAGE = "The company reported strong revenue growth across all segments this year. " * 6


@pytest.fixture
def clean(engine: Engine) -> Iterator[None]:
    clean_news(engine)
    yield
    clean_news(engine)


def company_id(engine: Engine, name: str = "Infosys"):  # noqa: ANN201
    with engine.connect() as conn:
        return conn.execute(text("select company_id from app.companies where company_name = :n"),
                            {"n": name}).scalar_one()


def service(engine: Engine, files: dict[str, bytes]) -> DocumentService:
    def handler(request: httpx.Request) -> httpx.Response:
        body = files.get(str(request.url))
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

    return DocumentService(engine, client=httpx.Client(transport=httpx.MockTransport(handler)))


def document(engine: Engine, url: str) -> dict:
    with engine.connect() as conn:
        return dict(conn.execute(text(
            """
            select d.extraction_status, d.page_count, d.file_sha256, d.extraction_error,
                   count(c.chunk_id) as chunks, min(c.page_from) as first_page, max(c.page_to) as last_page
            from app.company_documents d left join app.document_chunks c using (document_id)
            where d.document_url = :u group by d.document_id
            """
        ), {"u": url}).mappings().one())


def test_chunks_follow_page_boundaries() -> None:
    pages = ["one two three", "", "four five", "six " * 10]
    chunks = chunk_pages(pages, target_words=6)
    assert [(c.page_from, c.page_to) for c in chunks] == [(1, 3), (4, 4)]
    assert chunks[0].content == "one two three\n\nfour five"
    assert chunk_pages(["", ""]) == []


def test_pdf_is_extracted_into_chunks_and_not_reprocessed(engine: Engine, clean: None) -> None:
    url = "https://ir.example.com/annual-report.pdf"
    svc = service(engine, {url: make_pdf([TEXT_PAGE, TEXT_PAGE, TEXT_PAGE])})
    svc.add(company_id(engine), url, "annual_report", "Annual Report 2025-26")

    result = svc.ingest_pending()
    assert result.extracted == 1
    doc = document(engine, url)
    assert doc["extraction_status"] == "extracted" and doc["page_count"] == 3
    assert doc["chunks"] >= 1 and doc["first_page"] == 1 and doc["last_page"] == 3

    # Processing the same file again changes nothing.
    again = IngestResult()
    svc.ingest(*_row(engine, url), again)
    assert again.unchanged == 1 and document(engine, url)["chunks"] == doc["chunks"]


def test_changed_file_is_re_extracted(engine: Engine, clean: None) -> None:
    url = "https://ir.example.com/results.pdf"
    files = {url: make_pdf([TEXT_PAGE])}
    svc = service(engine, files)
    svc.add(company_id(engine), url, "quarterly_results", "Q2 results")
    svc.ingest_pending()
    first_sha = document(engine, url)["file_sha256"]

    files[url] = make_pdf([TEXT_PAGE, TEXT_PAGE])
    svc.ingest(*_row(engine, url), IngestResult())
    doc = document(engine, url)
    assert doc["file_sha256"] != first_sha and doc["page_count"] == 2


def test_scanned_pdf_is_flagged_not_stored_empty(engine: Engine, clean: None) -> None:
    url = "https://ir.example.com/scanned.pdf"
    svc = service(engine, {url: make_pdf(["", "", ""])})
    svc.add(company_id(engine), url, "annual_report", "Scanned report")
    assert svc.ingest_pending().needs_ocr == 1
    doc = document(engine, url)
    assert doc["extraction_status"] == "needs_ocr" and doc["chunks"] == 0


def test_non_pdf_and_missing_files(engine: Engine, clean: None) -> None:
    html, missing = "https://ir.example.com/page.html", "https://ir.example.com/gone.pdf"
    svc = service(engine, {html: b"<html>announcement page</html>"})
    cid = company_id(engine)
    svc.add(cid, html, "exchange_filing", "Announcement")
    svc.add(cid, missing, "exchange_filing", "Missing")
    result = svc.ingest_pending()
    assert result.not_pdf == 1 and result.failed == 1
    assert document(engine, html)["extraction_status"] == "not_pdf"
    assert "404" in document(engine, missing)["extraction_error"]


def test_add_validates_input(engine: Engine) -> None:
    svc = service(engine, {})
    with pytest.raises(ValueError):
        svc.add(company_id(engine), "https://x/y.pdf", "gossip", "Bad type")
    with pytest.raises(ValueError):
        svc.add(company_id(engine), "ftp://x/y.pdf", "annual_report", "Bad scheme")


def test_reports_api(client: TestClient, engine: Engine, clean: None) -> None:
    url = "https://ir.example.com/ar.pdf"
    svc = service(engine, {url: make_pdf([TEXT_PAGE, TEXT_PAGE])})
    svc.add(company_id(engine), url, "annual_report", "Annual Report", fiscal_period="FY2026")
    svc.ingest_pending()

    body = client.get("/stocks/INFY/reports").json()
    assert body["count"] == 1
    doc = body["documents"][0]
    assert doc["extraction_status"] == "extracted" and doc["page_count"] == 2
    assert doc["word_count"] > 0 and doc["fiscal_period"] == "FY2026" and doc["source"] == "manual_document"
    assert client.get("/stocks/INFY/reports", params={"document_type": "quarterly_results"}).json()["count"] == 0


def _row(engine: Engine, url: str) -> tuple:
    with engine.connect() as conn:
        r = conn.execute(text("select document_id, document_url, file_sha256 from app.company_documents "
                              "where document_url = :u"), {"u": url}).one()
    return r.document_id, r.document_url, r.file_sha256
