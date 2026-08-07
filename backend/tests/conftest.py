import os

import pytest

# Must be set BEFORE importing anything from `config`/`backend` so the app
# picks up an isolated, throwaway SQLite DB for every test run.
os.environ["AUTH_ENABLED"] = "false"
os.environ["DATABASE_URL"] = "sqlite:///./test_community_manager.db"
os.environ["SESSION_SECRET"] = "test-secret"


@pytest.fixture()
def client():
    # Imported lazily so the env vars above are set first.
    from fastapi.testclient import TestClient

    from backend.database import Base, engine
    from backend.main import app

    with TestClient(app) as c:
        yield c

    # Reset the DB between tests: drop everything, then close all pooled
    # connections before removing the file (otherwise a lingering pooled
    # connection can keep serving stale data to the next test even after
    # the file on disk has been deleted).
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if os.path.exists("test_community_manager.db"):
        os.remove("test_community_manager.db")
