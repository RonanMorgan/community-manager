import logging
from typing import TYPE_CHECKING, Optional

import config
from app.enums import SyncStatus
from clients.brevo_client import BrevoAction
from .base import Service as SyncService
from .mattermost import _extract_base_name

if TYPE_CHECKING:
    from clients.brevo_client import BrevoClient


class BrevoService(SyncService):
    SERVICE_NAME = "BREVO"

    def _ensure_contacts_in_brevo_list(
        self,
        brevo_client: "BrevoClient",
        list_id: int,
        list_name: str,
        mm_users_to_ensure: list[dict],
        mm_channel_display_name_for_log: str,
    ) -> tuple[list[dict], set]:
        results = []
        targeted_emails = set()

        if not list_id:
            logging.error(f"No Brevo list ID provided to _ensure_contacts_in_brevo_list for list name {list_name}.")
            return results, targeted_emails

        for mm_user in mm_users_to_ensure:
            mm_username = mm_user.get("username", "UnknownUser")
            mm_user_email = mm_user.get("email")

            base_user_info = {
                "mm_username": mm_username,
                "mm_user_email": mm_user_email or "NoEmailProvided",
                "mm_channel_display_name": mm_channel_display_name_for_log,
                "target_resource_name": list_name,
                "service": "BREVO",
            }

            if mm_username in config.EXCLUDED_USERS:
                logging.debug(f"User '{mm_username}' is excluded. Skipping Brevo ensure for list '{list_name}'.")
                continue

            if not mm_user_email:
                results.append(
                    {
                        **base_user_info,
                        "status": SyncStatus.SKIPPED.value,
                        "action": "SKIPPED_NO_MM_EMAIL_FOR_BREVO_ENSURE",
                        "error_message": "User has no email in Mattermost for Brevo.",
                    }
                )
                continue

            targeted_emails.add(mm_user_email.lower())

            if brevo_client.add_contact_to_list(email=mm_user_email, list_id=list_id):
                results.append(
                    {
                        **base_user_info,
                        "status": SyncStatus.SUCCESS.value,
                        "action": BrevoAction.CONTACT_ADDED.value,
                    }
                )
            else:
                results.append(
                    {
                        **base_user_info,
                        "status": SyncStatus.FAILURE.value,
                        "action": BrevoAction.FAILED_TO_ENSURE_CONTACT.value,
                        "error_message": f"API call to add/ensure contact '{mm_user_email}' in Brevo list '{list_name}' failed.",
                    }
                )

        return results, targeted_emails

    def _sync_single_brevo_list(
        self,
        brevo_client: "BrevoClient",
        brevo_list_name: str,
        mm_users_in_channel: list[dict],
        mm_channel_display_name_for_log: str,
    ) -> list[dict]:
        results = []
        logging.info(
            f"Starting Brevo list sync for '{brevo_list_name}' based on MM channel '{mm_channel_display_name_for_log}'. "
        )

        if not brevo_client:
            logging.error("Brevo client not provided to _sync_single_brevo_list.")
            return results

        brevo_lists = brevo_client.get_lists(name=brevo_list_name)
        brevo_list_obj = brevo_lists[0] if brevo_lists else None
        if not brevo_list_obj:
            brevo_list_obj = brevo_client.create_list(brevo_list_name)
            if not brevo_list_obj:
                logging.error(
                    f"Failed to create or retrieve Brevo list '{brevo_list_name}'. Skipping sync for this list."
                )
                results.append(
                    {
                        "service": "BREVO",
                        "target_resource_name": brevo_list_name,
                        "status": SyncStatus.FAILURE.value,
                        "action": "FAILED_TO_ENSURE_BREVO_LIST",
                        "error_message": f"Could not create or find Brevo list '{brevo_list_name}'.",
                    }
                )
                return results

        brevo_list_id = brevo_list_obj["id"]
        logging.info(f"Ensured Brevo list '{brevo_list_name}' (ID: {brevo_list_id}) exists.")

        add_results, mm_targeted_emails = self._ensure_contacts_in_brevo_list(
            brevo_client,
            brevo_list_id,
            brevo_list_name,
            mm_users_in_channel,
            mm_channel_display_name_for_log,
        )
        results.extend(add_results)

        logging.info(f"Finished Brevo list sync for '{brevo_list_name}'. Total results: {len(results)}")
        return results

    def _map_brevo_list_to_entity_and_base_name(
        self, list_name: str, permissions_matrix: dict
    ) -> tuple[Optional[str], Optional[str]]:
        for entity_key, entity_cfg in permissions_matrix.items():
            brevo_cfg = entity_cfg.get("brevo")
            if brevo_cfg:
                pattern = brevo_cfg.get("list_name_pattern")
                if pattern:
                    base_name = _extract_base_name(list_name, pattern)
                    if base_name is not None:
                        return entity_key, base_name
        return None, None

    async def group_sync(
        self,
        base_name,
        entity_config,
        all_authentik_groups_by_name,
        email_to_authentik_user_pk_map,
        std_mm_users_in_channel,
        adm_mm_users_in_channel,
        mm_users_for_services,
        std_mm_channel_name_for_log,
        entity_key,
    ):
        brevo_client = self.client
        config = entity_config.get("brevo")
        if not config:
            return []
        std_mm_users = std_mm_users_in_channel
        log_channel_name = std_mm_channel_name_for_log
        brevo_list_name = config.get("list_name_pattern", "mm_{base_name}").format(base_name=base_name)
        return self._sync_single_brevo_list(brevo_client, brevo_list_name, std_mm_users, log_channel_name)

    async def differential_sync(self, mm_channel_members: dict):
        # Brevo sync is additive only, so no differential sync logic is needed.
        return []
