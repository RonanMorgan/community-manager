from abc import ABC, abstractmethod


class BaseCommand(ABC):
    def __init__(self, bot):
        self.bot = bot

    @property
    def user_right_manager(self):
        return self.bot.user_right_manager

    @property
    @abstractmethod
    def command_name(self):
        pass

    async def check_user_right(self, user_id: str, channel_id: str) -> bool:
        return True

    @abstractmethod
    async def _execute(self, channel_id, arg_string, user_id_who_posted):
        pass

    async def execute(self, channel_id, arg_string, user_id_who_posted):
        if await self.check_user_right(user_id_who_posted, channel_id):
            await self._execute(channel_id, arg_string, user_id_who_posted)

    @staticmethod
    @abstractmethod
    def get_help():
        pass
