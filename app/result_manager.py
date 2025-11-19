import asyncio

from app.enums import SyncStatus
from clients.authentik_client import AuthentikAction
from clients.brevo_client import BrevoAction
from clients.nocodb_client import NocoDBAction
from clients.outline_client import OutlineAction
from clients.vaultwarden_client import VaultwardenAction


class ResultManager:
    def __init__(self, bot):
        self.bot = bot

    async def format_and_send_sync_results(
        self,
        channel_id: str,
        initial_post_id: str | None,
        detailed_results: list[dict],
        command_name: str = "synchronisation",
    ):
        """Helper function to format and send detailed synchronization results."""
        if not detailed_results:
            final_summary_message = f":information_source: Processus de {command_name} terminé, mais aucune opération utilisateur spécifique n'a été effectuée ou rapportée."
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                final_summary_message,
                thread_id=initial_post_id,
            )
            return

        total_success_ops = 0
        total_problem_ops = 0
        action_summary = {}

        for result in detailed_results:
            user_mm_name = result.get("mm_username", "Utilisateur inconnu")
            service_name = result.get("service", "ServiceInconnu").upper()
            target_resource = result.get("target_resource_name", "RessourceInconnue")
            action = result.get("action", "AUCUNE_ACTION")
            status = result.get("status", "ECHEC")
            error_msg = result.get("error_message")

            action_summary[action] = action_summary.get(action, 0) + 1

            icon = ":white_check_mark:" if status == SyncStatus.SUCCESS.value else ":x:"
            if status == SyncStatus.SKIPPED.value and action != "SKIPPED_NO_MM_EMAIL":
                icon = ":warning:"

            user_line = f"{icon} **Utilisateur :** `{user_mm_name}`"
            if result.get("mm_user_email") and result.get("mm_user_email") != "NoEmailProvided":
                user_line += f" ({result.get('mm_user_email')})"

            service_line = f"**Service :** `{service_name}`"
            resource_line = f"**Ressource :** `{target_resource}`"
            action_line = f"**Action :** `{action}`"
            message_parts = [user_line, service_line, resource_line, action_line]

            if status == SyncStatus.SUCCESS.value:
                total_success_ops += 1
                if action == AuthentikAction.USER_ADDED_TO_GROUP.value:
                    message_parts.append("Ajouté avec succès au groupe Authentik.")
                elif action == AuthentikAction.USER_ALREADY_IN_GROUP.value:
                    message_parts.append("Déjà membre du groupe Authentik.")
                elif action == AuthentikAction.USER_REMOVED_FROM_GROUP.value:
                    message_parts.append("Supprimé avec succès du groupe Authentik.")
                elif action in [
                    OutlineAction.USER_ADDED_TO_COLLECTION_WITH_READ_ACCESS_AND_DM_SENT.value,
                    OutlineAction.USER_ADDED_TO_COLLECTION_WITH_READ_WRITE_ACCESS_AND_DM_SENT.value,
                ]:
                    permission = "lecture" if "READ_ACCESS" in action else "lecture/écriture"
                    message_parts.append(f"Ajouté à la collection Outline (permission {permission}) et MP envoyé.")
                elif action in [
                    OutlineAction.USER_ADDED_TO_COLLECTION_WITH_READ_ACCESS_DM_FAILED.value,
                    OutlineAction.USER_ADDED_TO_COLLECTION_WITH_READ_WRITE_ACCESS_DM_FAILED.value,
                ]:
                    permission = "lecture" if "READ_ACCESS" in action else "lecture/écriture"
                    message_parts.append(
                        f"Ajouté à la collection Outline (permission {permission}), mais échec de l'envoi du MP."
                    )
                elif action == OutlineAction.USER_ALREADY_IN_COLLECTION_PERMISSION_ENSURED.value:
                    message_parts.append("Déjà membre de la collection Outline, permission assurée.")
                elif action == OutlineAction.USER_REMOVED_FROM_COLLECTION.value:
                    message_parts.append("Supprimé avec succès de la collection Outline.")
                elif action == NocoDBAction.USER_REMOVED_FROM_BASE.value:
                    message_parts.append("Supprimé avec succès de la base NoCoDB.")
                elif action in [a.value for a in NocoDBAction if "UPDATED_TO" in a.name]:
                    role = action.split("_UPDATED_TO_")[1]
                    message_parts.append(f"Rôle mis à jour avec succès à '{role.lower()}' dans la base NoCoDB.")
                elif action == NocoDBAction.USER_ALREADY_IN_BASE_WITH_CORRECT_ROLE.value:
                    message_parts.append("Déjà membre de la base NoCoDB avec le bon rôle.")
                elif "INVITED_AS" in action and "DM_SENT" in action:
                    role = action.split("_INVITED_AS_")[1].split("_AND_DM_SENT")[0]
                    message_parts.append(f"Invité avec succès à la base NoCoDB (rôle: {role.lower()}) et MP envoyé.")
                elif "INVITED_AS" in action and "DM_FAILED" in action:
                    role = action.split("_INVITED_AS_")[1].split("_DM_FAILED")[0]
                    message_parts.append(
                        f"Invité à la base NoCoDB (rôle: {role.lower()}), mais échec de l'envoi du MP."
                    )
                elif "INVITED_AS" in action:
                    role = action.split("_INVITED_AS_")[1]
                    message_parts.append(f"Invité avec succès à la base NoCoDB (rôle: {role.lower()}).")
                elif action == BrevoAction.CONTACT_ADDED.value:
                    message_parts.append("Contact ajouté/assuré dans la liste Brevo.")
                elif action == BrevoAction.CONTACT_REMOVED.value:
                    message_parts.append("Contact supprimé de la liste Brevo.")
                elif action == VaultwardenAction.USER_INVITED_TO_COLLECTION_AND_DM_SENT.value:
                    message_parts.append("Invité à la collection Vaultwarden et MP envoyé.")
                elif action == VaultwardenAction.USER_INVITED_TO_COLLECTION.value:
                    message_parts.append("Invité à la collection Vaultwarden.")
                elif action == VaultwardenAction.USER_REMOVED_FROM_COLLECTION.value:
                    message_parts.append("Supprimé de la collection Vaultwarden.")

            elif status == SyncStatus.SKIPPED.value:
                message_parts.append(f"Ignoré. Raison : {error_msg if error_msg else 'Non spécifiée'}")
                if action != "SKIPPED_NO_MM_EMAIL":
                    total_problem_ops += 1
            else:
                total_problem_ops += 1
                message_parts.append(f"ÉCHEC. Raison : {error_msg if error_msg else 'Non spécifiée'}")

            full_user_report_message = "\n".join(message_parts)
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                full_user_report_message,
                thread_id=initial_post_id,
            )

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
            summary_lines.insert(
                1,
                f":x: {command_name.capitalize()} terminée avec des problèmes/omissions.",
            )
        elif total_success_ops > 0:
            summary_lines.insert(1, f":rocket: {command_name.capitalize()} terminée avec succès.")
        else:
            summary_lines.insert(
                1,
                f":information_source: {command_name.capitalize()} terminée. Peu ou pas d'opérations significatives effectuées.",
            )

        final_summary_message = "\n".join(summary_lines)
        if final_summary_message:
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                final_summary_message,
                thread_id=initial_post_id,
            )
