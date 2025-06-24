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
            "create_group": self._handle_create_group_command,
            "help": self._send_help_message,
            "sync_user_channels": self._handle_sync_user_channels_command,  # New command
        }

    async def _handle_sync_user_channels_command(self, channel_id, arg_string=None):  # arg_string is unused for now
        """Triggers the synchronization of Mattermost channel users to Authentik groups."""
        # FR: Déclenche la synchronisation des utilisateurs des canaux Mattermost vers les groupes Authentik.
        logging.info(f"'{self.bot_name_mention} sync_user_channels' command received in channel {channel_id}.")

        # Send initial acknowledgement message and get its ID for threading
        initial_message_text = ":hourglass_flowing_sand: Démarrage de la synchronisation des utilisateurs des canaux Mattermost vers les groupes Authentik et collections Outline... Ceci peut prendre un moment."
        initial_post_id = await asyncio.to_thread(self.envoyer_message, channel_id, initial_message_text)

        # Check if necessary clients for core functionality are available
        if not self.authentik_client or not self.mattermost_api_client or not self.config.MATTERMOST_TEAM_ID:
            error_msg = ":warning: **Erreur :** Le bot n'est pas correctement configuré pour la synchronisation. Client Authentik, client API Mattermost, ou ID d'équipe Mattermost manquant. Veuillez vérifier les logs du serveur."
            logging.error(
                "Bot is not properly configured for sync (core components): Missing Authentik client, Mattermost API client, or Mattermost Team ID."
            )
            await asyncio.to_thread(self.envoyer_message, channel_id, error_msg, thread_id=initial_post_id)
            return

        # Outline client is optional, its absence is handled by the orchestrator.
        # We log here if it's not configured, for bot admin awareness.
        if not self.outline_client:
            logging.info("Outline client not configured on this bot instance. Outline sync will be skipped.")
            # Optionally send a message to Mattermost? For now, just server log.

        try:
            logging.info("Dispatching group synchronization task to a thread...")
            orchestration_success, detailed_results = await asyncio.to_thread(
                orchestrate_group_synchronization,  # Updated function name
                self.authentik_client,
                self.mattermost_api_client,
                self.outline_client,  # Pass outline_client (can be None)
                self.config.MATTERMOST_TEAM_ID,
            )

            final_summary_message = ""
            if not orchestration_success:
                logging.warning("Group synchronization task reported critical failure during orchestration.")
                final_summary_message = ":x: La synchronisation des groupes a échoué de manière critique durant l'orchestration. Veuillez consulter les logs du serveur pour plus de détails."
            else:
                logging.info(
                    f"Group synchronization task orchestration completed. Detailed results count: {len(detailed_results)}"
                )
                if not detailed_results:
                    final_summary_message = ":information_source: Processus de synchronisation terminé, mais aucune opération utilisateur spécifique n'a été effectuée ou rapportée."
                else:
                    total_success_ops = 0
                    total_problem_ops = 0  # Failures or critical skips

                    for result in detailed_results:
                        user_mm_name = result.get("mm_username", "Utilisateur inconnu")
                        service_name = result.get("service", "ServiceInconnu").upper()
                        target_resource = result.get("target_resource_name", "RessourceInconnue")
                        action = result.get("action", "AUCUNE_ACTION")
                        status = result.get("status", "ECHEC")
                        error_msg = result.get("error_message")

                        icon = ":white_check_mark:" if status == "SUCCESS" else ":x:"
                        if status == "SKIPPED" and action != "SKIPPED_NO_MM_EMAIL":
                            icon = ":warning:"

                        user_line = f"{icon} **Utilisateur :** `{user_mm_name}`"
                        if result.get("mm_user_email") and result.get("mm_user_email") != "NoEmailProvided":
                            user_line += f" ({result.get('mm_user_email')})"

                        service_line = "**Service :** `{}`".format(service_name)
                        resource_line = "**Ressource :** `{}`".format(target_resource)
                        action_line = "**Action :** `{}`".format(action)

                        message_parts = [user_line, service_line, resource_line, action_line]

                        if status == "SUCCESS":
                            total_success_ops += 1
                            if action == "USER_ADDED_TO_AUTHENTIK_GROUP":
                                message_parts.append(f"Ajouté avec succès au groupe Authentik.")
                            elif action == "USER_ALREADY_IN_AUTHENTIK_GROUP":
                                message_parts.append(f"Déjà membre du groupe Authentik.")
                            elif action == "USER_ADDED_TO_OUTLINE_COLLECTION_AND_DM_SENT":
                                message_parts.append(f"Ajouté à la collection Outline et MP envoyé.")
                            elif action == "USER_ADDED_TO_OUTLINE_COLLECTION_DM_FAILED":
                                message_parts.append(f"Ajouté à la collection Outline, mais échec de l'envoi du MP.")
                            elif action == "USER_ALREADY_IN_OUTLINE_COLLECTION":
                                message_parts.append(f"Déjà membre de la collection Outline.")
                            elif action == "USER_MEMBERSHIP_ENSURED_IN_OUTLINE_COLLECTION": # Generic, might be replaced by more specific ones
                                message_parts.append(f"Appartenance assurée à la collection Outline.")
                        elif status == "SKIPPED":
                            message_parts.append(f"Ignoré. Raison : {error_msg if error_msg else 'Non spécifiée'}")
                            if action != "SKIPPED_NO_MM_EMAIL":
                                total_problem_ops += 1
                        else:  # FAILURE
                            total_problem_ops += 1
                            message_parts.append(f"ÉCHEC. Raison : {error_msg if error_msg else 'Non spécifiée'}")

                        full_user_report_message = "\n".join(message_parts)
                        await asyncio.to_thread(
                            self.envoyer_message, channel_id, full_user_report_message, thread_id=initial_post_id
                        )

                    # Constructing the final summary message
                    if total_problem_ops > 0 and total_success_ops > 0:
                        final_summary_message = f":warning: Synchronisation partiellement terminée. {total_success_ops} opérations réussies, {total_problem_ops} problèmes/omissions nécessitant attention. Voir détails ci-dessus."
                    elif total_problem_ops > 0:
                        final_summary_message = f":x: Synchronisation terminée avec {total_problem_ops} problèmes/omissions nécessitant attention. Voir détails ci-dessus."
                    elif total_success_ops > 0:
                        final_summary_message = f":rocket: Synchronisation terminée avec succès avec {total_success_ops} opérations. Voir détails ci-dessus."
                    else:
                        final_summary_message = ":white_check_mark: Processus de synchronisation terminé. Aucune nouvelle appartenance créée ou problème critique détecté. Vérifiez les détails pour les omissions ou appartenances existantes."

            if final_summary_message:
                await asyncio.to_thread(
                    self.envoyer_message, channel_id, final_summary_message, thread_id=initial_post_id
                )

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
            # loop.call_soon_threadsafe might be needed if signal handler is not in loop's thread
            # but loop.add_signal_handler usually runs callback in loop's thread.
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

    async def _send_help_message(self, channel_id, arg_string=None):
        """Displays this help message listing all available commands."""
        # FR: Affiche ce message d'aide listant toutes les commandes disponibles.
        help_lines = ["### Commandes disponibles pour MartyBot", "---"]
        if not self.commands:
            help_lines.append("Aucune commande n'est actuellement disponible.")
        else:
            for cmd, handler_method in self.commands.items():
                docstring = handler_method.__doc__
                description = ""
                if docstring:
                    # Assuming docstrings might remain in English or be simple enough not to need immediate translation in help text
                    first_line = docstring.strip().split("\n")[0]
                    description = f" - _{first_line}_"
                help_lines.append(f"* **`{cmd}`**{description}")
        help_lines.append("\n---")
        help_lines.append(
            f"**Exemple `create_group` :** `{self.bot_name_mention} create_group ProjetAlpha ProjetBeta` - Crée les ressources pour 'ProjetAlpha' et 'ProjetBeta'."
        )
        help_lines.append(
            f"\n**Note :** La commande `{self.bot_name_mention} sync_user_channels` peut prendre un certain temps pour s'exécuter."
        )
        help_lines.append(f"\nMentionnez-moi avec une commande, comme `{self.bot_name_mention} help`.")
        help_text = "\n".join(help_lines)
        await asyncio.to_thread(self.envoyer_message, channel_id, help_text)

    async def _handle_create_group_command(self, channel_id, project_names_str):
        """Creates all necessary group resources for one or more new projects."""
        # FR: Crée toutes les ressources de groupe nécessaires pour un ou plusieurs nouveaux projets.
        if not project_names_str:
            message = f":warning: **Erreur :** Au moins un nom de projet est requis. Utilisation : `{self.bot_name_mention} create_group <nomDuProjet1> [nomDuProjet2 ...]`"
            await asyncio.to_thread(self.envoyer_message, channel_id, message)
            return

        project_names = project_names_str.split()
        num_projects = len(project_names)
        processing_message = (
            f":hourglass_flowing_sand: Traitement de 'create_group' pour {num_projects} projet(s) : "
            f"**`{'`, `'.join(project_names)}`**..."
        )
        await asyncio.to_thread(self.envoyer_message, channel_id, processing_message)

        overall_summary_messages = []
        any_project_had_all_success = False
        any_project_had_partial_success = False
        any_project_had_total_failure = False
        all_projects_no_services_configured = True


        for project_name in project_names:
            project_specific_results = [f"--- Résumé pour le projet **`{project_name}`** ---"]
            attempted_ops_for_project = 0
            succeeded_ops_for_project = 0

            # Authentik
            auth_configured = bool(self.authentik_client)
            auth_success = False
            auth_message = "non configuré"
            if auth_configured:
                all_projects_no_services_configured = False
                attempted_ops_for_project += 1
                try:
                    auth_success = self.authentik_client.create_group(project_name)
                    if auth_success:
                        succeeded_ops_for_project += 1
                        auth_message = "groupe Authentik créé avec succès."
                    else:
                        # client.create_group returns False on failure, including if it already exists and logs it.
                        # We rely on the client's logging for "already exists" for now.
                        auth_message = "échec de la création du groupe Authentik (ou existe déjà, voir logs)."
                except Exception as e:
                    logging.error(f"Exception creating Authentik group for {project_name}: {e}", exc_info=True)
                    auth_message = f"erreur lors de la création du groupe Authentik : {e}"
            project_specific_results.append(
                f"{':white_check_mark:' if auth_success else (':warning:' if auth_configured and not auth_success else ':x:')} Authentik : {auth_message}"
            )


            # Outline
            outline_configured = bool(self.outline_client)
            outline_success = False
            outline_message = "non configuré"
            if outline_configured:
                all_projects_no_services_configured = False
                attempted_ops_for_project += 1
                try:
                    outline_success = self.outline_client.create_group(project_name)
                    if outline_success:
                        succeeded_ops_for_project += 1
                        outline_message = "collection Outline créée avec succès."
                    else:
                        outline_message = "échec de la création de la collection Outline (ou existe déjà, voir logs)."
                except Exception as e:
                    logging.error(f"Exception creating Outline collection for {project_name}: {e}", exc_info=True)
                    outline_message = f"erreur lors de la création de la collection Outline : {e}"
            project_specific_results.append(
                f"{':white_check_mark:' if outline_success else (':warning:' if outline_configured and not outline_success else ':x:')} Outline : {outline_message}"
            )

            # Mattermost
            mm_configured = bool(self.mattermost_api_client)
            mm_success = False
            mm_message = "non configuré"
            if mm_configured:
                all_projects_no_services_configured = False
                attempted_ops_for_project += 1
                try:
                    mm_success = self.mattermost_api_client.create_channel(project_name)
                    if mm_success:
                        succeeded_ops_for_project += 1
                        mm_message = "canal Mattermost créé avec succès."
                    else:
                        mm_message = "échec de la création du canal Mattermost (ou existe déjà, voir logs)."
                except Exception as e:
                    logging.error(f"Exception creating Mattermost channel for {project_name}: {e}", exc_info=True)
                    mm_message = f"erreur lors de la création du canal Mattermost : {e}"
            project_specific_results.append(
                f"{':white_check_mark:' if mm_success else (':warning:' if mm_configured and not mm_success else ':x:')} Mattermost : {mm_message}"
            )

            # Determine status for this specific project
            if attempted_ops_for_project == 0 : # Should not happen if all_projects_no_services_configured is false
                project_specific_results.append(f":information_source: Aucun service actif n'a été tenté pour ce projet.")
            elif succeeded_ops_for_project == attempted_ops_for_project:
                project_specific_results.insert(1, f":rocket: Toutes les ressources demandées pour **`{project_name}`** ont été traitées avec succès (ou existaient déjà).")
                any_project_had_all_success = True
            elif succeeded_ops_for_project > 0:
                project_specific_results.insert(1, f":warning: Création partiellement terminée pour **`{project_name}`**.")
                any_project_had_partial_success = True
            else: # 0 succeeded_ops_for_project but attempted_ops_for_project > 0
                project_specific_results.insert(1, f":boom: Échec de la création de toutes les ressources demandées pour **`{project_name}`**.")
                any_project_had_total_failure = True

            overall_summary_messages.extend(project_specific_results)

        # Final summary message for all projects
        final_response_header = ""
        if all_projects_no_services_configured and num_projects > 0 :
            final_response_header = f":information_source: Aucun service (Authentik, Outline, Mattermost) n'est configuré pour la commande 'create_group'. Veuillez vérifier la configuration du bot."
        elif num_projects == 1: # Single project, reuse specific project header logic more directly
            # The individual project messages already provide good detail.
            # We can use the flags set to make a concise header.
            if any_project_had_all_success :
                 final_response_header = f":heavy_check_mark: Traitement de 'create_group' pour **`{project_names[0]}`** terminé."
            elif any_project_had_partial_success:
                 final_response_header = f":warning: Traitement de 'create_group' pour **`{project_names[0]}`** terminé avec des avertissements."
            elif any_project_had_total_failure:
                 final_response_header = f":x: Traitement de 'create_group' pour **`{project_names[0]}`** terminé avec des échecs."
            # else: # Should be covered by all_projects_no_services_configured
            #    final_response_header = f"Traitement de 'create_group' pour **`{project_names[0]}`** : " # Generic if somehow missed
        elif num_projects > 1 :
            if any_project_had_all_success and not any_project_had_partial_success and not any_project_had_total_failure:
                final_response_header = f":rocket: Tous les projets ont été traités avec succès !"
            elif any_project_had_total_failure and not any_project_had_partial_success and not any_project_had_all_success:
                final_response_header = f":boom: Échec complet pour tous les projets."
            else: # Mix of success, partial, failure
                final_response_header = f":information_source: Traitement de 'create_group' pour {num_projects} projets terminé. Voir détails ci-dessous :"

        if all_projects_no_services_configured and num_projects > 0:
            # If no services are configured at all, the header is sufficient.
            final_response_message = final_response_header
        else:
            # Otherwise, append the detailed summary for each project.
            final_response_message = f"{final_response_header}\n" + "\n".join(overall_summary_messages)

        await asyncio.to_thread(self.envoyer_message, channel_id, final_response_message)

    async def _handle_message_event(self, message_data):
        post_info = message_data.get("data", {}).get("post")
        if not post_info:
            logging.warning("No post data in 'posted' event.")
            return
        post_data = json.loads(post_info)
        message_text = post_data.get("message", "")
        channel_id = post_data.get("channel_id")

        escaped_mention = re.escape(self.bot_name_mention)
        mention_match = re.search(rf"(?i)(?:^|\s){escaped_mention}(?:\s+(.*)|$)", message_text)

        if not mention_match:
            return
        text_after_mention = mention_match.group(1)
        command_verb, arg_string = self._parse_command_from_mention(text_after_mention if text_after_mention else "")

        if command_verb:
            handler_method = self.commands.get(command_verb)
            if handler_method:
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
            logging.warning(
                "One or more API clients are not initialized. Bot may have limited functionality."
            )  # Changed to warning

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
                    ping_interval=60,  # From user's working example
                    ping_timeout=30,  # From user's working example
                    # extra_headers argument removed
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
            # Signal handlers removed as per subtask requirement
            # for sig in (signal.SIGINT, signal.SIGTERM):
            #     try:
            #         loop.add_signal_handler(sig, self._request_shutdown)
            #         logging.info(f"Signal handler for {sig.name} set.")
            #     except NotImplementedError:
            #         logging.warning(f"Signal handler for {sig.name} could not be set on this OS/loop policy (NotImplementedError).")
            #     except Exception as e:
            #         logging.error(f"Error setting signal handler for {sig.name}: {e}")

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
