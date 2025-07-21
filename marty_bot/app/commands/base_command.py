from abc import ABC, abstractmethod


class BaseCommand(ABC):
    def __init__(self, bot):
        self.bot = bot

    @property
    @abstractmethod
    def command_name(self):
        pass

    @abstractmethod
    async def execute(self, channel_id, arg_string, user_id_who_posted):
        pass

    @staticmethod
    @abstractmethod
    def get_help():
        pass
