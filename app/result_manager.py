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
        """Formats and sends synchronization results, grouped by service and resource."""
        if not detailed_results:
            final_summary_message = f":information_source: Processus de {command_name} terminé, mais aucune opération utilisateur spécifique n'a été effectuée ou rapportée."
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                final_summary_message,
                thread_id=initial_post_id,
            )
            return

        # Group results by service and target resource
        grouped_results = {}
        for result in detailed_results:
            service_name = result.get("service", "ServiceInconnu").upper()
            target_resource = result.get("target_resource_name", "RessourceInconnue")
            group_key = (service_name, target_resource)
            if group_key not in grouped_results:
                grouped_results[group_key] = []
            grouped_results[group_key].append(result)

        total_success_ops = 0
        total_problem_ops = 0
        action_summary = {}

        # Process each group and send a consolidated message
        for (service_name, target_resource), results in grouped_results.items():
            message_parts = [f"### Rapport pour `{service_name}` sur `{target_resource}`"]
            action_counts = {}

            for result in results:
                action = result.get("action", "AUCUNE_ACTION")
                status = result.get("status", SyncStatus.FAILURE.value)

                # Update global summary stats
                action_summary[action] = action_summary.get(action, 0) + 1
                if status == SyncStatus.SUCCESS.value:
                    total_success_ops += 1
                elif status == SyncStatus.FAILURE.value:
                    total_problem_ops += 1
                elif status == SyncStatus.SKIPPED.value and action != "SKIPPED_NO_MM_EMAIL":
                    total_problem_ops += 1

                # Group users by action and status for this specific resource message
                status_key = (action, status)
                if status_key not in action_counts:
                    action_counts[status_key] = {"users": [], "errors": set()}
                action_counts[status_key]["users"].append(result.get("mm_username", "Inconnu"))
                if status != SyncStatus.SUCCESS.value and result.get("error_message"):
                    action_counts[status_key]["errors"].add(result.get("error_message"))

            # Format the message for this resource
            for (action, status), data in sorted(action_counts.items()):
                users = sorted(list(set(data["users"])))  # Unique users
                user_list_str = ", ".join(f"`{u}`" for u in users)
                icon = {
                    SyncStatus.SUCCESS.value: ":white_check_mark:",
                    SyncStatus.FAILURE.value: ":x:",
                    SyncStatus.SKIPPED.value: ":warning:",
                }.get(status, ":question:")

                message_parts.append(f"**Action : `{action}`**")
                message_parts.append(f"- {icon} **Statut :** {status}")
                message_parts.append(f"- **Utilisateurs ({len(users)}) :** {user_list_str}")
                if data["errors"]:
                    error_list_str = "\n".join(f"  - `{e}`" for e in data["errors"])
                    message_parts.append(f"- **Erreurs/Raisons :**\n{error_list_str}")

            # Send the consolidated message for this service/resource
            full_report_message = "\n".join(message_parts)
            await asyncio.to_thread(
                self.bot.envoyer_message,
                channel_id,
                full_report_message,
                thread_id=initial_post_id,
            )

        # Final summary message (as before)
        summary_lines = [f"### :checkered_flag: Résumé global de la {command_name} :"]
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
