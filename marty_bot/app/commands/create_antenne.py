from libraries.resource_creation import execute_batch_create_command

from .base_command import BaseCommand


class CreateAntenneCommand(BaseCommand):
    @property
    def command_name(self):
        return "create_antenne"

    async def _execute(self, channel_id, arg_string, user_id_who_posted):
        clients = {
            "authentik": self.bot.authentik_client,
            "outline": self.bot.outline_client,
            "mattermost": self.bot.mattermost_api_client,
            "brevo": self.bot.brevo_client,
            "nocodb": self.bot.nocodb_client,
            "vaultwarden": self.bot.vaultwarden_client,
        }
        await execute_batch_create_command(
            channel_id,
            arg_string,
            "antenne",
            "ANTENNE",
            user_id_who_posted,
            self.bot.config,
            clients,
            self.bot,
        )

    @staticmethod
    def get_help():
        return (
            "Crée les ressources pour une ou plusieurs antennes. Usage: create_antenne <NomAntenne1> [NomAntenne2 ...]"
        )
