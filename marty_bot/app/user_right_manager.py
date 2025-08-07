import asyncio
import logging

from libraries.group_sync_services import (
    _map_mm_channel_to_entity_and_base_name,
    slugify,
)


class UserRightManager:
    def __init__(self, bot):
        self.bot = bot

    async def is_admin(self, user_id):
        mattermost_api_client = self.bot.mattermost_api_client
        if not mattermost_api_client or not user_id:
            logging.error("is_admin check failed: Mattermost API client or user_id not available.")
            return False

        user_roles = await asyncio.to_thread(mattermost_api_client.get_user_roles, user_id)
        if "system_admin" in user_roles:
            return True

        logging.warning(f"User {user_id} (roles: {user_roles}) is not a system admin.")
        return False

    async def is_channel_admin(self, user_id, channel_id):
        mattermost_api_client = self.bot.mattermost_api_client
        config = self.bot.config

        if not mattermost_api_client or not user_id or not channel_id:
            logging.error("is_channel_admin check failed: Mattermost API client, user_id, or channel_id not available.")
            return False, None, None

        current_channel_info = await asyncio.to_thread(mattermost_api_client.get_channel_by_id, channel_id)
        if not current_channel_info:
            logging.warning(f"Could not retrieve info for channel {channel_id}.")
            return False, None, None

        channel_members = await asyncio.to_thread(mattermost_api_client.get_users_in_channel, channel_id)
        if not any(member.get("id") == user_id for member in channel_members):
            logging.warning(f"User {user_id} is not a member of channel {channel_id}.")
            return False, None, None

        admin_channel_name_slug = current_channel_info.get("name")
        admin_channel_display_name = current_channel_info.get("display_name")

        entity_key, base_name, channel_type = _map_mm_channel_to_entity_and_base_name(
            admin_channel_name_slug,
            admin_channel_display_name,
            config.PERMISSIONS_MATRIX,
        )

        if entity_key and base_name and channel_type == "admin":
            logging.info(f"Channel {channel_id} is a valid admin channel for entity {base_name}.")
            return True, entity_key, base_name

        logging.warning(f"Channel {channel_id} is not a recognized admin channel.")
        return False, None, None
