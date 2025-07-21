import os
import importlib
import inspect
from .base_command import BaseCommand


class CommandFactory:
    def __init__(self, bot):
        self.bot = bot
        self.commands = self._load_commands()

    def _load_commands(self):
        commands = {}
        commands_dir = os.path.dirname(__file__)
        for filename in os.listdir(commands_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                module_name = f"app.commands.{filename[:-3]}"
                module = importlib.import_module(module_name)
                for name, cls in inspect.getmembers(module, inspect.isclass):
                    if issubclass(cls, BaseCommand) and cls is not BaseCommand:
                        command_name = self._get_command_name(filename)
                        if command_name == "help":
                            commands[command_name] = cls(self.bot, self)
                        else:
                            commands[command_name] = cls(self.bot)
        return commands

    def _get_command_name(self, filename):
        return filename[:-3]

    def get_command(self, command_name):
        return self.commands.get(command_name)
