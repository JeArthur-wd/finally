"""API test fixtures: a TestClient over an app wired to the temp DB and fake source."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.services.conftest import env  # noqa: F401  (re-exported fixture)


@pytest.fixture
def client(env, tmp_path):  # noqa: F811
    app = create_app(use_lifespan=False, static_dir=str(tmp_path / "no-static"))
    with TestClient(app) as c:
        yield c
