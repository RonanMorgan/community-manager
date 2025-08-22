import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.bot import MartyBot


class UserRightManager:
    def __init__(self, bot: "MartyBot"):
        self.bot = bot

    async def is_admin(self, user_id: str) -> bool:
        if not self.bot.mattermost_api_client or not user_id:
            logging.error("Mattermost API client or user_id not available for permission check.")
            return False
        user_roles = await asyncio.to_thread(self.bot.mattermost_api_client.get_user_roles, user_id)
        return "system_admin" in user_roles

    async def is_channel_admin(self, user_id: str, channel_id: str) -> bool:
        current_channel_info = await asyncio.to_thread(self.bot.mattermost_api_client.get_channel_by_id, channel_id)
        if not current_channel_info:
            return False

        channel_members = await asyncio.to_thread(self.bot.mattermost_api_client.get_users_in_channel, channel_id)
        if not any(member.get("id") == user_id for member in channel_members):
            return False

        admin_channel_name_slug = current_channel_info.get("name")
        from libraries.group_sync_services import (
            _map_mm_channel_to_entity_and_base_name,
            slugify,
        )

        for e_key, e_conf in self.bot.config.PERMISSIONS_MATRIX.items():
            admin_cfg = e_conf.get("admin")
            if admin_cfg:
                admin_pattern = admin_cfg.get("mattermost_channel_name_pattern")
                if admin_pattern:
                    temp_entity_key, temp_base_name, _ = _map_mm_channel_to_entity_and_base_name(
                        admin_channel_name_slug,
                        current_channel_info.get("display_name"),
                        {e_key: e_conf},
                    )
                    if temp_entity_key == e_key and temp_base_name:
                        expected_admin_channel_slug = slugify(admin_pattern.format(base_name=temp_base_name))
                        if admin_channel_name_slug == expected_admin_channel_slug:
                            return True
        return False
