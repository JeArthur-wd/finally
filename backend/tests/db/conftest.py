"""Fixtures for database tests: every test gets a fresh tmp_path SQLite DB."""

import pytest

from app import db
from app.db import connection


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Initialise a fresh DB in tmp_path; restore the module path afterwards."""
    monkeypatch.setattr(connection, "_db_path", None)
    monkeypatch.delenv("DB_PATH", raising=False)
    path = str(tmp_path / "t.db")
    db.init_db(path)
    yield path
