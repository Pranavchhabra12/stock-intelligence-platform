"""Content: news articles, article-company links, company documents and text chunks.

Copyright: articles keep a headline, link and the publisher's own short
description only, never the full text. Documents are exchange filings and
company publications; their extracted text is stored in page-ranged chunks
for analysis, always with the original URL.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-22
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- Phrases that name OTHER companies sharing a word with this one
        -- (e.g. "Reliance Power" for Reliance Industries). Removed from news text
        -- before matching, so those stories are not linked to the wrong company.
        alter table app.companies
          add column news_exclude_phrases text[] not null default '{}';

        create table app.news_articles (
          article_id    uuid primary key default gen_random_uuid(),
          source_id     smallint not null references app.data_sources (source_id),
          canonical_url text not null,
          -- sha256 of canonical_url: the dedupe key
          url_hash      text not null unique check (url_hash ~ '^[0-9a-f]{64}$'),
          headline      text not null check (length(headline) between 1 and 1000),
          -- the publisher's own short description, capped; never the article body
          snippet       text check (length(snippet) <= 600),
          publisher     text,
          published_at  timestamptz,
          collected_at  timestamptz not null default now(),
          language      text,
          -- filled by AI classification in Phase 4
          category      text,
          -- sha256 of the normalised headline: catches the same story syndicated under other URLs
          content_hash  text not null check (content_hash ~ '^[0-9a-f]{64}$')
        );
        create index news_articles_published on app.news_articles (published_at desc);
        create index news_articles_content_hash on app.news_articles (content_hash);

        create table app.article_companies (
          article_id      uuid not null references app.news_articles (article_id) on delete cascade,
          company_id      uuid not null references app.companies (company_id) on delete cascade,
          relevance_score numeric(4, 3) not null check (relevance_score between 0 and 1),
          -- where the company was found: in the headline, only in the description,
          -- or only implied by the search query that returned the article
          mention_type    text not null check (mention_type in ('headline', 'snippet', 'query')),
          linked_by       text not null default 'rule' check (linked_by in ('rule', 'ai', 'manual')),
          created_at      timestamptz not null default now(),
          primary key (article_id, company_id)
        );
        create index article_companies_company on app.article_companies (company_id, relevance_score desc);

        create table app.company_documents (
          document_id       uuid primary key default gen_random_uuid(),
          company_id        uuid not null references app.companies (company_id) on delete restrict,
          source_id         smallint not null references app.data_sources (source_id),
          document_type     text not null check (document_type in
                              ('annual_report', 'quarterly_results', 'investor_presentation',
                               'exchange_filing', 'earnings_transcript', 'other_disclosure')),
          document_title    text not null,
          document_url      text not null,
          publication_date  date,
          fiscal_period     text,
          file_sha256       text check (file_sha256 ~ '^[0-9a-f]{64}$'),
          page_count        integer check (page_count >= 0),
          extraction_status text not null default 'pending' check (extraction_status in
                              ('pending', 'extracted', 'needs_ocr', 'not_pdf', 'failed')),
          extraction_error  text,
          storage_path      text,
          collected_at      timestamptz not null default now(),
          extracted_at      timestamptz,
          unique (company_id, document_url)
        );
        create index company_documents_company on app.company_documents (company_id, publication_date desc);
        create index company_documents_status on app.company_documents (extraction_status);

        create table app.document_chunks (
          chunk_id      bigint generated always as identity primary key,
          document_id   uuid not null references app.company_documents (document_id) on delete cascade,
          chunk_no      integer not null check (chunk_no >= 0),
          page_from     integer not null check (page_from >= 1),
          page_to       integer not null,
          content       text not null,
          word_count    integer not null check (word_count >= 0),
          content_hash  text not null check (content_hash ~ '^[0-9a-f]{64}$'),
          unique (document_id, chunk_no),
          check (page_to >= page_from)
        );

        alter table app.news_articles enable row level security;
        alter table app.article_companies enable row level security;
        alter table app.company_documents enable row level security;
        alter table app.document_chunks enable row level security;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists app.document_chunks;
        drop table if exists app.company_documents;
        drop table if exists app.article_companies;
        drop table if exists app.news_articles;
        alter table app.companies drop column if exists news_exclude_phrases;
        """
    )
