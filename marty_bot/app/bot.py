import websockets
import json
import re  # Import re for regular expressions
import os  # IMPORT MANQUANT !

# import threading # No longer used
import requests

# import os # No longer used
import asyncio
import logging
import markdown2  # For send_email Markdown to HTML conversion

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
from clients.nocodb_client import NocoDBClient  # Added NocoDBClient
from clients.vaultwarden_client import VaultwardenClient  # Added VaultwardenClient

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

        self.brevo_client = None  # Initialize brevo_client attribute
        if (
            hasattr(self.config, "BREVO_API_URL")
            and hasattr(self.config, "BREVO_API_KEY")
            and self.config.BREVO_API_URL
            and self.config.BREVO_API_KEY
        ):
            try:
                # Ensure BrevoClient is imported
                from clients.brevo_client import BrevoClient

                self.brevo_client = BrevoClient(self.config.BREVO_API_URL, self.config.BREVO_API_KEY)
                logging.info("BrevoClient initialized successfully for MartyBot instance.")
            except ValueError as e:
                logging.warning(f"Failed to initialize BrevoClient for MartyBot instance: {e}")
            except ImportError:
                logging.error("Failed to import BrevoClient. Brevo features will be disabled.")
        else:
            logging.warning(
                "Brevo API URL or Key not configured for MartyBot instance. Brevo features will be disabled."
            )

        self.nocodb_client = None
        if self.config.NOCODB_URL and self.config.NOCODB_TOKEN:
            try:
                self.nocodb_client = NocoDBClient(self.config.NOCODB_URL, self.config.NOCODB_TOKEN)
                logging.info("NocoDBClient initialized successfully for MartyBot instance.")
            except ValueError as e:
                logging.warning(f"Failed to initialize NocoDBClient for MartyBot instance: {e}")
        else:
            logging.warning(
                "NocoDB URL or Token not configured for MartyBot instance. NocoDB features will be disabled."
            )

        self.vaultwarden_client = None
        if self.config.VAULTWARDEN_ORGANIZATION_ID:
            try:
                # VAULTWARDEN_SERVER_URL is optional for the client constructor
                self.vaultwarden_client = VaultwardenClient(
                    organization_id=self.config.VAULTWARDEN_ORGANIZATION_ID,
                    server_url=self.config.VAULTWARDEN_SERVER_URL,
                    api_username=self.config.VAULTWARDEN_API_USERNAME,
                    api_password=self.config.VAULTWARDEN_API_PASSWORD,
                )
                logging.info("VaultwardenClient initialized successfully for MartyBot instance.")
            except ValueError as e:  # Catch specific error from client if org_id is missing (already checked by if)
                logging.warning(f"Failed to initialize VaultwardenClient for MartyBot instance: {e}")
            except Exception as e:  # Catch other potential errors like 'bw' not found
                logging.error(
                    f"An unexpected error occurred during VaultwardenClient initialization: {e}", exc_info=True
                )
                self.vaultwarden_client = None  # Ensure client is None if init fails
        else:
            logging.warning(
                "Vaultwarden Organization ID not configured for MartyBot instance. Vaultwarden features will be disabled."
            )

        self.websocket = None  # Represents the active WebSocket connection object

        # For graceful shutdown
        self.shutdown_event = asyncio.Event()

        # Reconnection parameters
        self.MAX_RECONNECT_ATTEMPTS = 5
        self.INITIAL_RECONNECT_DELAY = 5  # seconds
        self.MAX_RECONNECT_DELAY = 60  # seconds

        self.commands = {
            "create_projet": lambda c, arg_str, user_id_who_posted: self._execute_batch_create_command(
                c, arg_str, "projet", "PROJET", user_id_who_posted
            ),
            "create_antenne": lambda c, arg_str, user_id_who_posted: self._execute_batch_create_command(
                c, arg_str, "antenne", "ANTENNE", user_id_who_posted
            ),
            "create_pole": lambda c, arg_str, user_id_who_posted: self._execute_batch_create_command(
                c, arg_str, "pôle", "POLES", user_id_who_posted
            ),
            "help": self._send_help_message,  # help handler does not need user_id_who_posted
            "update_all_user_rights": self._handle_update_all_user_rights_command,  # Will now take user_id_who_posted
            "update_user_rights_and_remove": self._handle_update_user_rights_and_remove_command,  # Will now take user_id_who_posted
            "send_email": self._handle_send_email_command,
        }

    async def _format_and_send_sync_results(
        self,
        channel_id: str,
        initial_post_id: str | None,
        detailed_results: list[dict],
        command_name: str = "synchronisation",
    ):
        """Helper function to format and send detailed synchronization results."""
        if not detailed_results:
            final_summary_message = f":information_source: Processus de {command_name} terminé, mais aucune opération utilisateur spécifique n'a été effectuée ou rapportée."
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
        summary_lines = [f"### :checkered_flag: Résumé de {command_name} des droits :"]
        summary_lines.append(f"- Opérations réussies : {total_success_ops}")
        if total_problem_ops > 0:
            summary_lines.append(f"- Problèmes/omissions : {total_problem_ops}")

        summary_lines.append("\n**Détail des actions :**")
        for act, count in sorted(action_summary.items()):
            summary_lines.append(f"- `{act}` : {count} fois")

        if total_problem_ops > 0 and total_success_ops > 0:
            summary_lines.insert(1, f":warning: {command_name.capitalize()} partiellement terminée.")
        elif total_problem_ops > 0:
            summary_lines.insert(1, f":x: {command_name.capitalize()} terminée avec des problèmes/omissions.")
        elif total_success_ops > 0:
            summary_lines.insert(1, f":rocket: {command_name.capitalize()} terminée avec succès.")
        else:  # No ops or only skips like NO_MM_EMAIL
            summary_lines.insert(
                1,
                f":information_source: {command_name.capitalize()} terminée. Peu ou pas d'opérations significatives effectuées.",
            )

        final_summary_message = "\n".join(summary_lines)
        if final_summary_message:
            await asyncio.to_thread(self.envoyer_message, channel_id, final_summary_message, thread_id=initial_post_id)

    async def _handle_update_user_rights_and_remove_command(
        self, channel_id, arg_string=None, user_id_who_posted=None
    ):
        """Synchronise les droits (ajouts/mises à jour) ET supprime les accès obsolètes. Nécessite les droits admin."""
        logging.info(
            f"'{self.bot_name_mention} update_user_rights_and_remove' command received in channel {channel_id} by user {user_id_who_posted} with args: '{arg_string}'."
        )

        if not self.mattermost_api_client or not user_id_who_posted:
            logging.error("Mattermost API client or user_id_who_posted not available for permission check.")
            await asyncio.to_thread(
                self.envoyer_message, channel_id, ":x: Erreur interne : Impossible de vérifier les permissions."
            )
            return

        user_roles = await asyncio.to_thread(self.mattermost_api_client.get_user_roles, user_id_who_posted)
        if "system_admin" not in user_roles:
            logging.warning(
                f"User {user_id_who_posted} (roles: {user_roles}) attempted to use 'update_user_rights_and_remove' without admin rights."
            )
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                ":no_entry_sign: Accès refusé. Cette commande nécessite les droits d'administrateur Mattermost.",
            )
            return

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
        initial_post_id = await asyncio.to_thread(self.envoyer_message, channel_id, initial_message_text)

        if not self.authentik_client or not self.mattermost_api_client or not self.config.MATTERMOST_TEAM_ID:
            error_msg = (
                ":warning: **Erreur :** Le bot n'est pas correctement configuré pour cette opération. "
                "Client Authentik, client API Mattermost, ou ID d'équipe Mattermost manquant. "
                "Veuillez vérifier les logs du serveur."
            )
            logging.error(
                "Bot is not properly configured for rights removal (core components): Missing Authentik client, "
                "Mattermost API client, or Mattermost Team ID."
            )
            await asyncio.to_thread(self.envoyer_message, channel_id, error_msg, thread_id=initial_post_id)
            return

        if not self.outline_client:
            logging.info(
                "Outline client not configured on this bot instance. Outline synchronization will be skipped for remove_user_rights."
            )

        try:
            logging.info("Dispatching group synchronization task (for rights removal) to a thread...")
            orchestration_success, detailed_results = await asyncio.to_thread(
                orchestrate_group_synchronization,
                self.authentik_client,
                self.mattermost_api_client,
                self.outline_client,
                self.brevo_client,
                self.nocodb_client,
                self.vaultwarden_client,  # Pass Vaultwarden client
                self.config.MATTERMOST_TEAM_ID,
                perform_deletions=True,
                fetch_remote_members=True,
                skip_services=skip_services_list if skip_services_list else None,  # Pass skip_services
            )

            if not orchestration_success:
                logging.warning(
                    "Group synchronization task (for rights removal) reported critical failure during orchestration."
                )
                summary_msg = (
                    ":x: La suppression/synchronisation des droits a échoué de manière critique durant l'orchestration. "
                    "Veuillez consulter les logs du serveur pour plus de détails."
                )
                await asyncio.to_thread(self.envoyer_message, channel_id, summary_msg, thread_id=initial_post_id)
            else:
                logging.info(
                    f"Group synchronization task (for rights removal) orchestration completed. Detailed results count: {len(detailed_results)}"
                )
                await self._format_and_send_sync_results(
                    channel_id, initial_post_id, detailed_results, command_name="Suppression/synchronisation"
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
            await asyncio.to_thread(self.envoyer_message, channel_id, error_response_msg, thread_id=initial_post_id)

    async def _create_resources_for_entity(
        self,
        base_name: str,  # User-provided name, e.g., "MonProjet"
        entity_key: str,  # Key from PERMISSIONS_MATRIX, e.g., "PROJET"
        item_type_display: str,  # e.g., "projet"
        requesting_user_id: str | None,
    ):
        """
        Helper function to create resources for a given entity type (e.g., PROJET)
        based on the new permissions matrix structure.
        """
        item_results_log = []
        entity_config = self.config.PERMISSIONS_MATRIX.get(entity_key)

        if not entity_config:
            msg = f":x: Configuration error: No permissions found for entity category '{entity_key}' in the matrix."
            logging.error(msg)
            item_results_log.append(msg)
            return item_results_log

        item_results_log.append(
            f"--- Création pour {item_type_display} **`{base_name}`** (entité: *{entity_key}*) ---"
        )

        # Standard resources
        standard_config = entity_config.get("standard")
        if standard_config:
            std_auth_pattern = standard_config.get("authentik_group_name_pattern", "{base_name}")
            std_mm_chan_pattern = standard_config.get("mattermost_channel_name_pattern", "{base_name}")
            std_mm_chan_type = standard_config.get("mattermost_channel_type", "O")

            std_auth_name = std_auth_pattern.format(base_name=base_name)
            std_mm_chan_name = std_mm_chan_pattern.format(base_name=base_name)

            item_results_log.append(f"  - Standard (base: `{base_name}`):")
            # Authentik Group (Standard)
            auth_msg_std = f"    - Authentik Groupe `{std_auth_name}`: "
            if self.authentik_client:
                try:
                    if self.authentik_client.create_group(std_auth_name):
                        auth_msg_std += ":white_check_mark: Créé."
                    else:
                        auth_msg_std += ":warning: Échec/Existe déjà."
                except Exception as e:
                    auth_msg_std += f":x: Erreur ({e})."
            else:
                auth_msg_std += ":information_source: Client non configuré."
            item_results_log.append(auth_msg_std)

            # Mattermost Channel (Standard)
            mm_msg_std = f"    - Mattermost Canal `{std_mm_chan_name}` (type: {std_mm_chan_type}): "
            if self.mattermost_api_client:
                try:
                    ch_std = self.mattermost_api_client.create_channel(std_mm_chan_name, channel_type=std_mm_chan_type)
                    if ch_std and ch_std.get("id"):
                        mm_msg_std += f":white_check_mark: Créé (ID: {ch_std['id']})."
                        if requesting_user_id and self.mattermost_api_client.add_user_to_channel(
                            ch_std["id"], requesting_user_id
                        ):
                            mm_msg_std += " Demandeur ajouté."
                        elif requesting_user_id:
                            mm_msg_std += " Échec ajout demandeur."
                    else:
                        mm_msg_std += ":warning: Échec/Existe déjà."
                except Exception as e:
                    mm_msg_std += f":x: Erreur ({e})."
            else:
                mm_msg_std += ":information_source: Client non configuré."
            item_results_log.append(mm_msg_std)

        # Admin resources (if configured)
        admin_config = entity_config.get("admin")
        if admin_config:
            adm_auth_pattern = admin_config.get("authentik_group_name_pattern", "{base_name} Admin")
            adm_mm_chan_pattern = admin_config.get("mattermost_channel_name_pattern", "{base_name} Admin")
            adm_mm_chan_type = admin_config.get("mattermost_channel_type", "P")

            adm_auth_name = adm_auth_pattern.format(base_name=base_name)
            adm_mm_chan_name = adm_mm_chan_pattern.format(base_name=base_name)

            item_results_log.append(f"  - Admin (base: `{base_name}`):")
            # Authentik Group (Admin)
            auth_msg_adm = f"    - Authentik Groupe `{adm_auth_name}`: "
            if self.authentik_client:
                try:
                    if self.authentik_client.create_group(adm_auth_name):
                        auth_msg_adm += ":white_check_mark: Créé."
                    else:
                        auth_msg_adm += ":warning: Échec/Existe déjà."
                except Exception as e:
                    auth_msg_adm += f":x: Erreur ({e})."
            else:
                auth_msg_adm += ":information_source: Client non configuré."
            item_results_log.append(auth_msg_adm)

            # Mattermost Channel (Admin)
            mm_msg_adm = f"    - Mattermost Canal `{adm_mm_chan_name}` (type: {adm_mm_chan_type}): "
            if self.mattermost_api_client:
                try:
                    ch_adm = self.mattermost_api_client.create_channel(adm_mm_chan_name, channel_type=adm_mm_chan_type)
                    if ch_adm and ch_adm.get("id"):
                        mm_msg_adm += f":white_check_mark: Créé (ID: {ch_adm['id']})."
                        if requesting_user_id and self.mattermost_api_client.add_user_to_channel(
                            ch_adm["id"], requesting_user_id
                        ):
                            mm_msg_adm += " Demandeur ajouté."
                        elif requesting_user_id:
                            mm_msg_adm += " Échec ajout demandeur."
                    else:
                        mm_msg_adm += ":warning: Échec/Existe déjà."
                except Exception as e:
                    mm_msg_adm += f":x: Erreur ({e})."
            else:
                mm_msg_adm += ":information_source: Client non configuré."
            item_results_log.append(mm_msg_adm)

        # Outline Collection (unique per entity)
        outline_config = entity_config.get("outline")
        if outline_config:
            coll_pattern = outline_config.get("collection_name_pattern", "{base_name}")
            outline_coll_name = coll_pattern.format(base_name=base_name)

            outline_msg = f"  - Outline Collection `{outline_coll_name}`: "
            if self.outline_client:
                try:
                    collection_obj = self.outline_client.create_group(outline_coll_name)
                    if collection_obj and collection_obj.get("id"):
                        # Simplification: On ne sait plus facilement si "CREATED" ou "EXISTS" ici sans changer plus create_group.
                        # On logue un succès générique si on a un objet collection valide.
                        outline_msg += ":white_check_mark: Collection assurée (créée ou existante)."
                    else:
                        outline_msg += ":warning: Échec création/vérification."
                except Exception as e:
                    outline_msg += f":x: Erreur ({e})."
            else:
                outline_msg += ":information_source: Client non configuré."
            item_results_log.append(outline_msg)

        # Brevo List (unique per entity)
        brevo_config = entity_config.get("brevo")
        if brevo_config:
            brevo_list_pattern = brevo_config.get(
                "list_name_pattern", "mm_list_{base_name}"
            )  # Default pattern if not specified
            brevo_list_name = brevo_list_pattern.format(base_name=base_name)
            folder_name_from_matrix = brevo_config.get("folder_name")
            target_folder_id = 1  # Default Brevo folder ID

            brevo_msg = f"  - Brevo Liste `{brevo_list_name}`"

            if self.brevo_client and folder_name_from_matrix:
                try:
                    fetched_folder_id = await asyncio.to_thread(
                        self.brevo_client.get_folder_id_by_name, folder_name_from_matrix
                    )
                    if fetched_folder_id:
                        target_folder_id = fetched_folder_id
                        brevo_msg += f" (Dossier: '{folder_name_from_matrix}', ID: {target_folder_id})"
                    else:
                        brevo_msg += f" (Dossier: '{folder_name_from_matrix}' introuvable, utilise défaut ID: {target_folder_id})"
                        logging.warning(
                            f"Brevo folder '{folder_name_from_matrix}' not found for list '{brevo_list_name}'. Using default folder ID {target_folder_id}."
                        )
                except Exception as e:
                    brevo_msg += f" (Erreur recherche dossier '{folder_name_from_matrix}', utilise défaut ID: {target_folder_id}): {e}"
                    logging.error(f"Error fetching Brevo folder ID for '{folder_name_from_matrix}': {e}")
            elif self.brevo_client:
                brevo_msg += f" (Dossier par défaut ID: {target_folder_id})"

            brevo_msg += ": "

            if self.brevo_client:
                try:
                    existing_list = await asyncio.to_thread(self.brevo_client.get_list_by_name, brevo_list_name)
                    if existing_list:
                        current_folder_id = existing_list.get("folderId")
                        if current_folder_id == target_folder_id:
                            brevo_msg += f":white_check_mark: Existe déjà (ID: {existing_list['id']})."
                        else:
                            brevo_msg += f":warning: Existe déjà (ID: {existing_list['id']}) mais dans un autre dossier (ID: {current_folder_id}). Non déplacée."
                            # Log this situation clearly
                            logging.warning(
                                f"Brevo list '{brevo_list_name}' (ID: {existing_list['id']}) exists in folder {current_folder_id}, target was {target_folder_id}. List not moved or recreated."
                            )
                    else:
                        # If not found globally, create it in the target folder
                        created_list = await asyncio.to_thread(
                            self.brevo_client.create_list, brevo_list_name, folder_id=int(target_folder_id)
                        )
                        if created_list and created_list.get("id"):
                            brevo_msg += f":white_check_mark: Créée (ID: {created_list['id']})."
                        else:
                            brevo_msg += ":warning: Échec création/vérification."
                except Exception as e:
                    brevo_msg += f":x: Erreur ({e})."
            else:
                brevo_msg += ":information_source: Client non configuré."
            item_results_log.append(brevo_msg)

        # NoCoDB Base (for ANTENNE and POLES)
        nocodb_config = entity_config.get("nocodb")
        if nocodb_config and entity_key in ["ANTENNE", "POLES"]:  # Only for specific entities
            base_title_pattern = nocodb_config.get("base_title_pattern", "nocodb_{base_name}")
            nocodb_base_title = base_title_pattern.format(base_name=base_name)
            nocodb_msg = f"  - NoCoDB Base `{nocodb_base_title}`: "

            if self.nocodb_client:
                try:
                    # Check if base already exists to avoid error and log appropriately
                    existing_base = await asyncio.to_thread(self.nocodb_client.get_base_by_title, nocodb_base_title)
                    if existing_base:
                        nocodb_msg += f":white_check_mark: Existe déjà (ID: {existing_base['id']})."
                    else:
                        # Create the base if it doesn't exist
                        created_base = await asyncio.to_thread(self.nocodb_client.create_base, nocodb_base_title)
                        if created_base and created_base.get("id"):
                            nocodb_msg += f":white_check_mark: Créée (ID: {created_base['id']})."
                        else:
                            nocodb_msg += ":warning: Échec création."
                except Exception as e:
                    nocodb_msg += f":x: Erreur ({e})."
            else:
                nocodb_msg += ":information_source: Client non configuré."
            item_results_log.append(nocodb_msg)

        # Vaultwarden Collection (unique per entity)
        vaultwarden_config = entity_config.get("vaultwarden")
        if vaultwarden_config:
            vw_coll_pattern = vaultwarden_config.get(
                "collection_name_pattern", "Shared - {base_name}"
            )  # Default pattern
            vw_coll_name = vw_coll_pattern.format(base_name=base_name)

            vw_msg = f"  - Vaultwarden Collection `{vw_coll_name}`: "
            if self.vaultwarden_client:
                # The create_collection method in the client handles checking for existing collections.
                # It requires BW_PASSWORD to be set in the environment.
                if not os.getenv("BW_PASSWORD"):
                    vw_msg += ":warning: Échec - BW_PASSWORD non défini dans l'environnement."
                    logging.warning(
                        f"Vaultwarden: BW_PASSWORD not set in environment. Cannot create collection '{vw_coll_name}'."
                    )
                else:
                    try:
                        # Assuming create_collection returns the collection ID if successful/exists, None otherwise
                        collection_id = await asyncio.to_thread(
                            self.vaultwarden_client.create_collection, vw_coll_name
                        )
                        if collection_id:
                            # We don't easily know if it was "created" vs "existed" without more client logic,
                            # so a generic success message.
                            vw_msg += f":white_check_mark: Collection assurée (ID: {collection_id})."
                        else:
                            vw_msg += ":warning: Échec création/vérification."
                    except FileNotFoundError:  # Raised by client if 'bw' CLI is not found
                        error_message = "CLI 'bw' non trouvée."
                        vw_msg += f":x: Erreur ({error_message})."
                        logging.error(f"Vaultwarden client error for collection '{vw_coll_name}': {error_message}")
                    except Exception as e:
                        vw_msg += f":x: Erreur ({e})."
                        logging.error(f"Error creating Vaultwarden collection '{vw_coll_name}': {e}", exc_info=True)
            else:
                vw_msg += ":information_source: Client non configuré."
            item_results_log.append(vw_msg)

        return item_results_log

    async def _execute_batch_create_command(
        self,
        channel_id: str,
        arg_string: str | None,
        item_type_display: str,  # e.g. "projet"
        entity_key: str,  # e.g. "PROJET"
        requesting_user_id: str | None,
    ):
        """Generic handler for create commands supporting multiple arguments, using new matrix structure."""
        command_name = f"create_{item_type_display.lower()}"  # Reconstruct command name for messages
        if not arg_string:
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                f":warning: Au moins un nom de {item_type_display} est requis. Usage: `{self.bot_name_mention} {command_name} <Nom1> [Nom2 ...]`",
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

        entity_config = self.config.PERMISSIONS_MATRIX.get(entity_key)
        if not entity_config:
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                f":x: Erreur: Configuration pour l'entité '{entity_key}' non trouvée dans la matrice des permissions.",
            )
            return

        overall_log_parts = [f"### Résumé global pour la commande `{command_name}`"]

        for base_name in base_names:
            logging.info(
                f"'{command_name}' command processing for: {base_name} (entity: {entity_key}) by user {requesting_user_id}"
            )
            # Pass the whole entity_config dict for this entity_key
            item_log = await self._create_resources_for_entity(
                base_name=base_name,
                entity_key=entity_key,
                item_type_display=item_type_display,
                requesting_user_id=requesting_user_id,
            )
            overall_log_parts.extend(item_log)
            overall_log_parts.append("---")

        final_summary_message = "\n".join(overall_log_parts)
        await asyncio.to_thread(self.envoyer_message, channel_id, final_summary_message)

    # _handle_create_projet_command, _handle_create_antenne_command, _handle_create_pole_command
    # are now simplified by the lambdas in self.commands, directly calling _execute_batch_create_command.
    # They can be removed if no other specific logic is needed for them.
    # For now, I will keep them commented out in case they are needed for more specific logic later.
    # async def _handle_create_projet_command(self, channel_id, arg_string, user_id_who_posted=None):
    #     """Crée les ressources pour un ou plusieurs projets. Usage: create_projet <NomProjet1> [NomProjet2 ...]"""
    #     await self._execute_batch_create_command(
    #         channel_id, arg_string, "projet", "PROJET", user_id_who_posted
    #     )
    # async def _handle_create_antenne_command(self, channel_id, arg_string, user_id_who_posted=None):
    #     """Crée les ressources pour une ou plusieurs antennes. Usage: create_antenne <NomAntenne1> [NomAntenne2 ...]"""
    #     await self._execute_batch_create_command(
    #         channel_id, arg_string, "antenne", "ANTENNE", user_id_who_posted
    #     )
    # async def _handle_create_pole_command(self, channel_id, arg_string, user_id_who_posted=None):
    #     """Crée les ressources pour un ou plusieurs pôles. Usage: create_pole <NomPole1> [NomPole2 ...]"""
    #     await self._execute_batch_create_command(
    #         channel_id, arg_string, "pôle", "POLES", user_id_who_posted
    #     )

    async def _handle_update_all_user_rights_command(self, channel_id, arg_string=None, user_id_who_posted=None):
        """S'assure que les utilisateurs Mattermost ont les bons droits (ajouts/mises à jour uniquement). Nécessite les droits admin."""
        logging.info(
            f"'{self.bot_name_mention} update_all_user_rights' (upsert) command received in channel {channel_id} by user {user_id_who_posted}."
        )

        if not self.mattermost_api_client or not user_id_who_posted:
            logging.error("Mattermost API client or user_id_who_posted not available for permission check.")
            await asyncio.to_thread(
                self.envoyer_message, channel_id, ":x: Erreur interne : Impossible de vérifier les permissions."
            )
            return

        user_roles = await asyncio.to_thread(self.mattermost_api_client.get_user_roles, user_id_who_posted)
        if "system_admin" not in user_roles:
            logging.warning(
                f"User {user_id_who_posted} (roles: {user_roles}) attempted to use 'update_all_user_rights' without admin rights."
            )
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                ":no_entry_sign: Accès refusé. Cette commande nécessite les droits d'administrateur Mattermost.",
            )
            return

        initial_message_text = ":hourglass_flowing_sand: Démarrage de la mise à jour des droits utilisateurs (ajouts/modifications uniquement)... Ceci peut prendre un moment."
        initial_post_id = await asyncio.to_thread(self.envoyer_message, channel_id, initial_message_text)

        if not self.authentik_client or not self.mattermost_api_client or not self.config.MATTERMOST_TEAM_ID:
            error_msg = (
                ":warning: **Erreur :** Le bot n'est pas correctement configuré pour la mise à jour des droits. "
                "Client Authentik, client API Mattermost, ou ID d'équipe Mattermost manquant. "
                "Veuillez vérifier les logs du serveur."
            )
            logging.error(
                "Bot is not properly configured for rights update (upsert): Missing Authentik client, "
                "Mattermost API client, or Mattermost Team ID."
            )
            await asyncio.to_thread(self.envoyer_message, channel_id, error_msg, thread_id=initial_post_id)
            return

        if not self.outline_client:
            logging.info("Outline client not configured. Outline operations will be skipped for update_user_rights.")

        try:
            logging.info("Dispatching group synchronization task (upsert mode) to a thread...")
            orchestration_success, detailed_results = await asyncio.to_thread(
                orchestrate_group_synchronization,
                self.authentik_client,
                self.mattermost_api_client,
                self.outline_client,
                self.brevo_client,
                self.nocodb_client,
                self.vaultwarden_client,  # Pass Vaultwarden client
                self.config.MATTERMOST_TEAM_ID,
                perform_deletions=False,
                fetch_remote_members=False,
                skip_services=None,  # Explicitly pass None
            )

            if not orchestration_success:
                logging.warning(
                    "Group synchronization task (upsert mode) reported critical failure during orchestration."
                )
                summary_msg = (
                    ":x: La mise à jour des droits (upsert) a échoué de manière critique durant l'orchestration. "
                    "Veuillez consulter les logs du serveur pour plus de détails."
                )
                await asyncio.to_thread(self.envoyer_message, channel_id, summary_msg, thread_id=initial_post_id)
            else:
                logging.info(
                    f"Group synchronization task (upsert mode) orchestration completed. Detailed results count: {len(detailed_results)}"
                )
                await self._format_and_send_sync_results(
                    channel_id, initial_post_id, detailed_results, command_name="Mise à jour (upsert)"
                )

        except Exception as e:
            logging.error(
                f"An unexpected error occurred while dispatching or running the upsert task: {e}", exc_info=True
            )
            error_response_msg = ":boom: Une erreur serveur inattendue s'est produite lors de la tentative d'exécution de la mise à jour des droits (upsert). Veuillez consulter les logs du serveur."
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
        help_lines.append("\n**Commandes de synchronisation des droits utilisateurs :**")
        help_lines.append(f"* **`{self.bot_name_mention} update_all_user_rights`**")
        help_lines.append(
            "  - _Rôle : S'assure que les utilisateurs présents dans les canaux Mattermost ont bien les accès correspondants dans Authentik et Outline._"
        )
        help_lines.append(
            "  - _Logique : Part des canaux Mattermost. Ajoute les utilisateurs aux groupes/collections distants si nécessaire, ou met à jour leurs permissions. **Ne supprime jamais d'accès.** Idéal pour ajouter rapidement des droits suite à l'ajout d'un utilisateur à un canal Mattermost._"
        )
        help_lines.append(f"* **`{self.bot_name_mention} update_user_rights_and_remove`**")
        help_lines.append(
            "  - _Rôle : Effectue une synchronisation complète des droits. Garantit que les accès dans Authentik/Outline reflètent exactement la composition des canaux Mattermost._"
        )
        help_lines.append(
            "  - _Logique : Combine les actions de `update_all_user_rights` (ajouts/mises à jour depuis Mattermost) ET **supprime les accès** des utilisateurs dans Authentik/Outline/NoCoDB s'ils ne sont plus présents dans les canaux Mattermost correspondants (ou si leurs droits ont changé). C'est la commande à utiliser pour une remise en cohérence complète._"
        )
        help_lines.append(
            f"  - _Option :_ Ajoutez `nocodb=false` après la commande (ex: `{self.bot_name_mention} update_user_rights_and_remove nocodb=false`) pour ignorer la synchronisation NoCoDB."
        )
        help_lines.append(
            "\n**Note :** La commande `update_user_rights_and_remove` est plus complète mais peut prendre plus de temps car elle vérifie tous les membres des services distants."
        )
        help_lines.append("\n**Commande d'envoi d'email (via Brevo) :**")
        help_lines.append(f"* **`{self.bot_name_mention} send_email <Sujet> /// <Message>`**")
        help_lines.append(
            '  - _Rôle : Envoie un email via Brevo aux membres de la liste de contacts associée au canal "standard" de l\'entité._'
        )
        help_lines.append(
            '  - _Usage : Doit être exécutée depuis le canal "admin" de l\'entité (projet, pôle, antenne). Le sujet et le message sont séparés par `///`._'
        )
        help_lines.append(f"\nMentionnez-moi avec une commande, comme `{self.bot_name_mention} help`.")
        help_text = "\n".join(help_lines)
        await asyncio.to_thread(self.envoyer_message, channel_id, help_text)

    async def _handle_send_email_command(self, channel_id: str, arg_string: str | None, user_id_who_posted: str):
        """
        Envoie un email via Brevo aux membres du canal standard associé.
        Usage: @marty send_email <Sujet de l'email> /// <Contenu de l'email>
        Doit être lancé depuis un canal admin d'une entité (projet, pôle, antenne).
        """
        logging.info(f"'send_email' command received in channel {channel_id} by user {user_id_who_posted}.")

        if not self.brevo_client:
            await asyncio.to_thread(
                self.envoyer_message, channel_id, ":x: Erreur: Le client Brevo n'est pas configuré."
            )
            return
        if not self.config.BREVO_DEFAULT_SENDER_EMAIL or not self.config.BREVO_DEFAULT_SENDER_NAME:
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                ":x: Erreur: L'expéditeur par défaut (email/nom) n'est pas configuré pour Brevo.",
            )
            return
        if not self.mattermost_api_client:
            await asyncio.to_thread(
                self.envoyer_message, channel_id, ":x: Erreur: Le client Mattermost API n'est pas configuré."
            )
            return

        if not arg_string or "///" not in arg_string:
            usage_msg = "Usage: `@marty send_email <Sujet de l'email> /// <Contenu de l'email>`"
            await asyncio.to_thread(self.envoyer_message, channel_id, f":warning: Syntaxe incorrecte. {usage_msg}")
            return

        subject, text_content = [part.strip() for part in arg_string.split("///", 1)]

        if not subject or not text_content:
            usage_msg = "Usage: `@marty send_email <Sujet de l'email> /// <Contenu de l'email>`"
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                f":warning: Le sujet et le contenu ne peuvent pas être vides. {usage_msg}",
            )
            return

        # 1. Vérifier que la commande est lancée depuis un canal admin et identifier l'entité
        current_channel_info = await asyncio.to_thread(
            self.mattermost_api_client.get_channel_by_id, channel_id
        )  # Corrected method call
        if not current_channel_info:
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                ":x: Erreur: Impossible de récupérer les informations du canal actuel.",
            )
            return

        # Check if user is a member of the current (admin) channel
        channel_members = await asyncio.to_thread(
            self.mattermost_api_client.get_users_in_channel, channel_id
        )  # Corrected method
        if not any(
            member.get("id") == user_id_who_posted for member in channel_members
        ):  # Changed "user_id" to "id" and added .get()
            logging.warning(
                f"User {user_id_who_posted} tried to use send_email from channel {channel_id} but is not a member."
            )
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                ":x: Erreur: Vous devez être membre de ce canal admin pour utiliser cette commande.",
            )
            return

        entity_key_found = None
        base_name_found = None
        admin_channel_name_slug = current_channel_info.get("name")

        from libraries.group_sync_services import (
            _map_mm_channel_to_entity_and_base_name,
            slugify,
        )  # For slugify if needed by map

        # We need to iterate through PERMISSIONS_MATRIX to find which entity this admin channel belongs to
        # This is a bit reversed from the usual mapping.
        for e_key, e_conf in self.config.PERMISSIONS_MATRIX.items():
            admin_cfg = e_conf.get("admin")
            if admin_cfg:
                admin_pattern = admin_cfg.get("mattermost_channel_name_pattern")
                if admin_pattern:
                    # We need to check if current_channel_info['name'] (slug) or ['display_name'] matches a *potential* admin channel
                    # This requires trying to extract a base_name and re-formatting, or having a direct match.
                    # For simplicity, we'll assume the channel name is relatively standard.
                    # A robust way is to use the _map_mm_channel_to_entity_and_base_name
                    # but that function itself might need adjustment if it only maps from base_name to channel, not channel to base_name.
                    # Let's try to extract base_name from current admin channel assuming it ends with " Admin" or similar.
                    # This part is tricky and might need refinement based on exact naming conventions.

                    # Attempt with display_name:
                    temp_entity_key, temp_base_name = _map_mm_channel_to_entity_and_base_name(
                        admin_channel_name_slug,
                        current_channel_info.get("display_name"),
                        {e_key: e_conf},  # Pass only current entity for specific matching
                    )
                    if temp_entity_key == e_key and temp_base_name:
                        # Verify if this is indeed an admin channel for THIS entity_key
                        expected_admin_channel_slug = slugify(admin_pattern.format(base_name=temp_base_name))
                        if admin_channel_name_slug == expected_admin_channel_slug:
                            entity_key_found = e_key
                            base_name_found = temp_base_name
                            break

        if not entity_key_found or not base_name_found:
            logging.warning(
                f"Channel {channel_id} ('{current_channel_info.get('display_name')}') is not recognized as a configured admin channel for any entity."
            )
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                ":x: Erreur: Cette commande doit être lancée depuis un canal admin d'une entité configurée (projet, pôle, antenne).",
            )
            return

        logging.info(
            f"Command 'send_email' validated for entity '{base_name_found}' (type: {entity_key_found}) from admin channel '{current_channel_info.get('display_name')}'."
        )

        # 2. Récupérer la liste Brevo du canal standard
        entity_permissions = self.config.PERMISSIONS_MATRIX.get(entity_key_found, {})
        brevo_config = entity_permissions.get("brevo", {})
        brevo_list_pattern = brevo_config.get("list_name_pattern")
        standard_channel_config = entity_permissions.get("standard", {})
        standard_mm_channel_name_pattern = standard_channel_config.get("mattermost_channel_name_pattern")

        if not brevo_list_pattern or not standard_mm_channel_name_pattern:
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                f":x: Erreur: Configuration Brevo ou du canal standard manquante pour l'entité {entity_key_found}.",
            )
            return

        target_brevo_list_name = brevo_list_pattern.format(base_name=base_name_found)
        brevo_list_obj = await asyncio.to_thread(self.brevo_client.get_list_by_name, target_brevo_list_name)

        if not brevo_list_obj or not brevo_list_obj.get("id"):
            await asyncio.to_thread(
                self.envoyer_message, channel_id, f":x: Erreur: Liste Brevo '{target_brevo_list_name}' non trouvée."
            )
            return

        brevo_list_id = brevo_list_obj["id"]

        # 3. Récupérer les contacts de la liste Brevo
        # Assuming get_contacts_from_list can fetch all contacts (might need pagination handling for very large lists)
        contacts_on_list = await asyncio.to_thread(self.brevo_client.get_contacts_from_list, brevo_list_id)

        if contacts_on_list is None:  # API error
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                f":x: Erreur lors de la récupération des contacts de la liste Brevo '{target_brevo_list_name}'.",
            )
            return

        to_contacts = [{"email": contact["email"]} for contact in contacts_on_list if contact.get("email")]

        if not to_contacts:
            await asyncio.to_thread(
                self.envoyer_message,
                channel_id,
                f":information_source: La liste Brevo '{target_brevo_list_name}' ne contient aucun contact avec une adresse email.",
            )
            return

        # 4. Envoyer l'email
        sender_email = self.config.BREVO_DEFAULT_SENDER_EMAIL
        sender_name = self.config.BREVO_DEFAULT_SENDER_NAME

        # Convert Markdown to HTML
        html_content = markdown2.markdown(text_content, extras=["break-on-newline"])

        email_sent_successfully = await asyncio.to_thread(
            self.brevo_client.send_transactional_email,
            subject,
            text_content,  # Original text content as fallback
            sender_email,
            sender_name,
            to_contacts,
            html_content=html_content,  # Pass HTML content
        )

        if email_sent_successfully:
            feedback_msg = f":white_check_mark: Email avec sujet '{subject}' envoyé (ou tentative d'envoi) à {len(to_contacts)} destinataires de la liste '{target_brevo_list_name}'."
        else:
            feedback_msg = (
                f":x: Échec de l'envoi de l'email avec sujet '{subject}' via Brevo. Vérifiez les logs du serveur."
            )

        await asyncio.to_thread(self.envoyer_message, channel_id, feedback_msg)

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
        # Add re.DOTALL to make . match newline characters
        mention_match = re.search(rf"(?i)(?:^|\s){escaped_mention}(?:\s+(.*)|$)", message_text, re.DOTALL)

        if not mention_match:
            return
        text_after_mention = mention_match.group(1)
        command_verb, arg_string = self._parse_command_from_mention(text_after_mention if text_after_mention else "")

        if command_verb:
            handler_method = self.commands.get(command_verb)
            if handler_method:
                # Pass user_id_who_posted to command handlers that need it
                # For lambdas, arguments must be positional if not explicitly defined with same name.
                if command_verb in [
                    "create_projet",
                    "create_antenne",
                    "create_pole",
                    "send_email",
                    "update_all_user_rights",  # Now expects user_id_who_posted
                    "update_user_rights_and_remove",  # Now expects user_id_who_posted
                ]:  # These handlers expect (channel_id, arg_string, user_id_who_posted)
                    await handler_method(channel_id, arg_string, user_id_who_posted)
                elif command_verb in ["help"]:  # help does not need user_id_who_posted
                    # These handlers are defined to accept (self, channel_id, arg_string)
                    await handler_method(channel_id, arg_string)
                # else: # No other command types currently defined that would fall here without specific handling
                #     # Fallback for any other command type if they were to be added without specific handling
                #     # await handler_method(channel_id, arg_string) # This would error for handlers expecting user_id
                #     # Consider a more robust dispatch or ensure all commands are explicitly handled
                #     logging.warning(f"Command '{command_verb}' called without specific user_id handling logic in _handle_message_event dispatcher.")
                #     # For safety, if a command isn't in the specific lists, we might avoid calling it or call it without user_id
                #     # This depends on the desired default behavior for unlisted commands.
                #     # For now, unlisted commands (if any were added to self.commands without updating here) would not be called.
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
