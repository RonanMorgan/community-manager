from .base_command import BaseCommand
import asyncio


class HelpCommand(BaseCommand):
    def __init__(self, bot, command_factory):
        super().__init__(bot)
        self.command_factory = command_factory

    async def execute(self, channel_id, arg_string, user_id_who_posted):
        await self.bot._send_help_message(channel_id, arg_string)

    @staticmethod
    def get_help():
        return "Displays this help message listing all available commands."
