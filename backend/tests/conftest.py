"""Test fixtures: a fresh Postgres database per test session, migrated and seeded.

Needs a running Postgres. Point TEST_DATABASE_ADMIN_URL at any database on
that server the test user can connect to (default: local `postgres` db).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url

from backend.database.urls import normalize_database_url

ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = ROOT / "database" / "seed" / "companies.json"
ADMIN_URL = normalize_database_url(
    os.environ.get("TEST_DATABASE_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
)


def _recreate_database(name: str) -> str:
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'drop database if exists "{name}" with (force)'))
        conn.execute(text(f'create database "{name}"'))
    admin.dispose()
    return make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)


def alembic_config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "database" / "migrations"))
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _recreate_database("sip_pytest")
    command.upgrade(alembic_config(url), "head")

    os.environ["DATABASE_URL"] = url
    os.environ["APP_ENV"] = "test"
    os.environ["API_RATE_LIMIT_PER_MINUTE"] = "0"   # disabled except in its own test
    os.environ["LOG_LEVEL"] = "WARNING"

    from backend.core.config import get_settings
    from backend.database.connection import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    from backend.database.seed import seed

    eng = create_engine(database_url)
    with eng.begin() as conn:
        seed(conn, json.loads(SEED_FILE.read_text(encoding="utf-8")))
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Connection]:
    """A connection whose changes are rolled back after the test."""
    conn = engine.connect()
    trans = conn.begin()
    try:
        yield conn
    finally:
        trans.rollback()
        conn.close()


@pytest.fixture(scope="session")
def client(engine: Engine) -> Iterator[TestClient]:
    from backend.main import create_app

    with TestClient(create_app()) as c:
        yield c
