import importlib
import inspect
import os

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
                        # Instantiate the command to get its name
                        instance = cls(self.bot)
                        command_name = instance.command_name
                        if command_name:
                            commands[command_name] = instance
        return commands

    def get_command(self, command_name):
        return self.commands.get(command_name)
