"""Master data: companies, exchange listings, search aliases, provider identifiers.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- One row per issuer. A company listed on NSE and BSE has ONE row here.
        create table app.companies (
          company_id   uuid primary key default gen_random_uuid(),
          company_name text not null,
          legal_name   text,
          -- MCA Corporate Identification Number, e.g. L17110MH1973PLC019786
          cin          text unique
                       check (cin ~ '^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$'),
          sector       text,
          industry     text,
          description  text,
          website      text,
          is_active    boolean not null default true,
          created_at   timestamptz not null default now(),
          updated_at   timestamptz not null default now()
        );

        -- One row per security per exchange. ISIN identifies the security,
        -- so it lives here rather than on companies.
        create table app.company_listings (
          listing_id    uuid primary key default gen_random_uuid(),
          company_id    uuid not null references app.companies (company_id) on delete restrict,
          exchange      text not null check (exchange in ('NSE', 'BSE')),
          -- NSE symbol, or BSE scrip id
          symbol        text not null check (symbol = upper(symbol)),
          -- BSE scrip code, e.g. 500325
          exchange_code text,
          isin          text check (isin ~ '^IN[A-Z0-9]{9}[0-9]$'),
          -- NSE series, e.g. EQ
          series        text,
          currency      char(3) not null default 'INR',
          listed_on     date,
          delisted_on   date,
          is_active     boolean not null default true,
          created_at    timestamptz not null default now(),
          updated_at    timestamptz not null default now(),
          check (delisted_on is null or listed_on is null or delisted_on >= listed_on)
        );

        -- Symbols can be reused after a delisting, so uniqueness applies to active rows.
        create unique index company_listings_symbol_active
          on app.company_listings (exchange, symbol) where is_active;
        create unique index company_listings_exchange_code
          on app.company_listings (exchange, exchange_code) where exchange_code is not null;
        create unique index company_listings_isin_active
          on app.company_listings (exchange, isin) where isin is not null and is_active;
        create index company_listings_company on app.company_listings (company_id);
        create index company_listings_isin on app.company_listings (isin);

        -- Names people search by: RIL, TCS, Tata Consultancy, former names, etc.
        create table app.company_aliases (
          alias_id   bigint generated always as identity primary key,
          company_id uuid not null references app.companies (company_id) on delete cascade,
          alias      text not null,
          alias_norm text generated always as
                     (btrim(regexp_replace(lower(alias), '[^a-z0-9]+', ' ', 'g'))) stored,
          alias_type text not null check (alias_type in
                     ('name', 'legal_name', 'former_name', 'abbreviation', 'symbol')),
          created_at timestamptz not null default now(),
          unique (company_id, alias_norm)
        );
        create index company_aliases_trgm
          on app.company_aliases using gin (alias_norm extensions.gin_trgm_ops);

        -- Each provider names instruments its own way (RELIANCE.NS, NSE_EQ + ISIN, ...).
        create table app.listing_provider_ids (
          listing_id      uuid not null references app.company_listings (listing_id) on delete cascade,
          source_id       smallint not null references app.data_sources (source_id),
          provider_symbol text not null,
          created_at      timestamptz not null default now(),
          primary key (listing_id, source_id),
          unique (source_id, provider_symbol)
        );

        create trigger set_updated_at before update on app.companies
          for each row execute function app.set_updated_at();
        create trigger set_updated_at before update on app.company_listings
          for each row execute function app.set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists app.listing_provider_ids;
        drop table if exists app.company_aliases;
        drop table if exists app.company_listings;
        drop table if exists app.companies;
        """
    )
