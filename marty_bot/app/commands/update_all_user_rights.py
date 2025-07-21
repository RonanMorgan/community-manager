from .base_command import BaseCommand
import asyncio
import logging

class UpdateAllUserRightsCommand(BaseCommand):
    @property
    def command_name(self):
        return "update_all_user_rights"

    async def execute(self, channel_id, arg_string, user_id_who_posted):
        """S'assure que les utilisateurs Mattermost ont les bons droits (ajouts/mises à jour uniquement). Nécessite les droits admin."""
        logging.info(
            f"'{self.bot.bot_name_mention} update_all_user_rights' (upsert) command received in channel {channel_id} by user {user_id_who_posted}."
        )

        if not self.bot.mattermost_api_client or not user_id_who_posted:
            logging.error("Mattermost API client or user_id_who_posted not available for permission check.")
            await asyncio.to_thread(
                self.bot.envoyer_message, channel_id, ":x: Erreur interne : Impossible de vérifier les permissions."
            )
            return

        user_roles = await asyncio.to_thread(self.bot.mattermost_api_client.get_user_roles, user_id_who_posted)
        if "system_admin" not in user_roles:
            logging.warning(
                f"User {user_id_who_posted} (roles: {user_roles}) attempted to use 'update_all_user_rights' without admin rights."
            )
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                ":no_entry_sign: Accès refusé. Cette commande nécessite les droits d'administrateur Mattermost.",
            )
            return

        initial_message_text = ":hourglass_flowing_sand: Démarrage de la mise à jour des droits utilisateurs (ajouts/modifications uniquement)... Ceci peut prendre un moment."
        initial_post_id = await asyncio.to_thread(self.bot.envoyer_message, channel_id, initial_message_text)

        if not self.bot.authentik_client or not self.bot.mattermost_api_client or not self.bot.config.MATTERMOST_TEAM_ID:
            error_msg = (
                ":warning: **Erreur :** Le bot n'est pas correctement configuré pour la mise à jour des droits. "
                "Client Authentik, client API Mattermost, ou ID d'équipe Mattermost manquant. "
                "Veuillez vérifier les logs du serveur."
            )
            logging.error(
                "Bot is not properly configured for rights update (upsert): Missing Authentik client, "
                "Mattermost API client, or Mattermost Team ID."
            )
            await asyncio.to_thread(self.bot.envoyer_message, channel_id, error_msg, thread_id=initial_post_id)
            return

        if not self.bot.outline_client:
            logging.info("Outline client not configured. Outline operations will be skipped for update_user_rights.")

        try:
            logging.info(
                "Calling 'orchestrate_group_synchronization' with sync_mode='TOOLS_TO_MM' for rights removal..."
            )
            orchestration_success, detailed_results = await self.bot.orchestrate_group_synchronization(
                authentik_client=self.bot.authentik_client,
                mattermost_client=self.bot.mattermost_api_client,
                outline_client=self.bot.outline_client,
                brevo_client=self.bot.brevo_client,
                nocodb_client=self.bot.nocodb_client,
                vaultwarden_client=self.bot.vaultwarden_client,
                mm_team_id=self.bot.config.MATTERMOST_TEAM_ID,
                perform_deletions=False,  # MM_TO_TOOLS with perform_deletions=False is upsert
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
                await asyncio.to_thread(self.bot.envoyer_message, channel_id, summary_msg, thread_id=initial_post_id)
            else:
                logging.info(
                    f"Group synchronization task (upsert mode) orchestration completed. Detailed results count: {len(detailed_results)}"
                )
                await self.bot._format_and_send_sync_results(
                    channel_id, initial_post_id, detailed_results, command_name="Mise à jour (upsert)"
                )

        except Exception as e:
            logging.error(
                f"An unexpected error occurred while dispatching or running the upsert task: {e}", exc_info=True
            )
            error_response_msg = ":boom: Une erreur serveur inattendue s'est produite lors de la tentative d'exécution de la mise à jour des droits (upsert). Veuillez consulter les logs du serveur."
            await asyncio.to_thread(self.bot.envoyer_message, channel_id, error_response_msg, thread_id=initial_post_id)

    @staticmethod
    def get_help():
        return "S'assure que les utilisateurs Mattermost ont les bons droits (ajouts/mises à jour uniquement). Nécessite les droits admin."
