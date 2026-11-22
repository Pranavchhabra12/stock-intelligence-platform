"""AI analysis: per-article sentiment, report summaries, and daily sentiment history.

AI output is commentary, never a financial figure: nothing here feeds the
financial tables, and every row records the model and prompt version that
produced it. A new prompt version or model creates new rows instead of
overwriting old ones.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-22
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table app.ai_analyses (
          analysis_id      uuid primary key default gen_random_uuid(),
          company_id       uuid not null references app.companies (company_id) on delete cascade,
          analysis_type    text not null check (analysis_type in ('article_sentiment', 'document_summary')),
          -- exactly one subject: the article or the document that was analysed
          article_id       uuid references app.news_articles (article_id) on delete cascade,
          document_id      uuid references app.company_documents (document_id) on delete cascade,
          model            text not null check (length(model) between 1 and 100),
          prompt_version   text not null check (length(prompt_version) between 1 and 20),
          status           text not null check (status in ('completed', 'failed')),
          -- article sentiment (about this company, not the market in general)
          sentiment_label  text check (sentiment_label in ('positive', 'neutral', 'negative')),
          sentiment_score  numeric(4, 3) check (sentiment_score between -1 and 1),
          confidence       numeric(4, 3) check (confidence between 0 and 1),
          -- short explanation (article) or the summary itself (document)
          summary          text check (length(summary) <= 4000),
          -- document summaries: [{"point": ..., "pages": [12, 13]}], every page checked against the source
          key_points       jsonb not null default '[]'::jsonb,
          risks            jsonb not null default '[]'::jsonb,
          input_hash       text not null check (input_hash ~ '^[0-9a-f]{64}$'),
          input_tokens     integer check (input_tokens >= 0),
          output_tokens    integer check (output_tokens >= 0),
          error            text check (length(error) <= 1000),
          created_at       timestamptz not null default now(),
          constraint ai_analyses_one_subject check ((article_id is null) <> (document_id is null)),
          constraint ai_analyses_subject_matches_type check (
            (analysis_type = 'article_sentiment' and article_id is not null)
            or (analysis_type = 'document_summary' and document_id is not null)),
          constraint ai_analyses_completed_has_result check (
            status <> 'completed'
            or (analysis_type = 'article_sentiment' and sentiment_label is not null and sentiment_score is not null)
            or (analysis_type = 'document_summary' and summary is not null))
        );
        create unique index ai_analyses_article_key
          on app.ai_analyses (company_id, article_id, model, prompt_version) where article_id is not null;
        create unique index ai_analyses_document_key
          on app.ai_analyses (company_id, document_id, model, prompt_version) where document_id is not null;
        create index ai_analyses_company_created on app.ai_analyses (company_id, analysis_type, created_at desc);

        -- One row per company per day per methodology. Rows are only written for
        -- finished days and never updated; a new methodology gets a new version.
        create table app.sentiment_history (
          company_id           uuid not null references app.companies (company_id) on delete cascade,
          as_of_date           date not null,
          methodology_version  text not null check (length(methodology_version) between 1 and 20),
          article_count        integer not null check (article_count > 0),
          positive_count       integer not null check (positive_count >= 0),
          neutral_count        integer not null check (neutral_count >= 0),
          negative_count       integer not null check (negative_count >= 0),
          -- relevance-weighted mean of article scores, -1 to 1
          sentiment_score      numeric(4, 3) not null check (sentiment_score between -1 and 1),
          computed_at          timestamptz not null default now(),
          primary key (company_id, as_of_date, methodology_version),
          check (positive_count + neutral_count + negative_count = article_count)
        );

        alter table app.ai_analyses enable row level security;
        alter table app.sentiment_history enable row level security;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists app.sentiment_history;
        drop table if exists app.ai_analyses;
        """
    )
