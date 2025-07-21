from .base_command import BaseCommand


class UpdateAllUserRightsCommand(BaseCommand):
    async def execute(self, channel_id, arg_string, user_id_who_posted):
        await self.bot._handle_update_all_user_rights_command(
            channel_id, arg_string, user_id_who_posted
        )

    @staticmethod
    def get_help():
        return "S'assure que les utilisateurs Mattermost ont les bons droits (ajouts/mises à jour uniquement). Nécessite les droits admin."
