"""Market data: daily prices and corporate actions.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-22
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- One row per listing per trading day. Upserts keep it idempotent.
        create table app.daily_prices (
          listing_id  uuid not null references app.company_listings (listing_id) on delete restrict,
          trade_date  date not null,
          open_price  numeric(14, 4) not null check (open_price > 0),
          high_price  numeric(14, 4) not null check (high_price > 0),
          low_price   numeric(14, 4) not null check (low_price > 0),
          close_price numeric(14, 4) not null check (close_price > 0),
          -- Provider's dividend-adjusted close, if it supplies one. Informational only.
          adj_close   numeric(14, 4) check (adj_close > 0),
          volume      bigint not null check (volume >= 0),
          -- raw = as traded; split_adjusted = earlier prices rescaled for splits/bonuses;
          -- unknown = the provider does not say
          price_basis text not null check (price_basis in ('raw', 'split_adjusted', 'unknown')),
          -- each row records the provider that actually supplied it (fallbacks included)
          source_id   smallint not null references app.data_sources (source_id),
          fetched_at  timestamptz not null default now(),
          primary key (listing_id, trade_date),
          check (high_price >= low_price),
          check (open_price between low_price and high_price),
          check (close_price between low_price and high_price)
        );
        create index daily_prices_trade_date on app.daily_prices (trade_date);

        comment on column app.daily_prices.price_basis is
          'Yahoo Finance prices are split-adjusted: past prices are rescaled after a split or bonus.';

        -- Dividends, splits and bonuses, per listing.
        create table app.corporate_actions (
          action_id   bigint generated always as identity primary key,
          listing_id  uuid not null references app.company_listings (listing_id) on delete restrict,
          ex_date     date not null,
          action_type text not null check (action_type in ('dividend', 'split', 'bonus')),
          -- Split/bonus factor: new shares per old share (e.g. 2 for a 1:1 bonus).
          ratio       numeric(12, 6) check (ratio > 0),
          -- Dividend per share, INR.
          amount      numeric(14, 4) check (amount > 0),
          source_id   smallint not null references app.data_sources (source_id),
          fetched_at  timestamptz not null default now(),
          unique (listing_id, ex_date, action_type),
          check ((action_type = 'dividend') = (amount is not null)),
          check ((action_type in ('split', 'bonus')) = (ratio is not null))
        );

        alter table app.daily_prices enable row level security;
        alter table app.corporate_actions enable row level security;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists app.corporate_actions;
        drop table if exists app.daily_prices;
        """
    )
