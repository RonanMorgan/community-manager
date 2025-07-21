import asyncio
import logging

import markdown2

from .base_command import BaseCommand


class SendEmailCommand(BaseCommand):
    @property
    def command_name(self):
        return "send_email"

    async def execute(self, channel_id, arg_string, user_id_who_posted):
        """
        Envoie un email via Brevo aux membres du canal standard associé.
        Usage: @marty send_email <Sujet de l'email> /// <Contenu de l'email>
        Doit être lancé depuis un canal admin d'une entité (projet, pôle, antenne).
        """
        logging.info(f"'send_email' command received in channel {channel_id} by user {user_id_who_posted}.")

        if not self.bot.brevo_client:
            await asyncio.to_thread(
                self.bot.envoyer_message, channel_id, ":x: Erreur: Le client Brevo n'est pas configuré."
            )
            return
        if not self.bot.config.BREVO_DEFAULT_SENDER_EMAIL or not self.bot.config.BREVO_DEFAULT_SENDER_NAME:
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                ":x: Erreur: L'expéditeur par défaut (email/nom) n'est pas configuré pour Brevo.",
            )
            return
        if not self.bot.mattermost_api_client:
            await asyncio.to_thread(
                self.bot.envoyer_message, channel_id, ":x: Erreur: Le client Mattermost API n'est pas configuré."
            )
            return

        if not arg_string or "///" not in arg_string:
            usage_msg = "Usage: `@marty send_email <Sujet de l'email> /// <Contenu de l'email>`"
            await asyncio.to_thread(self.bot.envoyer_message, channel_id, f":warning: Syntaxe incorrecte. {usage_msg}")
            return

        subject, text_content = [part.strip() for part in arg_string.split("///", 1)]

        if not subject or not text_content:
            usage_msg = "Usage: `@marty send_email <Sujet de l'email> /// <Contenu de l'email>`"
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                f":warning: Le sujet et le contenu ne peuvent pas être vides. {usage_msg}",
            )
            return

        # 1. Vérifier que la commande est lancée depuis un canal admin et identifier l'entité
        current_channel_info = await asyncio.to_thread(
            self.bot.mattermost_api_client.get_channel_by_id, channel_id
        )  # Corrected method call
        if not current_channel_info:
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                ":x: Erreur: Impossible de récupérer les informations du canal actuel.",
            )
            return

        # Check if user is a member of the current (admin) channel
        channel_members = await asyncio.to_thread(
            self.bot.mattermost_api_client.get_users_in_channel, channel_id
        )  # Corrected method
        if not any(
            member.get("id") == user_id_who_posted for member in channel_members
        ):  # Changed "user_id" to "id" and added .get()
            logging.warning(
                f"User {user_id_who_posted} tried to use send_email from channel {channel_id} but is not a member."
            )
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                ":x: Erreur: Vous devez être membre de ce canal admin pour utiliser cette commande.",
            )
            return

        entity_key_found = None
        base_name_found = None
        admin_channel_name_slug = current_channel_info.get("name")

        from libraries.group_sync_services import (  # For slugify if needed by map
            _map_mm_channel_to_entity_and_base_name,
            slugify,
        )

        # We need to iterate through PERMISSIONS_MATRIX to find which entity this admin channel belongs to
        # This is a bit reversed from the usual mapping.
        for e_key, e_conf in self.bot.config.PERMISSIONS_MATRIX.items():
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
                self.bot.envoyer_message,
                channel_id,
                ":x: Erreur: Cette commande doit être lancée depuis un canal admin d'une entité configurée (projet, pôle, antenne).",
            )
            return

        logging.info(
            f"Command 'send_email' validated for entity '{base_name_found}' (type: {entity_key_found}) from admin channel '{current_channel_info.get('display_name')}'."
        )

        # 2. Récupérer la liste Brevo du canal standard
        entity_permissions = self.bot.config.PERMISSIONS_MATRIX.get(entity_key_found, {})
        brevo_config = entity_permissions.get("brevo", {})
        brevo_list_pattern = brevo_config.get("list_name_pattern")
        standard_channel_config = entity_permissions.get("standard", {})
        standard_mm_channel_name_pattern = standard_channel_config.get("mattermost_channel_name_pattern")

        if not brevo_list_pattern or not standard_mm_channel_name_pattern:
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                f":x: Erreur: Configuration Brevo ou du canal standard manquante pour l'entité {entity_key_found}.",
            )
            return

        target_brevo_list_name = brevo_list_pattern.format(base_name=base_name_found)
        brevo_list_obj = await asyncio.to_thread(self.bot.brevo_client.get_list_by_name, target_brevo_list_name)

        if not brevo_list_obj or not brevo_list_obj.get("id"):
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                f":x: Erreur: Liste Brevo '{target_brevo_list_name}' non trouvée.",
            )
            return

        brevo_list_id = brevo_list_obj["id"]

        # 3. Récupérer les contacts de la liste Brevo
        # Assuming get_contacts_from_list can fetch all contacts (might need pagination handling for very large lists)
        contacts_on_list = await asyncio.to_thread(self.bot.brevo_client.get_contacts_from_list, brevo_list_id)

        if contacts_on_list is None:  # API error
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                f":x: Erreur lors de la récupération des contacts de la liste Brevo '{target_brevo_list_name}'.",
            )
            return

        to_contacts = [{"email": contact["email"]} for contact in contacts_on_list if contact.get("email")]

        if not to_contacts:
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                f":information_source: La liste Brevo '{target_brevo_list_name}' ne contient aucun contact avec une adresse email.",
            )
            return

        # 4. Envoyer l'email
        sender_email = self.bot.config.BREVO_DEFAULT_SENDER_EMAIL
        sender_name = self.bot.config.BREVO_DEFAULT_SENDER_NAME

        # Convert Markdown to HTML
        html_content = markdown2.markdown(text_content, extras=["break-on-newline"])

        email_sent_successfully = await asyncio.to_thread(
            self.bot.brevo_client.send_transactional_email,
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

        await asyncio.to_thread(self.bot.envoyer_message, channel_id, feedback_msg)

    @staticmethod
    def get_help():
        return "Envoie un email via Brevo aux membres du canal standard associé."
