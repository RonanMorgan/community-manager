import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import config
from backend.database import Base, engine
from backend.routers import api, auth_routes, pages

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema management: real migrations now live in migrations/ (Alembic).
    # - Postgres (docker-compose): `docker-entrypoint.sh` runs `alembic upgrade
    #   head` BEFORE this process even starts, so we do nothing here.
    # - SQLite (local dev / tests, see .env.example and backend/tests/conftest.py):
    #   for convenience we still create tables directly from the models, so you
    #   don't need to set up Alembic just to run `uvicorn backend.main:app` against
    #   a throwaway local file. This path never ALTERs an existing table, so it's
    #   safe: SQLite dev DBs are meant to be disposable, not to receive schema
    #   changes in place.
    if config.DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    if not config.AUTH_ENABLED:
        logging.warning(
            "AUTH_ENABLED=false: OIDC login is BYPASSED, every request is treated as an admin "
            f"({config.DEV_FAKE_ADMIN_EMAIL}). Do not use this in production."
        )
    yield


app = FastAPI(title="Community Manager", lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)

app.mount("/static", StaticFiles(directory="backend/static"), name="static")

app.include_router(pages.router)
app.include_router(auth_routes.router)
app.include_router(api.router)
