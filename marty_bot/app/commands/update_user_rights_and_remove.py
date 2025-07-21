from .base_command import BaseCommand


class UpdateUserRightsAndRemoveCommand(BaseCommand):
    async def execute(self, channel_id, arg_string, user_id_who_posted):
        await self.bot._handle_update_user_rights_and_remove_command(
            channel_id, arg_string, user_id_who_posted
        )

    @staticmethod
    def get_help():
        return "Synchronise les droits (ajouts/mises à jour) ET supprime les accès obsolètes. Nécessite les droits admin."
