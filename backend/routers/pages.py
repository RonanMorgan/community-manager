import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from backend.auth import CurrentUser, require_admin
from backend.database import get_db
from backend.models import Category, Group, ToolName

router = APIRouter()
templates = Jinja2Templates(directory="backend/templates")

UNCATEGORIZED_SECTION = "Autres"


def _resolve_icon_url(app: dict) -> str | None:
    """Authentik's `meta_icon` can be a relative path to an uploaded media
    file (e.g. '/media/application-icons/foo.png'), which only resolves
    against the Authentik server itself. `meta_icon_url` is normally the
    absolute, ready-to-use URL — prefer it, and fall back to manually
    prefixing `meta_icon` with AUTHENTIK_URL if only that's present."""
    icon_url = app.get("meta_icon_url") or app.get("meta_icon")
    if not icon_url:
        return None
    if icon_url.startswith("http://") or icon_url.startswith("https://"):
        return icon_url
    return f"{config.AUTHENTIK_URL.rstrip('/')}/{icon_url.lstrip('/')}"


def _group_applications_by_section(applications: list[dict]) -> list[tuple[str, list[dict]]]:
    """Groups applications by their Authentik `group` field (the same field
    used by Authentik's own Library page to show sections). Apps without a
    group are put in a catch-all 'Autres' section, listed last."""
    sections: dict[str, list[dict]] = {}
    for app in applications:
        section_name = (app.get("group") or "").strip() or UNCATEGORIZED_SECTION
        sections.setdefault(section_name, []).append(app)

    for apps in sections.values():
        apps.sort(key=lambda a: (a.get("name") or "").lower())

    ordered_names = sorted(n for n in sections if n != UNCATEGORIZED_SECTION)
    if UNCATEGORIZED_SECTION in sections:
        ordered_names.append(UNCATEGORIZED_SECTION)

    return [(name, sections[name]) for name in ordered_names]


@router.get("/", response_class=HTMLResponse)
def root():
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/groups")


@router.get("/applications", response_class=HTMLResponse)
def applications_page(request: Request, user: CurrentUser = Depends(require_admin)):
    sections: list[tuple[str, list[dict]]] = []
    error = None
    try:
        from clients.authentik_client import AuthentikClient

        if not config.AUTHENTIK_URL or not config.AUTHENTIK_TOKEN:
            error = "Authentik n'est pas configuré (AUTHENTIK_URL / AUTHENTIK_TOKEN manquants)."
        else:
            client = AuthentikClient(base_url=config.AUTHENTIK_URL, token=config.AUTHENTIK_TOKEN)
            applications = client.list_applications()
            if applications is None:
                error = (
                    "Impossible de récupérer les applications depuis Authentik "
                    "(le token API est peut-être invalide ou expiré — voir les logs du serveur pour le détail)."
                )
            else:
                for app in applications:
                    app["resolved_icon_url"] = _resolve_icon_url(app)
                sections = _group_applications_by_section(applications)
    except Exception as e:  # noqa: BLE001 - surface any client error to the page
        logging.exception("Failed to fetch Authentik applications")
        error = str(e)

    return templates.TemplateResponse(
        request,
        "applications.html",
        {"user": user, "sections": sections, "error": error},
    )


@router.get("/groups", response_class=HTMLResponse)
def groups_page(request: Request, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    groups = db.execute(select(Group).order_by(Group.name)).scalars().all()

    groups_by_category = {
        Category.PROJET: [],
        Category.POLE: [],
        Category.ANTENNE: [],
    }
    uncategorized_groups = []
    for group in groups:
        if group.category in groups_by_category:
            groups_by_category[group.category].append(group)
        else:
            uncategorized_groups.append(group)

    return templates.TemplateResponse(
        request,
        "groups.html",
        {
            "user": user,
            "projet_groups": groups_by_category[Category.PROJET],
            "pole_groups": groups_by_category[Category.POLE],
            "antenne_groups": groups_by_category[Category.ANTENNE],
            "uncategorized_groups": uncategorized_groups,
            "categories": [c.value for c in Category],
            # Outline is fully wired (create/rename/add/remove); Mattermost is
            # read/discovery-only for now (via /api/sync), see CLAUDE.md.
            "table_tools": ["outline", "mattermost"],
            # All tools shown as checkboxes in the "create group" modal; only
            # the ones with a provisioner (see outline_service.PROVISIONERS)
            # are enabled — the others are visible but disabled.
            "available_tools": [t.value for t in ToolName if t != ToolName.MATTERMOST_ADMIN],
            "functional_tools": ["outline"],
        },
    )
