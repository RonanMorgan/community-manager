"""
Thin service layer between the API routes and clients/outline_client.py.

Kept separate from the routes so the "only Outline is wired up in V0, other
tools are stubs" decision lives in one place (see `PROVISIONERS` at the
bottom of this module, used by backend/routers/api.py when creating a
group's resources).
"""

from clients.outline_client import OutlineClient
from backend.models import ToolName


class OutlineError(Exception):
    """Raised for any Outline operation failure that should surface as an
    explicit, user-facing error (per the product decision: no silent
    failures, e.g. when adding a user who doesn't exist yet in Outline)."""


def get_client() -> OutlineClient:
    import config

    if not config.OUTLINE_URL or not config.OUTLINE_TOKEN:
        raise OutlineError("Outline is not configured (OUTLINE_URL / OUTLINE_TOKEN missing).")
    return OutlineClient(base_url=config.OUTLINE_URL, token=config.OUTLINE_TOKEN)


def create_collection(display_name: str) -> dict:
    client = get_client()
    collection = client.create_group(display_name)
    if not collection:
        raise OutlineError(f"Failed to create the Outline collection '{display_name}'.")
    return collection


def find_collection_by_name(name: str) -> dict | None:
    """Looks up a collection with an EXACT name match (used by the
    Authentik-driven group synchronization). Returns None if not found."""
    client = get_client()
    result = client.list_collections(name=name)
    if result is None:
        raise OutlineError(f"Failed to search Outline collections for name '{name}'.")
    return result or None


def search_collections(query: str) -> list[dict]:
    """Substring search for the "reattach this resource" UI (see
    backend/routers/api.py::search_resource_candidates). Unlike
    find_collection_by_name, returns every plausible match, not just an
    exact one."""
    client = get_client()
    results = client.search_collections(query)
    if results is None:
        raise OutlineError(f"Failed to search Outline collections for '{query}'.")
    return results


def rename_collection(collection_id: str, new_name: str) -> None:
    client = get_client()
    ok = client.update_collection_name(collection_id, new_name)
    if not ok:
        raise OutlineError(f"Failed to rename Outline collection '{collection_id}' to '{new_name}'.")


def list_members_with_permission(collection_id: str) -> list[dict]:
    """Returns [{"id", "name", "email", "permission"}] fetched LIVE from Outline."""
    client = get_client()
    memberships = client.get_collection_memberships_with_permission(collection_id)
    if memberships is None:
        raise OutlineError(f"Failed to fetch members of Outline collection '{collection_id}'.")
    return [
        {
            "id": m["user"]["id"],
            "name": m["user"].get("name", ""),
            "email": m["user"].get("email"),
            "permission": m.get("permission") or "read",
        }
        for m in memberships
    ]


def add_user(collection_id: str, email: str, permission: str) -> None:
    client = get_client()
    user = client.get_user_by_email(email)
    if not user:
        raise OutlineError(
            f"Aucun utilisateur Outline trouvé pour l'email '{email}'. "
            "Cette personne doit s'être connectée au moins une fois à Outline "
            "(provisioning automatique via OIDC) avant de pouvoir être ajoutée à une collection."
        )
    ok = client.add_user_to_collection(collection_id, user["id"], permission=permission)
    if not ok:
        raise OutlineError(f"Échec de l'ajout de '{email}' à la collection Outline '{collection_id}'.")


def remove_user(collection_id: str, user_id: str) -> None:
    client = get_client()
    ok = client.remove_user_from_collection(collection_id, user_id)
    if not ok:
        raise OutlineError(f"Échec de la suppression de l'utilisateur '{user_id}' de la collection Outline.")


# Registry so backend/routers/api.py can create resources generically for
# every tool checked at group-creation time, without hardcoding "if outline".
# Add an entry here (and a matching service module) when a new tool is wired up.
PROVISIONERS = {
    ToolName.OUTLINE: create_collection,
}
