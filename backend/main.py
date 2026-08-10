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
    # V0: create tables directly from the models. Switch to Alembic migrations
    # before this app holds data you can't afford to lose (see CLAUDE.md).
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
