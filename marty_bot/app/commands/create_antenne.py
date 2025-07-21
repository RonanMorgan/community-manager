from .base_command import BaseCommand


class CreateAntenneCommand(BaseCommand):
    async def execute(self, channel_id, arg_string, user_id_who_posted):
        await self.bot._execute_batch_create_command(
            channel_id, arg_string, "antenne", "ANTENNE", user_id_who_posted
        )

    @staticmethod
    def get_help():
        return "Crée les ressources pour une ou plusieurs antennes. Usage: create_antenne <NomAntenne1> [NomAntenne2 ...]"
