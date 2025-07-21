from .base_command import BaseCommand


class SendEmailCommand(BaseCommand):
    async def execute(self, channel_id, arg_string, user_id_who_posted):
        await self.bot._handle_send_email_command(
            channel_id, arg_string, user_id_who_posted
        )

    @staticmethod
    def get_help():
        return "Envoie un email via Brevo aux membres du canal standard associé."
