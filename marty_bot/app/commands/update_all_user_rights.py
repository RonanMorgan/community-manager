import asyncio
import logging

from .base_command import BaseCommand
from libraries.group_sync_services import orchestrate_group_synchronization


class UpdateAllUserRightsCommand(BaseCommand):
    @property
    def command_name(self):
        return "update_all_user_rights"

    async def check_user_right(self, user_id: str, channel_id: str) -> bool:
        if not await self.user_right_manager.is_admin(user_id):
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                ":no_entry_sign: Accès refusé. Cette commande nécessite les droits d'administrateur Mattermost.",
            )
            return False
        return True

    async def _execute(self, channel_id, arg_string, user_id_who_posted):
        """S'assure que les utilisateurs Mattermost ont les bons droits (ajouts/mises à jour uniquement). Nécessite les droits admin."""
        logging.info(
            f"'{self.bot.bot_name_mention} update_all_user_rights' (upsert) command received in channel {channel_id} by user {user_id_who_posted}."
        )

        initial_message_text = ":hourglass_flowing_sand: Démarrage de la mise à jour des droits utilisateurs (ajouts/modifications uniquement)... Ceci peut prendre un moment."
        initial_post_id = await asyncio.to_thread(self.bot.envoyer_message, channel_id, initial_message_text)

        if (
            not self.bot.authentik_client
            or not self.bot.mattermost_api_client
            or not self.bot.config.MATTERMOST_TEAM_ID
        ):
            error_msg = (
                ":warning: **Erreur :** Le bot n'est pas correctement configuré pour la mise à jour des droits. "
                "Client Authentik, client API Mattermost, ou ID d'équipe Mattermost manquant. "
                "Veuillez vérifier les logs du serveur."
            )
            logging.error(
                "Bot is not properly configured for rights update (upsert): Missing Authentik client, "
                "Mattermost API client, or Mattermost Team ID."
            )
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                error_msg,
                thread_id=initial_post_id,
            )
            return

        try:
            logging.info(
                "Calling 'orchestrate_group_synchronization' with sync_mode='TOOLS_TO_MM' for rights removal..."
            )
            clients = {
                "authentik": self.bot.authentik_client,
                "mattermost": self.bot.mattermost_api_client,
                "outline": self.bot.outline_client,
                "brevo": self.bot.brevo_client,
                "nocodb": self.bot.nocodb_client,
                "vaultwarden": self.bot.vaultwarden_client,
            }
            (
                orchestration_success,
                detailed_results,
            ) = await orchestrate_group_synchronization(
                clients=clients,
                mm_team_id=self.bot.config.MATTERMOST_TEAM_ID,
                sync_mode="MM_TO_TOOLS",
                skip_services=None,
            )

            if not orchestration_success:
                logging.warning(
                    "Group synchronization task (upsert mode) reported critical failure during orchestration."
                )
                summary_msg = (
                    ":x: La mise à jour des droits (upsert) a échoué de manière critique durant l'orchestration. "
                    "Veuillez consulter les logs du serveur pour plus de détails."
                )
                await asyncio.to_thread(
                    self.bot.envoyer_message,
                    channel_id,
                    summary_msg,
                    thread_id=initial_post_id,
                )
            else:
                logging.info(
                    f"Group synchronization task (upsert mode) orchestration completed. Detailed results count: {len(detailed_results)}"
                )
                await self.bot.result_manager.format_and_send_sync_results(
                    channel_id,
                    initial_post_id,
                    detailed_results,
                    command_name="Mise à jour (upsert)",
                )

        except Exception as e:
            logging.error(
                f"An unexpected error occurred while dispatching or running the upsert task: {e}",
                exc_info=True,
            )
            error_response_msg = ":boom: Une erreur serveur inattendue s'est produite lors de la tentative d'exécution de la mise à jour des droits (upsert). Veuillez consulter les logs du serveur."
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                error_response_msg,
                thread_id=initial_post_id,
            )

    @staticmethod
    def get_help():
        return "S'assure que les utilisateurs Mattermost ont les bons droits (ajouts/mises à jour uniquement). Nécessite les droits admin."
