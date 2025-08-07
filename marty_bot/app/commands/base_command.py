import asyncio
from abc import ABC, abstractmethod

from app.user_right_manager import UserRightManager


class BaseCommand(ABC):
    def __init__(self, bot):
        self.bot = bot
        self.user_right_manager = UserRightManager(bot)
        self.auth_context = {}

    @property
    @abstractmethod
    def command_name(self):
        pass

    @property
    def permission_level(self):
        return None

    async def check_user_right(self, user_id, channel_id):
        if self.permission_level == "admin":
            if await self.user_right_manager.is_admin(user_id):
                return True
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                ":no_entry_sign: Accès refusé. Cette commande nécessite les droits d'administrateur Mattermost.",
            )
            return False
        elif self.permission_level == "channel_admin":
            has_rights, entity_key, base_name = await self.user_right_manager.is_channel_admin(user_id, channel_id)
            if has_rights:
                self.auth_context["entity_key"] = entity_key
                self.auth_context["base_name"] = base_name
                return True
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                ":no_entry_sign: Accès refusé. Cette commande doit être lancée depuis un canal admin configuré et vous devez en être membre.",
            )
            return False
        return True

    @abstractmethod
    async def execute(self, channel_id, arg_string, user_id_who_posted):
        pass

    @staticmethod
    @abstractmethod
    def get_help():
        pass
