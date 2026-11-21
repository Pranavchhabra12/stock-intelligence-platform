"""Financials: metric definitions, reporting periods and reported values.

Only five values are stored as reported. Everything else (market cap, P/E,
P/B, dividend yield, ROE, growth) is calculated in analytics views in Phase 6,
so derived numbers can always be traced back to stored ones.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-22
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table app.metric_definitions (
          metric_code text primary key check (metric_code ~ '^[a-z][a-z0-9_]*$'),
          label       text not null,
          unit        text not null check (unit in
                        ('INR', 'INR_PER_SHARE', 'SHARES', 'PERCENT', 'RATIO')),
          statement   text not null check (statement in
                        ('income_statement', 'balance_sheet', 'market', 'derived')),
          is_derived  boolean not null,
          description text not null
        );

        insert into app.metric_definitions
          (metric_code, label, unit, statement, is_derived, description) values
          ('total_revenue', 'Revenue (total income)', 'INR', 'income_statement', false,
           'Total revenue for the period as reported. For banks this is total income.'),
          ('net_profit', 'Net profit', 'INR', 'income_statement', false,
           'Net income attributable to shareholders for the period.'),
          ('eps', 'Earnings per share', 'INR_PER_SHARE', 'income_statement', false,
           'Basic earnings per share for the period.'),
          ('shareholders_equity', 'Shareholders'' equity', 'INR', 'balance_sheet', false,
           'Equity attributable to shareholders at period end.'),
          ('shares_outstanding', 'Shares outstanding', 'SHARES', 'balance_sheet', false,
           'Ordinary shares outstanding at period end.'),
          ('market_cap', 'Market cap', 'INR', 'derived', true,
           'Shares outstanding x latest close.'),
          ('pe_ratio', 'P/E ratio', 'RATIO', 'derived', true,
           'Latest close / EPS over the last 12 months.'),
          ('pb_ratio', 'P/B ratio', 'RATIO', 'derived', true,
           'Latest close / (shareholders'' equity / shares outstanding).'),
          ('dividend_yield', 'Dividend yield', 'PERCENT', 'derived', true,
           'Dividends per share over the last 12 months / latest close.'),
          ('roe', 'Return on equity', 'PERCENT', 'derived', true,
           'Net profit over the last 12 months / shareholders'' equity.'),
          ('revenue_growth_yoy', 'Revenue growth (YoY)', 'PERCENT', 'derived', true,
           'Revenue vs the same period a year earlier.'),
          ('profit_growth_yoy', 'Profit growth (YoY)', 'PERCENT', 'derived', true,
           'Net profit vs the same period a year earlier.');

        -- One reporting period per company, period type, end date, basis and source.
        create table app.financial_periods (
          period_id      bigint generated always as identity primary key,
          company_id     uuid not null references app.companies (company_id) on delete restrict,
          period_type    text not null check (period_type in ('quarterly', 'annual')),
          period_end     date not null,
          -- Indian fiscal year, named by the year it ends in March (FY2026 = Apr 2025 - Mar 2026).
          fiscal_year    smallint not null,
          -- 1 = Apr-Jun ... 4 = Jan-Mar; null for annual periods.
          fiscal_quarter smallint check (fiscal_quarter between 1 and 4),
          -- Yahoo Finance does not say which, so its rows are 'unknown'.
          consolidation  text not null default 'unknown'
                         check (consolidation in ('consolidated', 'standalone', 'unknown')),
          revision       smallint not null default 0,
          filing_date    date,
          source_id      smallint not null references app.data_sources (source_id),
          fetched_at     timestamptz not null default now(),
          created_at     timestamptz not null default now(),
          unique (company_id, period_type, period_end, consolidation, source_id, revision),
          check ((period_type = 'quarterly') = (fiscal_quarter is not null))
        );
        create index financial_periods_company on app.financial_periods (company_id, period_end);

        -- Reported values only; derived metrics are never stored here.
        create table app.financial_metrics (
          period_id   bigint not null references app.financial_periods (period_id) on delete cascade,
          metric_code text not null references app.metric_definitions (metric_code),
          value       numeric(24, 4) not null,
          primary key (period_id, metric_code)
        );

        create or replace function app.reject_derived_metric() returns trigger
        language plpgsql as $$
        begin
          if (select is_derived from app.metric_definitions where metric_code = new.metric_code) then
            raise exception 'metric % is derived and must not be stored', new.metric_code;
          end if;
          return new;
        end $$;

        create trigger reject_derived_metric before insert or update on app.financial_metrics
          for each row execute function app.reject_derived_metric();

        alter table app.metric_definitions enable row level security;
        alter table app.financial_periods enable row level security;
        alter table app.financial_metrics enable row level security;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists app.financial_metrics;
        drop function if exists app.reject_derived_metric();
        drop table if exists app.financial_periods;
        drop table if exists app.metric_definitions;
        """
    )
