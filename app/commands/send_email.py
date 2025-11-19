import asyncio
import logging

import markdown2

from .base_command import BaseCommand


class SendEmailCommand(BaseCommand):
    @property
    def command_name(self):
        return "send_email"

    async def check_user_right(self, user_id: str, channel_id: str) -> bool:
        if not await self.user_right_manager.is_channel_admin(user_id, channel_id):
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                ":x: Erreur: Cette commande doit être lancée depuis un canal admin d'une entité configurée (projet, pôle, antenne).",
            )
            return False
        return True

    async def _execute(self, channel_id, arg_string, user_id_who_posted):
        """
        Envoie un email via Brevo aux membres du canal standard associé.
        Usage: @marty send_email <Sujet de l'email> /// <Contenu de l'email>
        Doit être lancé depuis un canal admin d'une entité (projet, pôle, antenne).
        """
        logging.info(f"'send_email' command received in channel {channel_id} by user {user_id_who_posted}.")

        if not self.bot.brevo_client:
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                ":x: Erreur: Le client Brevo n'est pas configuré.",
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
                self.bot.envoyer_message,
                channel_id,
                ":x: Erreur: Le client Mattermost API n'est pas configuré.",
            )
            return

        if not arg_string or "///" not in arg_string:
            usage_msg = "Usage: `@marty send_email <Sujet de l'email> /// <Contenu de l'email>`"
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                f":warning: Syntaxe incorrecte. {usage_msg}",
            )
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

        current_channel_info = await asyncio.to_thread(self.bot.mattermost_api_client.get_channel_by_id, channel_id)
        from libraries.group_sync_services import (
            _map_mm_channel_to_entity_and_base_name,
        )

        entity_key_found, base_name_found, _ = _map_mm_channel_to_entity_and_base_name(
            current_channel_info.get("name"),
            current_channel_info.get("display_name"),
            self.bot.config.PERMISSIONS_MATRIX,
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
