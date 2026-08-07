import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from backend.auth import CurrentUser, require_admin
from backend.database import get_db
from backend.models import Group, ToolName

router = APIRouter()
templates = Jinja2Templates(directory="backend/templates")


@router.get("/", response_class=HTMLResponse)
def root():
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/groups")


@router.get("/applications", response_class=HTMLResponse)
def applications_page(request: Request, user: CurrentUser = Depends(require_admin)):
    applications = []
    error = None
    try:
        from clients.authentik_client import AuthentikClient

        if not config.AUTHENTIK_URL or not config.AUTHENTIK_TOKEN:
            error = "Authentik n'est pas configuré (AUTHENTIK_URL / AUTHENTIK_TOKEN manquants)."
        else:
            client = AuthentikClient(base_url=config.AUTHENTIK_URL, token=config.AUTHENTIK_TOKEN)
            applications = client.list_applications()
    except Exception as e:  # noqa: BLE001 - surface any client error to the page
        logging.exception("Failed to fetch Authentik applications")
        error = str(e)

    return templates.TemplateResponse(
        request,
        "applications.html",
        {"user": user, "applications": applications, "error": error},
    )


@router.get("/groups", response_class=HTMLResponse)
def groups_page(request: Request, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    groups = db.execute(select(Group).order_by(Group.name)).scalars().all()
    return templates.TemplateResponse(
        request,
        "groups.html",
        {
            "user": user,
            "groups": groups,
            # Only Outline is wired up to a real tool in V0 (table column shown).
            "table_tools": ["outline"],
            # All tools shown as checkboxes in the "create group" modal; the
            # non-Outline ones are disabled until their provisioner exists
            # (see backend/outline_service.py PROVISIONERS).
            "available_tools": [t.value for t in ToolName],
            "functional_tools": ["outline"],
        },
    )
