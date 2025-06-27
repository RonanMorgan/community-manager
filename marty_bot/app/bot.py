import websockets
import json
import re  # Import re for regular expressions

# import threading # No longer used
import requests

# import os # No longer used
import asyncio
import logging

# import signal  # No longer used directly in MartyBot class after removing signal handlers
import threading  # For logging current thread name in start()

from app import config

# Configure basic logging based on DEBUG status
# This initial basicConfig is for any logging before MartyBot instance is created
# or if MartyBot's specific config isn't applied globally.
# MartyBot's __init__ will refine this for its instance.
if config.DEBUG:
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    )
    logging.debug("Initial DEBUG mode is enabled. Global verbose logging active.")
else:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# Import client classes
from clients.authentik_client import AuthentikClient
from clients.outline_client import OutlineClient
from clients.mattermost_client import MattermostClient

# Import orchestration function for sync command
from libraries.group_sync_services import orchestrate_group_synchronization


class MartyBot:
    def __init__(self, config_obj):
        self.config = config_obj

        # Ensure logging is configured based on the instance's config for future logs from this instance
        # This will apply to loggers obtained after this point if they inherit from root.
        log_format = "%(asctime)s - %(levelname)s - %(message)s"
        log_level = logging.INFO
        if self.config.DEBUG:
            log_level = logging.DEBUG
            log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"

        # Get root logger and set its level. Remove existing handlers before adding new one.
        # This is to avoid duplicate log messages if basicConfig was called before.
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:  # Iterate over a copy
            root_logger.removeHandler(handler)
        logging.basicConfig(level=log_level, format=log_format)  # Re-apply basicConfig with new settings

        if self.config.DEBUG:
            logging.debug("DEBUG mode is enabled for MartyBot instance. Verbose logging active.")

        self.bot_name_mention = f"@{self.config.BOT_NAME.lower()}" if self.config.BOT_NAME else ""

        # Initialize API Clients
        self.authentik_client = None
        if self.config.AUTHENTIK_URL and self.config.AUTHENTIK_TOKEN:
            try:
                self.authentik_client = AuthentikClient(self.config.AUTHENTIK_URL, self.config.AUTHENTIK_TOKEN)
                logging.info("AuthentikClient initialized successfully for MartyBot instance.")
            except ValueError as e:
                logging.warning(f"Failed to initialize AuthentikClient for MartyBot instance: {e}")
        else:
            logging.warning(
                "Authentik URL or Token not configured for MartyBot instance. Authentik features will be disabled."
            )

        self.outline_client = None
        if self.config.OUTLINE_URL and self.config.OUTLINE_TOKEN:
            try:
                self.outline_client = OutlineClient(self.config.OUTLINE_URL, self.config.OUTLINE_TOKEN)
                logging.info("OutlineClient initialized successfully for MartyBot instance.")
            except ValueError as e:
                logging.warning(f"Failed to initialize OutlineClient for MartyBot instance: {e}")
        else:
            logging.warning(
                "Outline URL or Token not configured for MartyBot instance. Outline features will be disabled."
            )

        self.mattermost_api_client = None
        if self.config.MATTERMOST_URL and self.config.BOT_TOKEN and self.config.MATTERMOST_TEAM_ID:
            try:
                self.mattermost_api_client = MattermostClient(
                    self.config.MATTERMOST_URL, self.config.BOT_TOKEN, self.config.MATTERMOST_TEAM_ID
                )
                logging.info(
                    "MattermostClient (for API operations using BOT_TOKEN) initialized successfully for MartyBot instance."
                )
            except ValueError as e:
                logging.warning(f"Failed to initialize MattermostClient (API) for MartyBot instance: {e}")
        else:
            logging.warning(
                "Mattermost URL, Bot Token, or Team ID not fully configured for MattermostClient instance. Mattermost API operations may fail or be disabled."
            )

        self.websocket = None  # Represents the active WebSocket connection object

        # For graceful shutdown
        self.shutdown_event = asyncio.Event()

        # Reconnection parameters
        self.MAX_RECONNECT_ATTEMPTS = 5
        self.INITIAL_RECONNECT_DELAY = 5  # seconds
        self.MAX_RECONNECT_DELAY = 60  # seconds

        self.commands = {
            "create_projet": self._handle_create_projet_command,
            "create_antenne": self._handle_create_antenne_command,
            "create_pole": self._handle_create_pole_command,
            "help": self._send_help_message,
            "sync_user_channels": self._handle_sync_user_channels_command,  # Maintenir l'ancienne commande pour l'instant
            "update_user_rights": self._handle_update_user_rights_command,  # Nouvelle commande
        }

    async def _format_and_send_sync_results(
        self, channel_id: str, initial_post_id: str | None, detailed_results: list[dict]
    ):
        """Helper function to format and send detailed synchronization results."""
        if not detailed_results:
            final_summary_message = ":information_source: Processus de synchronisation terminé, mais aucune opération utilisateur spécifique n'a été effectuée ou rapportée."
            await asyncio.to_thread(self.envoyer_message, channel_id, final_summary_message, thread_id=initial_post_id)
            return

        total_success_ops = 0
        total_problem_ops = 0
        action_summary = {}  # Pour compter les types d'actions

        for result in detailed_results:
            user_mm_name = result.get("mm_username", "Utilisateur inconnu")
            service_name = result.get("service", "ServiceInconnu").upper()
            target_resource = result.get("target_resource_name", "RessourceInconnue")
            action = result.get("action", "AUCUNE_ACTION")
            status = result.get("status", "ECHEC")
            error_msg = result.get("error_message")

            action_summary[action] = action_summary.get(action, 0) + 1

            icon = ":white_check_mark:" if status == "SUCCESS" else ":x:"
            if (
                status == "SKIPPED" and action != "SKIPPED_NO_MM_EMAIL"
            ):  # SKIPPED_NO_MM_EMAIL n'est pas un problème en soi
                icon = ":warning:"

            user_line = f"{icon} **Utilisateur :** `{user_mm_name}`"
            if result.get("mm_user_email") and result.get("mm_user_email") != "NoEmailProvided":
                user_line += f" ({result.get('mm_user_email')})"

            service_line = f"**Service :** `{service_name}`"
            resource_line = f"**Ressource :** `{target_resource}`"
            action_line = f"**Action :** `{action}`"
            message_parts = [user_line, service_line, resource_line, action_line]

            if status == "SUCCESS":
                total_success_ops += 1
                # Descriptions spécifiques par action
                if action == "USER_ADDED_TO_AUTHENTIK_GROUP":
                    message_parts.append("Ajouté avec succès au groupe Authentik.")
                elif action == "USER_ALREADY_IN_AUTHENTIK_GROUP":
                    message_parts.append("Déjà membre du groupe Authentik.")
                elif action == "USER_REMOVED_FROM_AUTHENTIK_GROUP":
                    message_parts.append("Supprimé avec succès du groupe Authentik.")
                elif action.startswith("USER_ADDED_TO_OUTLINE_COLLECTION_WITH_") and action.endswith("_AND_DM_SENT"):
                    permission = action.split("_WITH_")[1].split("_ACCESS")[0]
                    message_parts.append(
                        f"Ajouté à la collection Outline (permission {permission.lower()}) et MP envoyé."
                    )
                elif action.startswith("USER_ADDED_TO_OUTLINE_COLLECTION_WITH_") and action.endswith("_DM_FAILED"):
                    permission = action.split("_WITH_")[1].split("_ACCESS")[0]
                    message_parts.append(
                        f"Ajouté à la collection Outline (permission {permission.lower()}), mais échec de l'envoi du MP."
                    )
                elif action.startswith("USER_ADDED_TO_OUTLINE_COLLECTION_WITH_"):  # No DM part
                    permission = action.split("_WITH_")[1].split("_ACCESS")[0]
                    message_parts.append(f"Ajouté à la collection Outline (permission {permission.lower()}).")
                elif action == "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED":
                    message_parts.append("Déjà membre de la collection Outline, permission assurée.")
                elif action == "USER_REMOVED_FROM_OUTLINE_COLLECTION":
                    message_parts.append("Supprimé avec succès de la collection Outline.")
                # ... autres actions SUCCESS ...
            elif status == "SKIPPED":
                message_parts.append(f"Ignoré. Raison : {error_msg if error_msg else 'Non spécifiée'}")
                if action != "SKIPPED_NO_MM_EMAIL":  # Ne pas compter comme un problème si juste pas d'email
                    total_problem_ops += 1
            else:  # FAILURE
                total_problem_ops += 1
                message_parts.append(f"ÉCHEC. Raison : {error_msg if error_msg else 'Non spécifiée'}")

            full_user_report_message = "\n".join(message_parts)
            await asyncio.to_thread(
                self.envoyer_message, channel_id, full_user_report_message, thread_id=initial_post_id
            )

        # Construction du message de résumé final
        summary_lines = ["### :checkered_flag: Résumé de la synchronisation des droits :"]
        summary_lines.append(f"- Opérations réussies : {total_success_ops}")
        if total_problem_ops > 0:
            summary_lines.append(f"- Problèmes/omissions : {total_problem_ops}")

        summary_lines.append("\n**Détail des actions :**")
        for act, count in sorted(action_summary.items()):
            summary_lines.append(f"- `{act}` : {count} fois")

        if total_problem_ops > 0 and total_success_ops > 0:
            summary_lines.insert(1, ":warning: Synchronisation partiellement terminée.")
        elif total_problem_ops > 0:
            summary_lines.insert(1, ":x: Synchronisation terminée avec des problèmes/omissions.")
        elif total_success_ops > 0:
            summary_lines.insert(1, ":rocket: Synchronisation terminée avec succès.")
        else:  # No ops or only skips like NO_MM_EMAIL
            summary_lines.insert(
                1, ":information_source: Synchronisation terminée. Peu ou pas d'opérations significatives effectuées."
            )

        final_summary_message = "\n".join(summary_lines)
        if final_summary_message:
            await asyncio.to_thread(self.envoyer_message, channel_id, final_summary_message, thread_id=initial_post_id)

    async def _handle_update_user_rights_command(self, channel_id, arg_string=None):
        """Met à jour tous les droits utilisateurs et supprime les accès obsolètes."""
        logging.info(f"'{self.bot_name_mention} update_user_rights' command received in channel {channel_id}.")

        initial_message_text = (
            ":hourglass_flowing_sand: Démarrage de la mise à jour des droits utilisateurs... "
            "Ceci inclut la synchronisation des groupes Authentik et des collections Outline, "
            "ainsi que la suppression des accès obsolètes. Cela peut prendre un moment."
        )
        initial_post_id = await asyncio.to_thread(self.envoyer_message, channel_id, initial_message_text)

        if not self.authentik_client or not self.mattermost_api_client or not self.config.MATTERMOST_TEAM_ID:
            error_msg = (
                ":warning: **Erreur :** Le bot n'est pas correctement configuré pour la synchronisation. "
                "Client Authentik, client API Mattermost, ou ID d'équipe Mattermost manquant. "
                "Veuillez vérifier les logs du serveur."
            )
            logging.error(
                "Bot is not properly configured for rights update (core components): Missing Authentik client, "
                "Mattermost API client, or Mattermost Team ID."
            )
            await asyncio.to_thread(self.envoyer_message, channel_id, error_msg, thread_id=initial_post_id)
            return

        if not self.outline_client:
            logging.info(
                "Outline client not configured on this bot instance. Outline synchronization will be skipped."
            )

        try:
            logging.info("Dispatching group synchronization task (for rights update) to a thread...")
            # On réutilise orchestrate_group_synchronization car elle fait maintenant la synchro complète
            orchestration_success, detailed_results = await asyncio.to_thread(
                orchestrate_group_synchronization,
                self.authentik_client,
                self.mattermost_api_client,
                self.outline_client,  # Peut être None, géré par l'orchestrateur
                self.config.MATTERMOST_TEAM_ID,
            )

            if not orchestration_success:  # Erreur critique dans l'orchestrateur lui-même
                logging.warning(
                    "Group synchronization task (for rights update) reported critical failure during orchestration."
                )
                summary_msg = (
                    ":x: La mise à jour des droits a échoué de manière critique durant l'orchestration. "
                    "Veuillez consulter les logs du serveur pour plus de détails."
                )
                await asyncio.to_thread(self.envoyer_message, channel_id, summary_msg, thread_id=initial_post_id)
            else:
                logging.info(
                    f"Group synchronization task (for rights update) orchestration completed. Detailed results count: {len(detailed_results)}"
                )
                await self._format_and_send_sync_results(channel_id, initial_post_id, detailed_results)

        except Exception as e:
            logging.error(
                f"An unexpected error occurred while dispatching or running the rights update task: {e}", exc_info=True
            )
            error_response_msg = (
                ":boom: Une erreur serveur inattendue s'est produite lors de la tentative "
                "d'exécution de la mise à jour des droits. Veuillez consulter les logs du serveur."
            )
            await asyncio.to_thread(self.envoyer_message, channel_id, error_response_msg, thread_id=initial_post_id)

    async def _create_resources_for_category(
        self,
        base_name: str,
        category_key: str,
        admin_category_key: str | None,
        # channel_id: str, # No longer used for sending message here
        item_type_display: str,
        requesting_user_id: str | None,  # Added user_id
    ):
        """
        Helper function to create resources based on permission matrix categories.
        It creates resources for a primary category and optionally for an admin category for a single base_name.
        Returns a list of log messages for this specific base_name.
        """
        item_results_log = []

        # Determine the prefix string based on the primary category_key
        prefix_str = ""
        if category_key == "PROJET":
            prefix_str = "projet_"
        elif category_key == "ANTENNE":
            prefix_str = "antenne_"
        elif category_key == "POLES":
            prefix_str = "pole_"

        prefixed_base_name = f"{prefix_str}{base_name}"

        categories_to_process = [(category_key, prefixed_base_name)]
        if admin_category_key:
            admin_resource_name = f"{prefixed_base_name} Admin"
            categories_to_process.append((admin_category_key, admin_resource_name))

        item_results_log.append(
            f"--- Création pour {item_type_display} **`{base_name}`** (préfixé en `{prefix_str}`) ---"
        )

        # Loop variable 'name_for_creation' now holds the correctly prefixed name
        for current_category_key, name_for_creation in categories_to_process:
            category_permissions = self.config.PERMISSIONS_MATRIX.get(current_category_key)

            if not category_permissions:
                msg = f":x: Configuration error: No permissions found for category '{current_category_key}' in the matrix for '{name_for_creation}'."
                logging.error(msg)
                item_results_log.append(msg)
                continue

            item_results_log.append(
                f"  - Sous-groupe/canal **`{name_for_creation}`** (basé sur *{current_category_key}*):"
            )

            auth_msg = "    - Authentik: "
            if self.authentik_client:
                try:
                    if self.authentik_client.create_group(name_for_creation):
                        auth_msg += ":white_check_mark: Groupe créé."
                    else:
                        auth_msg += ":warning: Échec création (ou groupe existe déjà)."
                except Exception as e:
                    logging.error(
                        f"Error creating Authentik group for {name_for_creation} ({current_category_key}): {e}",
                        exc_info=True,
                    )
                    auth_msg += f":x: Erreur interne ({e})."
            else:
                auth_msg += ":information_source: Client non configuré."
            item_results_log.append(auth_msg)

            outline_msg = "    - Outline: "
            if self.outline_client:
                try:
                    status = self.outline_client.create_group(name_for_creation)
                    if status == "CREATED":
                        outline_msg += ":white_check_mark: Collection créée."
                    elif status == "EXISTS":
                        outline_msg += ":information_source: Collection existait déjà."
                    else:  # FAILED
                        outline_msg += ":warning: Échec création/vérification."
                except Exception as e:
                    logging.error(
                        f"Error creating Outline collection for {name_for_creation} ({current_category_key}): {e}",
                        exc_info=True,
                    )
                    outline_msg += f":x: Erreur interne ({e})."
            else:
                outline_msg += ":information_source: Client non configuré."
            item_results_log.append(outline_msg)

            mm_settings = category_permissions.get("mattermost", {})
            mm_channel_type = mm_settings.get("channel_type", "O")
            mm_msg = "    - Mattermost: "
            if self.mattermost_api_client:
                created_mm_channel_id = None
                try:
                    channel_creation_result = self.mattermost_api_client.create_channel(
                        name_for_creation, channel_type=mm_channel_type
                    )
                    if (
                        channel_creation_result
                        and isinstance(channel_creation_result, dict)
                        and channel_creation_result.get("id")
                    ):
                        created_mm_channel_id = channel_creation_result["id"]
                        mm_msg += f":white_check_mark: Canal ({'Public' if mm_channel_type == 'O' else 'Privé'}) créé (ID: {created_mm_channel_id})."
                        if requesting_user_id and created_mm_channel_id:
                            logging.info(
                                f"Attempting to add user {requesting_user_id} to new channel {created_mm_channel_id} ({name_for_creation})"
                            )
                            if self.mattermost_api_client.add_user_to_channel(
                                created_mm_channel_id, requesting_user_id
                            ):
                                mm_msg += " Utilisateur demandeur ajouté au canal."
                                logging.info(
                                    f"Successfully added user {requesting_user_id} to channel {created_mm_channel_id} ({name_for_creation})"
                                )
                            else:
                                mm_msg += " Échec de l'ajout de l'utilisateur demandeur au canal."
                                logging.warning(
                                    f"Failed to add user {requesting_user_id} to channel {created_mm_channel_id} ({name_for_creation})"
                                )
                    else:
                        mm_msg += f":warning: Échec création ({'Public' if mm_channel_type == 'O' else 'Privé'}) (ou existe déjà)."
                except Exception as e:
                    logging.error(
                        f"Error creating Mattermost channel for {name_for_creation} ({current_category_key}): {e}",
                        exc_info=True,
                    )
                    mm_msg += f":x: Erreur interne ({e})."
            else:
                mm_msg += ":information_source: Client non configuré."
            item_results_log.append(mm_msg)

        return item_results_log

    async def _execute_batch_create_command(
        self,
        channel_id: str,
        arg_string: str | None,
        item_type_display: str,
        category_key: str,
        admin_category_key: str | None,
        command_name: str,
        requesting_user_id: str | None,  # Added user_id
    ):
        """Generic handler for create commands supporting multiple arguments."""
        if not arg_string:
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                f":warning: Au moins un nom de {item_type_display} est requis. Usage: `{self.bot_name_mention} {command_name} <Nom1> [Nom2 ...]`",  # noqa: E501
            )
            return

        base_names = arg_string.split()
        num_items = len(base_names)
        plural_s = "s" if num_items > 1 else ""

        initial_message = (
            f":hourglass_flowing_sand: Traitement de '{command_name}' pour {num_items} {item_type_display}{plural_s}: "
            f"**`{'`, `'.join(base_names)}`**..."
        )
        await asyncio.to_thread(self.envoyer_message, channel_id, initial_message)

        if not self.config.PERMISSIONS_MATRIX:
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                ":x: Erreur: La matrice des permissions n'est pas chargée. Impossible de continuer.",
            )
            return

        overall_log_parts = [f"### Résumé global pour la commande `{command_name}`"]

        for base_name in base_names:
            logging.info(f"'{command_name}' command processing for: {base_name} by user {requesting_user_id}")
            item_log = await self._create_resources_for_category(
                base_name=base_name,
                category_key=category_key,
                admin_category_key=admin_category_key,
                item_type_display=item_type_display,
                requesting_user_id=requesting_user_id,  # Pass it down
            )
            overall_log_parts.extend(item_log)
            overall_log_parts.append("---")

        final_summary_message = "\n".join(overall_log_parts)
        await asyncio.to_thread(self.envoyer_message, channel_id, final_summary_message)

    async def _handle_create_projet_command(self, channel_id, arg_string, user_id_who_posted=None):  # Added user_id
        """Crée les ressources pour un ou plusieurs projets (standard et admin). Usage: create_projet <NomProjet1> [NomProjet2 ...]"""
        await self._execute_batch_create_command(
            channel_id, arg_string, "projet", "PROJET", "PROJET_ADMIN", "create_projet", user_id_who_posted
        )

    async def _handle_create_antenne_command(self, channel_id, arg_string, user_id_who_posted=None):  # Added user_id
        """Crée les ressources pour une ou plusieurs antennes (standard et admin). Usage: create_antenne <NomAntenne1> [NomAntenne2 ...]"""
        await self._execute_batch_create_command(
            channel_id, arg_string, "antenne", "ANTENNE", "ANTENNE_ADMIN", "create_antenne", user_id_who_posted
        )

    async def _handle_create_pole_command(self, channel_id, arg_string, user_id_who_posted=None):  # Added user_id
        """Crée les ressources pour un ou plusieurs pôles (standard et admin). Usage: create_pole <NomPole1> [NomPole2 ...]"""
        await self._execute_batch_create_command(
            channel_id, arg_string, "pôle", "POLES", "POLES_ADMIN", "create_pole", user_id_who_posted
        )

    async def _handle_sync_user_channels_command(
        self, channel_id, arg_string=None
    ):  # arg_string and user_id not used here
        """Triggers the synchronization of Mattermost channel users to Authentik groups."""
        logging.info(f"'{self.bot_name_mention} sync_user_channels' command received in channel {channel_id}.")

        initial_message_text = ":hourglass_flowing_sand: Démarrage de la synchronisation des utilisateurs des canaux Mattermost vers les groupes Authentik et collections Outline... Ceci peut prendre un moment."
        initial_post_id = await asyncio.to_thread(self.envoyer_message, channel_id, initial_message_text)

        if not self.authentik_client or not self.mattermost_api_client or not self.config.MATTERMOST_TEAM_ID:
            error_msg = (
                ":warning: **Erreur :** Le bot n'est pas correctement configuré pour la synchronisation. "
                "Client Authentik, client API Mattermost, ou ID d'équipe Mattermost manquant. "
                "Veuillez vérifier les logs du serveur."
            )
            logging.error(
                "Bot is not properly configured for sync (core components): Missing Authentik client, "
                "Mattermost API client, or Mattermost Team ID."
            )
            await asyncio.to_thread(self.envoyer_message, channel_id, error_msg, thread_id=initial_post_id)
            return

        if not self.outline_client:
            logging.info("Outline client not configured on this bot instance. Outline sync will be skipped.")

        try:
            logging.info("Dispatching group synchronization task to a thread...")
            orchestration_success, detailed_results = await asyncio.to_thread(
                orchestrate_group_synchronization,
                self.authentik_client,
                self.mattermost_api_client,
                self.outline_client,  # Peut être None, géré par l'orchestrateur
                self.config.MATTERMOST_TEAM_ID,
            )

            if not orchestration_success:  # Erreur critique dans l'orchestrateur lui-même
                logging.warning("Group synchronization task reported critical failure during orchestration.")
                summary_msg = (
                    ":x: La synchronisation des groupes a échoué de manière critique durant l'orchestration. "
                    "Veuillez consulter les logs du serveur pour plus de détails."
                )
                await asyncio.to_thread(self.envoyer_message, channel_id, summary_msg, thread_id=initial_post_id)
            else:
                logging.info(
                    f"Group synchronization task orchestration completed. Detailed results count: {len(detailed_results)}"
                )
                # Utiliser la méthode factorisée pour envoyer les résultats
                await self._format_and_send_sync_results(channel_id, initial_post_id, detailed_results)

        except Exception as e:
            logging.error(
                f"An unexpected error occurred while dispatching or running the sync task: {e}", exc_info=True
            )
            error_response_msg = ":boom: Une erreur serveur inattendue s'est produite lors de la tentative d'exécution de la synchronisation. Veuillez consulter les logs du serveur."
            await asyncio.to_thread(self.envoyer_message, channel_id, error_response_msg, thread_id=initial_post_id)

    def _request_shutdown(self):
        logging.info("Shutdown requested. Setting shutdown event.")
        self.shutdown_event.set()
        if self.websocket and self.websocket.open:
            logging.info("Requesting WebSocket close from _request_shutdown (scheduling task).")
            asyncio.create_task(self.websocket.close(code=1000, reason="Bot shutdown"))

    def envoyer_message(self, channel_id, message_text, thread_id=None) -> str | None:
        """
        Sends a message to the specified Mattermost channel.
        Returns the post ID of the sent message if successful, None otherwise.
        """
        if not self.config.BOT_TOKEN or not self.config.MATTERMOST_URL:
            logging.error("BOT_TOKEN or MATTERMOST_URL not configured for bot instance. Cannot send message.")
            return None

        headers = {
            "Authorization": f"Bearer {self.config.BOT_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "channel_id": channel_id,
            "message": message_text,
        }
        if thread_id:
            payload["root_id"] = thread_id

        post_url = f"{self.config.MATTERMOST_URL.rstrip('/')}/api/v4/posts"
        logging.debug(
            f"Mattermost API >> Sending message to channel {channel_id} (thread: {thread_id}). Payload: {json.dumps(payload)}"
        )
        log_message = f"Sending message to {post_url} in channel {channel_id}: {message_text[:100]}..."
        logging.info(log_message)
        try:
            response = requests.post(post_url, headers=headers, json=payload)
            response.raise_for_status()
            post_data = response.json()
            post_id = post_data.get("id")
            if post_id:
                logging.info(f"Message sent successfully to channel {channel_id}. Post ID: {post_id}")
                return post_id
            else:
                logging.error(
                    f"Message sent to channel {channel_id} but no post ID was returned in response: {post_data}"
                )
                return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Error sending message to Mattermost: {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON response from Mattermost after sending message: {e}")
            return None

    def _parse_command_from_mention(self, message_text_after_mention):
        stripped_text = message_text_after_mention.strip()
        if not stripped_text:
            return None, None

        parts = stripped_text.split(maxsplit=1)
        command_verb = parts[0].lower()
        arg_string = parts[1] if len(parts) > 1 else None
        return command_verb, arg_string

    async def _send_help_message(self, channel_id, arg_string=None):  # Added user_id, but not used by help
        """Displays this help message listing all available commands."""
        help_lines = ["### Commandes disponibles pour MartyBot", "---"]
        if not self.commands:
            help_lines.append("Aucune commande n'est actuellement disponible.")
        else:
            for cmd, handler_method in self.commands.items():
                docstring = handler_method.__doc__
                description = ""
                if docstring:
                    first_line = docstring.strip().split("\n")[0]
                    description = f" - _{first_line}_"
                help_lines.append(f"* **`{cmd}`**{description}")
        help_lines.append("\n---")
        help_lines.append("**Exemples de création :**")
        help_lines.append(f"* `{self.bot_name_mention} create_projet MonProjet1 MonProjet2`")
        help_lines.append(f"* `{self.bot_name_mention} create_antenne AntenneRegionale`")
        help_lines.append(f"* `{self.bot_name_mention} create_pole PoleTechnique AutrePole`")
        help_lines.append(
            f"\n**Note :** Les commandes `{self.bot_name_mention} sync_user_channels` et `{self.bot_name_mention} update_user_rights` "
            "peuvent prendre un certain temps pour s'exécuter."
        )
        help_lines.append(f"\nMentionnez-moi avec une commande, comme `{self.bot_name_mention} help`.")
        help_text = "\n".join(help_lines)
        await asyncio.to_thread(self.envoyer_message, channel_id, help_text)

    async def _handle_message_event(self, message_data):
        post_info = message_data.get("data", {}).get("post")
        if not post_info:
            logging.warning("No post data in 'posted' event.")
            return
        post_data = json.loads(post_info)
        message_text = post_data.get("message", "")
        channel_id = post_data.get("channel_id")
        user_id_who_posted = post_data.get("user_id")  # Get user_id here

        escaped_mention = re.escape(self.bot_name_mention)
        mention_match = re.search(rf"(?i)(?:^|\s){escaped_mention}(?:\s+(.*)|$)", message_text)

        if not mention_match:
            return
        text_after_mention = mention_match.group(1)
        command_verb, arg_string = self._parse_command_from_mention(text_after_mention if text_after_mention else "")

        if command_verb:
            handler_method = self.commands.get(command_verb)
            if handler_method:
                # Pass user_id_who_posted to command handlers that need it
                if command_verb in ["create_projet", "create_antenne", "create_pole"]:
                    await handler_method(channel_id, arg_string, user_id_who_posted=user_id_who_posted)
                elif (
                    command_verb == "sync_user_channels"
                ):  # This command doesn't need user_id_who_posted for its core logic
                    await handler_method(channel_id, arg_string)
                else:  # For help or other commands that might not need it
                    await handler_method(channel_id, arg_string)
            else:
                message = f":question: Commande inconnue : **`{command_verb}`**. Essayez `{self.bot_name_mention} help` pour une liste des commandes disponibles."
                await asyncio.to_thread(self.envoyer_message, channel_id, message)
        elif text_after_mention is None or text_after_mention.strip() == "":
            message = f"Bonjour ! Vous m'avez mentionné. Essayez `{self.bot_name_mention} help` pour une liste des commandes."
            await asyncio.to_thread(self.envoyer_message, channel_id, message)

    async def on_message(self, ws, message_str):
        logging.debug(f"WebSocket << Raw incoming message: {message_str}")
        try:
            data = json.loads(message_str)
            logging.debug(
                f"WebSocket << Event received: Type='{data.get('event')}', Seq='{data.get('seq')}', DataKeys='{list(data.get('data', {}).keys()) if data.get('data') else None}'"
            )
            event_type = data.get("event")

            if event_type == "posted":
                logging.debug(f"WebSocket << 'posted' event 'data' field raw content: {data.get('data')}")
                await self._handle_message_event(data)
            elif event_type == "hello":
                logging.info(f"WebSocket << Received 'hello' event: {data}")
            elif event_type:
                logging.debug(f"WebSocket << Received unhandled event type '{event_type}': {data}")
        except json.JSONDecodeError:
            logging.error(f"Error decoding JSON message: {message_str}")
        except Exception as e:
            logging.error(f"Error in on_message: {e}. Original message: {message_str}", exc_info=True)

    async def on_error(self, ws, error):
        logging.error(f"WebSocket Error: {error}")

    async def on_close(self, ws, close_status_code, close_msg):
        logging.info(f"WebSocket closed with code: {close_status_code}, message: {close_msg}")

    async def on_open(self, ws):
        logging.info("WebSocket connection opened.")
        if not self.config.BOT_TOKEN:
            logging.error("BOT_TOKEN not configured for bot instance. Cannot send authentication challenge.")
            await ws.close()
            return
        auth_data = {"seq": 1, "action": "authentication_challenge", "data": {"token": self.config.BOT_TOKEN}}
        try:
            await ws.send(json.dumps(auth_data))
            logging.info(
                f"Sent authentication challenge for bot token starting with: {str(self.config.BOT_TOKEN)[:4]}..."
            )
        except Exception as e:
            logging.error(f"Error sending authentication challenge: {e}")

    async def _run_websocket_loop(self):
        if not self.config.MATTERMOST_URL or not self.config.BOT_TOKEN:
            logging.error("Mattermost URL or Bot Token not configured for bot instance. Cannot start WebSocket.")
            return
        if not self.authentik_client and not self.outline_client and not self.mattermost_api_client:
            logging.warning("One or more API clients are not initialized. Bot may have limited functionality.")

        websocket_url = f"{self.config.MATTERMOST_URL.replace('http', 'ws', 1).rstrip('/')}/api/v4/websocket"
        reconnect_attempts = 0
        current_delay = self.INITIAL_RECONNECT_DELAY

        while not self.shutdown_event.is_set():
            try:
                logging.info(
                    f"Attempting to connect to WebSocket: {websocket_url} (Attempt: {reconnect_attempts + 1})"
                )
                async with websockets.connect(
                    websocket_url,
                    ping_interval=60,
                    ping_timeout=30,
                ) as self.websocket:
                    logging.info(f"Successfully connected to WebSocket: {websocket_url}")
                    await self.on_open(self.websocket)
                    reconnect_attempts = 0
                    current_delay = self.INITIAL_RECONNECT_DELAY
                    while not self.shutdown_event.is_set():
                        try:
                            message_str = await asyncio.wait_for(self.websocket.recv(), timeout=1.0)
                            if message_str:
                                await self.on_message(self.websocket, message_str)
                        except asyncio.TimeoutError:
                            if self.shutdown_event.is_set():
                                logging.debug("Shutdown event set during recv timeout, breaking inner loop.")
                                break
                            continue
                        except websockets.exceptions.ConnectionClosedOK as e:
                            logging.info(f"WebSocket connection closed normally by server (ClosedOK): {e}")
                            await self.on_close(self.websocket, e.code, e.reason)
                            break
                        except websockets.exceptions.ConnectionClosedError as e:
                            logging.warning(
                                f"WebSocket connection closed with error: {e}. Code: {e.code}, Reason: {e.reason}"
                            )
                            await self.on_close(self.websocket, e.code, e.reason)
                            break
                        except Exception as e:
                            logging.error(f"Error during WebSocket recv: {e}", exc_info=True)
                            await self.on_error(self.websocket, e)
                            break
                if self.shutdown_event.is_set():
                    logging.info("Shutdown event set, breaking outer connection loop.")
                    break
            except (
                websockets.exceptions.InvalidURI,
                websockets.exceptions.InvalidHandshake,
                ConnectionRefusedError,
                OSError,
            ) as e:
                logging.error(f"Failed to connect to WebSocket: {e}")
            except Exception as e:
                logging.error(f"Unexpected error during WebSocket connection attempt: {e}", exc_info=True)

            if not self.shutdown_event.is_set():
                reconnect_attempts += 1
                if reconnect_attempts >= self.MAX_RECONNECT_ATTEMPTS:
                    logging.error(f"Exceeded max reconnect attempts ({self.MAX_RECONNECT_ATTEMPTS}). Stopping bot.")
                    self.shutdown_event.set()
                    break
                logging.info(f"Reconnecting in {current_delay} seconds...")
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=current_delay)
                    if self.shutdown_event.is_set():
                        logging.info("Shutdown initiated during reconnect delay.")
                        break
                except asyncio.TimeoutError:
                    pass
                current_delay = min(current_delay * 2, self.MAX_RECONNECT_DELAY)

        logging.info("MartyBot WebSocket listener stopped.")
        if self.websocket and self.websocket.open:
            logging.info("Closing WebSocket connection finally (if still open)...")
            try:
                await self.websocket.close(code=1000, reason="Bot shutting down")
            except Exception as e:
                logging.error(f"Error during final WebSocket close: {e}")

    def start(self):
        logging.info(f"Initializing Marty Bot instance for dedicated thread: {threading.current_thread().name}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        logging.info(f"New asyncio event loop created and set for thread {threading.current_thread().name}")

        try:
            logging.info(
                f"Starting WebSocket listener for MartyBot instance in thread {threading.current_thread().name}..."
            )
            loop.run_until_complete(self._run_websocket_loop())
        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt caught in start(), requesting shutdown.")
            if not self.shutdown_event.is_set():
                self._request_shutdown()
        finally:
            logging.info(f"Cleaning up asyncio event loop in thread {threading.current_thread().name}.")
            try:
                all_tasks = asyncio.all_tasks(loop=loop)
                current_task = None
                if loop.is_running():
                    current_task = asyncio.current_task(loop=loop)
                tasks_to_cancel = [t for t in all_tasks if t is not current_task]
                if tasks_to_cancel:
                    logging.debug(f"Cancelling {len(tasks_to_cancel)} outstanding tasks.")
                    for task in tasks_to_cancel:
                        task.cancel()
                    loop.run_until_complete(asyncio.gather(*tasks_to_cancel, return_exceptions=True))
                    logging.debug("Outstanding tasks gathered after cancellation.")
                if hasattr(loop, "shutdown_asyncgens"):
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    logging.debug("Async generators shut down.")
            except RuntimeError as e:
                logging.warning(f"RuntimeError during task cleanup (likely loop already stopped): {e}")
            except Exception as e:
                logging.error(f"Error during task cleanup: {e}", exc_info=True)
            finally:
                if hasattr(loop, "shutdown_default_executor"):
                    try:
                        loop.run_until_complete(loop.shutdown_default_executor())
                        logging.debug("Default executor shut down.")
                    except Exception as e:
                        logging.error(f"Error shutting down default executor: {e}", exc_info=True)
                if not loop.is_closed():
                    loop.close()
                    logging.info(f"Asyncio event loop closed for thread {threading.current_thread().name}.")
                else:
                    logging.info(
                        f"Asyncio event loop was already closed for thread {threading.current_thread().name}."
                    )


if __name__ == "__main__":
    logging.info("Starting Marty Bot directly (for testing WebSocket connection)...")
    if not config.MATTERMOST_URL or not config.BOT_TOKEN or not config.BOT_NAME:
        logging.critical(
            "Cannot start directly: MATTERMOST_URL, BOT_TOKEN, or BOT_NAME is missing. "
            "Check .env file and config.py."
        )
    elif not config.MATTERMOST_TEAM_ID:
        logging.warning(
            "MATTERMOST_TEAM_ID is not set. `create_group` for Mattermost channels will fail."  # noqa: E501
        )
    else:
        log_msg = (
            f"Direct run config check: URL={config.MATTERMOST_URL}, BotName={config.BOT_NAME}, "
            f"Token starts with {str(config.BOT_TOKEN)[:4]}, TeamID={config.MATTERMOST_TEAM_ID}"
        )
        logging.info(log_msg)
        marty_bot_instance = MartyBot(config)
        marty_bot_instance.start()
