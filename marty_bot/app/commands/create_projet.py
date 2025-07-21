from .base_command import BaseCommand


class CreateProjetCommand(BaseCommand):
    async def execute(self, channel_id, arg_string, user_id_who_posted):
        await self.bot._execute_batch_create_command(
            channel_id, arg_string, "projet", "PROJET", user_id_who_posted
        )

    @staticmethod
    def get_help():
        return "Crée les ressources pour un ou plusieurs projets. Usage: create_projet <NomProjet1> [NomProjet2 ...]"
