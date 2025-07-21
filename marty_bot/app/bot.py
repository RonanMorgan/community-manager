import websockets

print("<<<<<<<<<< SCRIPT EXECUTED >>>>>>>>>>")
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
from clients.client_factory import create_clients
# Import orchestration function for sync command
from libraries.group_sync_services import orchestrate_group_synchronization
from app.commands.command_factory import CommandFactory


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

        clients = create_clients()
        self.authentik_client = clients.get("authentik")
        self.outline_client = clients.get("outline")
        self.mattermost_api_client = clients.get("mattermost")
        self.brevo_client = clients.get("brevo")
        self.nocodb_client = clients.get("nocodb")
        self.vaultwarden_client = clients.get("vaultwarden")

        self.websocket = None  # Represents the active WebSocket connection object

        # For graceful shutdown
        self.shutdown_event = asyncio.Event()

        # Reconnection parameters
        self.MAX_RECONNECT_ATTEMPTS = 5
        self.INITIAL_RECONNECT_DELAY = 5  # seconds
        self.MAX_RECONNECT_DELAY = 60  # seconds

        self.command_factory = CommandFactory(self)
        self.orchestrate_group_synchronization = orchestrate_group_synchronization

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
                elif action == "NOCODB_USER_REMOVED_FROM_BASE":
                    message_parts.append("Supprimé avec succès de la base NoCoDB.")
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
            command = self.command_factory.get_command(command_verb)
            if command:
                await command.execute(channel_id, arg_string, user_id_who_posted)
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
