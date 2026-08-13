"""
Thin service layer between the API routes and clients/mattermost_client.py.

V0.1 scope: Mattermost is used for the synchronization discovery (find a
channel matching a group's name) and for listing a channel's real members
+ roles. Adding/removing users on a Mattermost channel from the UI is not
wired up yet (see CLAUDE.md) — only Outline supports that today.
"""
from clients.mattermost_client import MattermostClient, slugify


class MattermostError(Exception):
    """Raised for any Mattermost operation failure that should surface as an
    explicit, user-facing error."""


def get_client() -> MattermostClient:
    import config

    if not config.MATTERMOST_URL or not config.BOT_TOKEN or not config.MATTERMOST_TEAM_ID:
        raise MattermostError("Mattermost is not configured (MATTERMOST_URL / BOT_TOKEN / MATTERMOST_TEAM_ID missing).")
    return MattermostClient(
        base_url=config.MATTERMOST_URL,
        token=config.BOT_TOKEN,
        team_id=config.MATTERMOST_TEAM_ID,
    )


def find_channel_by_name(name: str) -> dict | None:
    """
    Looks up a channel matching `name`, trying two strategies:
    1. Direct lookup by URL-safe slug (`slugify(name)`) — the primary
       strategy, since Mattermost auto-derives a channel's slug from its
       display name (unless someone manually customized the "Channel
       handle" field), including on rename. `slugify()` mirrors Mattermost's
       own conversion rules (see clients/mattermost_client.py).
    2. Fallback: search by exact display name (`search_channels_for_team`,
       kept only for a display-name EXACT match). Needed for channels whose
       handle was manually customized away from the auto-derived slug, and
       for Mattermost deployments with "anonymous URLs" enabled (Mattermost
       11.6+), where the slug never reflects the name at all.
    """
    client = get_client()

    channel = client.get_channel_by_name(client.team_id, slugify(name))
    if channel:
        return channel

    candidates = client.search_channels_for_team(client.team_id, name)
    if candidates is None:
        # The slug lookup already came back empty, and the fallback search
        # itself failed — surface this as an error rather than silently
        # treating it as "not found".
        raise MattermostError(f"Failed to search Mattermost channels for '{name}'.")

    normalized_target = name.strip().lower()
    for candidate in candidates:
        if (candidate.get("display_name") or "").strip().lower() == normalized_target:
            return candidate

    return None


def search_channels(query: str) -> list[dict]:
    """Substring search for the "reattach this resource" UI (see
    backend/routers/api.py::search_resource_candidates). Unlike
    find_channel_by_name, searches on display name / free text, not an
    exact slug match."""
    client = get_client()
    results = client.search_channels_for_team(client.team_id, query)
    if results is None:
        raise MattermostError(f"Failed to search Mattermost channels for '{query}'.")
    return results


def list_members_with_role(channel_id: str) -> list[dict]:
    """Returns [{"id", "name", "email", "permission"}] fetched LIVE from Mattermost.
    `permission` mirrors the Outline service's shape: 'admin' if the member
    has the channel_admin role, 'member' otherwise, so the resource-users
    modal can render both tools the same way."""
    client = get_client()
    members = client.get_channel_members_with_roles(channel_id)
    if members is None:
        raise MattermostError(f"Failed to fetch members of Mattermost channel '{channel_id}'.")
    result = []
    for m in members:
        user = m["user"]
        roles = m.get("roles", "")
        permission = "admin" if "channel_admin" in roles else "member"
        result.append(
            {
                "id": user["id"],
                "name": user.get("nickname") or user.get("username", ""),
                "email": user.get("email"),
                "permission": permission,
            }
        )
    return result
