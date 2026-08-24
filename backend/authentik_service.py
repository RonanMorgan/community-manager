"""
Thin service layer between the API routes and clients/authentik_client.py.

Authentik is the source of truth for groups (see CLAUDE.md §4-bis): unlike
Outline/Mattermost, an Authentik group isn't tracked as a `GroupResource`
row — it IS the `Group` itself, linked via `Group.authentik_group_id`.
This module only covers what's needed for the "Créer un groupe" button to
also create the corresponding group in Authentik.
"""
from clients.authentik_client import AuthentikClient


class AuthentikError(Exception):
    """Raised for any Authentik operation failure that should surface as an
    explicit, user-facing error."""


def get_client() -> AuthentikClient:
    import config

    if not config.AUTHENTIK_URL or not config.AUTHENTIK_TOKEN:
        raise AuthentikError("Authentik is not configured (AUTHENTIK_URL / AUTHENTIK_TOKEN missing).")
    return AuthentikClient(base_url=config.AUTHENTIK_URL, token=config.AUTHENTIK_TOKEN)


def create_group(name: str) -> dict:
    client = get_client()
    result = client.create_group(name)
    if not result:
        raise AuthentikError(
            f"Échec de la création du groupe Authentik '{name}' (il existe peut-être déjà — voir les logs serveur)."
        )
    return result
