import asyncio
import logging

from .base_command import BaseCommand
from libraries.group_sync_services import differential_sync


class UpdateUserRightsAndRemoveCommand(BaseCommand):
    @property
    def command_name(self):
        return "update_user_rights_and_remove"

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
        """Synchronise les droits (ajouts/mises à jour) ET supprime les accès obsolètes. Nécessite les droits admin."""
        logging.info(
            f"'{self.bot.bot_name_mention} update_user_rights_and_remove' command received in channel {channel_id} by user {user_id_who_posted} with args: '{arg_string}'."
        )

        skip_services_list = []
        if arg_string and arg_string.lower() == "nocodb=false":
            skip_services_list.append("nocodb")
            logging.info("NoCoDB synchronization will be skipped for this run based on 'nocodb=false' argument.")
            initial_message_text = (
                ":hourglass_flowing_sand: Démarrage de la synchronisation complète des droits (avec suppressions, NoCoDB ignoré)... "
                "Ceci inclut la synchronisation des groupes Authentik et des collections Outline. "
                "Cela peut prendre un moment."
            )
        else:
            if arg_string:  # Log if there was an argument but it wasn't the recognized one
                logging.info(
                    f"Argument '{arg_string}' not recognized as 'nocodb=false', proceeding with full sync including NoCoDB."
                )
            initial_message_text = (
                ":hourglass_flowing_sand: Démarrage de la synchronisation complète des droits (avec suppressions)... "
                "Ceci inclut la synchronisation des groupes Authentik et des collections Outline. "
                "Cela peut prendre un moment."
            )
        initial_post_id = await asyncio.to_thread(self.bot.envoyer_message, channel_id, initial_message_text)

        if (
            not self.bot.authentik_client
            or not self.bot.mattermost_api_client
            or not self.bot.config.MATTERMOST_TEAM_ID
        ):
            error_msg = (
                ":warning: **Erreur :** Le bot n'est pas correctement configuré pour cette opération. "
                "Client Authentik, client API Mattermost, ou ID d'équipe Mattermost manquant. "
                "Veuillez vérifier les logs du serveur."
            )
            logging.error(
                "Bot is not properly configured for rights removal (core components): Missing Authentik client, "
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
            logging.info("Calling 'differential_sync' for upsert...")  # Corrected log message for upsert

            (
                orchestration_success,
                detailed_results,
            ) = await differential_sync(
                clients=self.bot._get_clients(),
                mm_team_id=self.bot.config.MATTERMOST_TEAM_ID,
                skip_services=skip_services_list if skip_services_list else None,
            )

            if not orchestration_success:
                logging.warning(
                    "Group synchronization task (for rights removal) reported critical failure during orchestration."
                )
                summary_msg = (
                    ":x: La suppression/synchronisation des droits a échoué de manière critique durant l'orchestration. "
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
                    f"Group synchronization task (for rights removal) orchestration completed. Detailed results count: {len(detailed_results)}"
                )
                await self.bot.result_manager.format_and_send_sync_results(
                    channel_id,
                    initial_post_id,
                    detailed_results,
                    command_name="Suppression/synchronisation",
                )

        except Exception as e:
            logging.error(
                f"An unexpected error occurred while dispatching or running the rights removal task: {e}",
                exc_info=True,
            )
            error_response_msg = (
                ":boom: Une erreur serveur inattendue s'est produite lors de la tentative "
                "d'exécution de la suppression/synchronisation des droits. Veuillez consulter les logs du serveur."
            )
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                error_response_msg,
                thread_id=initial_post_id,
            )

    @staticmethod
    def get_help():
        return (
            "Synchronise les droits (ajouts/mises à jour) ET supprime les accès obsolètes. Nécessite les droits admin."
        )
