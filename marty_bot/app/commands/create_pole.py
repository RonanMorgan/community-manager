from .base_command import BaseCommand


class CreatePoleCommand(BaseCommand):
    @property
    def command_name(self):
        return "create_pole"

    async def execute(self, channel_id, arg_string, user_id_who_posted):
        await self.bot._execute_batch_create_command(
            channel_id, arg_string, "pôle", "POLES", user_id_who_posted
        )

    @staticmethod
    def get_help():
        return "Crée les ressources pour un ou plusieurs pôles. Usage: create_pole <NomPole1> [NomPole2 ...]"
