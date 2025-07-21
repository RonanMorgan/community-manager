import logging
from typing import TYPE_CHECKING
import re

if TYPE_CHECKING:
    from clients.mattermost_client import MattermostClient


def slugify(text: str) -> str:
    """
    Simple slugify function:
    - Convert to lowercase
    - Replace spaces and underscores with hyphens
    - Remove characters that are not alphanumeric or hyphens
    - Ensure it doesn't start or end with a hyphen
    - Truncate to 64 characters (Mattermost limit for channel name)
    - Return a default name if the slug becomes empty
    """
    text = str(text).lower()
    # Replace spaces and underscores with hyphens first
    text = re.sub(r"[\s_]+", "-", text)
    # Replace any sequence of non-alphanumeric characters (excluding existing hyphens) with a single hyphen
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    # Remove leading or trailing hyphens that might have been created
    text = text.strip("-")
    # Consolidate multiple hyphens (e.g., "foo---bar" to "foo-bar").
    text = re.sub(r"-+", "-", text)

    if len(text) > 64:
        text = text[:64].strip("-")  # Re-strip if truncation creates leading/trailing hyphen

    if not text or text == "-":  # Handle if slug becomes empty or just a hyphen
        return "default-slug-name"  # Changed default from 'default-channel-name' to be more generic
    return text


def _get_mm_users_for_entity(
    mattermost_client: "MattermostClient",
    mm_team_id: str,
    base_name: str,
    entity_config: dict,
) -> tuple[dict, list, list]:  # Returns mm_users_for_services, std_mm_users, adm_mm_users
    """
    Fetches Mattermost users for a given entity, from both standard and admin channels.
    Returns a consolidated dictionary of users with their admin status, and separate lists for std/admin channel users.
    """
    std_config = entity_config.get("standard", {})
    admin_config = entity_config.get("admin")

    std_mm_channel_name = std_config.get("mattermost_channel_name_pattern", "{base_name}").format(base_name=base_name)
    std_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(std_mm_channel_name))
    std_mm_users_in_channel = []
    if std_mm_channel:
        std_mm_users_in_channel = mattermost_client.get_users_in_channel(std_mm_channel["id"])
    else:
        logging.warning(f"Mattermost channel '{std_mm_channel_name}' for entity '{base_name}' not found.")

    adm_mm_users_in_channel = []
    if admin_config:
        adm_mm_channel_name = admin_config.get("mattermost_channel_name_pattern", "{base_name} Admin").format(
            base_name=base_name
        )
        adm_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(adm_mm_channel_name))
        if adm_mm_channel:
            adm_mm_users_in_channel = mattermost_client.get_users_in_channel(adm_mm_channel["id"])
        else:
            logging.warning(f"Mattermost admin channel '{adm_mm_channel_name}' for entity '{base_name}' not found.")

    mm_users_for_services = {}
    for mm_user in std_mm_users_in_channel:
        email = mm_user.get("email", "").lower()
        if email:
            mm_users_for_services[email] = {
                "username": mm_user.get("username"),
                "mm_user_id": mm_user.get("id"),
                "is_admin_channel_member": False,
            }

    if admin_config:
        for mm_user in adm_mm_users_in_channel:
            email = mm_user.get("email", "").lower()
            if email:
                existing_data = mm_users_for_services.get(email, {})
                mm_users_for_services[email] = {
                    "username": mm_user.get("username", existing_data.get("username")),
                    "mm_user_id": mm_user.get("id", existing_data.get("mm_user_id")),
                    "is_admin_channel_member": True,
                }

    return mm_users_for_services, std_mm_users_in_channel, adm_mm_users_in_channel
