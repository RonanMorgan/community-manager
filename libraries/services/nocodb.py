import logging
from typing import TYPE_CHECKING, Optional

import config
from app.enums import SyncStatus
from clients.nocodb_client import NocoDBAction
from .base import Service as SyncService
from .mattermost import _extract_base_name

if TYPE_CHECKING:
    from clients.mattermost_client import MattermostClient
    from clients.nocodb_client import NocoDBClient


class NocoDBService(SyncService):
    SERVICE_NAME = "NOCODB"

    def _sync_single_nocodb_base(
        self,
        nocodb_client: "NocoDBClient",
        mattermost_client: "MattermostClient",
        base_title_pattern: str,
        entity_base_name: str,
        mm_users_for_permission: dict,
        default_permission: str,
        admin_permission: str,
        mm_channel_context_name: str,
    ) -> list[dict]:
        results = []
        nocodb_base_title = base_title_pattern.format(base_name=entity_base_name)
        logging.debug(f"Starting NoCoDB base sync for '{nocodb_base_title}'.")

        nocodb_base_obj = nocodb_client.get_base_by_title(nocodb_base_title)
        if not nocodb_base_obj or not nocodb_base_obj.get("id"):
            logging.warning(
                f"NoCoDB base '{nocodb_base_title}' not found. Skipping sync. It should be created by 'create_antenne/pole' command."
            )
            return [
                {
                    "service": "NOCODB",
                    "target_resource_name": nocodb_base_title,
                    "status": SyncStatus.SKIPPED.value,
                    "action": "SKIPPED_NOCODB_BASE_NOT_FOUND",
                    "error_message": f"Base '{nocodb_base_title}' not found in NoCoDB.",
                }
            ]

        base_id = nocodb_base_obj["id"]
        current_nocodb_users_list = nocodb_client.list_base_users(base_id)
        current_nocodb_users_map = {
            user.get("email", "").lower(): user for user in current_nocodb_users_list if user.get("email")
        }
        target_nocodb_user_emails = set()

        for email_l, mm_user_d in mm_users_for_permission.items():
            if mm_user_d.get("username") in config.EXCLUDED_USERS:
                if email_l in current_nocodb_users_map:
                    target_nocodb_user_emails.add(email_l)
                    logging.debug(
                        f"User '{mm_user_d.get('username')}' ({email_l}) is excluded and already in NoCoDB base '{nocodb_base_title}'. Will be preserved."
                    )

        add_update_results, mm_targeted_emails = self._ensure_users_in_nocodb_base(
            nocodb_client=nocodb_client,
            mattermost_client=mattermost_client,
            base_id=base_id,
            base_title=nocodb_base_title,
            mm_users_for_permission=mm_users_for_permission,
            default_permission=default_permission,
            admin_permission=admin_permission,
            current_nocodb_users_map=current_nocodb_users_map,
            mm_channel_context_name=mm_channel_context_name,
        )
        results.extend(add_update_results)
        target_nocodb_user_emails.update(mm_targeted_emails)

        logging.debug(f"Finished NoCoDB base sync for '{nocodb_base_title}'. Total results: {len(results)}")
        return results

    def _ensure_users_in_nocodb_base(
        self,
        nocodb_client: "NocoDBClient",
        mattermost_client: "MattermostClient",
        base_id: str,
        base_title: str,
        mm_users_for_permission: dict,
        default_permission: str,
        admin_permission: str,
        current_nocodb_users_map: dict,
        mm_channel_context_name: str,
    ) -> tuple[list[dict], set]:
        results = []
        targeted_emails_in_base = set()

        if not base_id:
            logging.error(f"No NoCoDB base ID provided to _ensure_users_in_nocodb_base for base title {base_title}.")
            return results, targeted_emails_in_base

        for email_lower, mm_user_data in mm_users_for_permission.items():
            mm_username = mm_user_data["username"]

            base_user_info = {
                "mm_username": mm_username,
                "mm_user_email": email_lower,
                "mm_channel_display_name": mm_channel_context_name,
                "target_resource_name": base_title,
                "service": "NOCODB",
            }
            nocodb_result = {
                **base_user_info,
                "status": "FAILURE",
                "action": "NOCODB_USER_UNCHANGED",
            }

            if mm_username in config.EXCLUDED_USERS:
                logging.debug(f"User '{mm_username}' is excluded. Skipping NoCoDB ensure for base '{base_title}'.")
                continue

            targeted_emails_in_base.add(email_lower)
            target_role = admin_permission if mm_user_data["is_admin_channel_member"] else default_permission
            existing_nocodb_user = current_nocodb_users_map.get(email_lower)

            if existing_nocodb_user:
                nocodb_user_id = existing_nocodb_user["id"]
                current_role = existing_nocodb_user.get("roles")
                if current_role != target_role:
                    if nocodb_client.update_base_user(base_id, nocodb_user_id, target_role):
                        nocodb_result.update(
                            {
                                "status": SyncStatus.SUCCESS.value,
                                "action": f"NOCODB_USER_ROLE_UPDATED_TO_{target_role.upper()}",
                            }
                        )
                    else:
                        nocodb_result.update(
                            {
                                "action": "FAILED_TO_UPDATE_NOCODB_USER_ROLE",
                                "error_message": "API call to update user role failed.",
                            }
                        )
                else:
                    nocodb_result.update(
                        {
                            "status": SyncStatus.SUCCESS.value,
                            "action": "NOCODB_USER_ALREADY_IN_BASE_WITH_CORRECT_ROLE",
                        }
                    )
            else:
                action_verb = f"NOCODB_USER_INVITED_AS_{target_role.upper()}"
                if nocodb_client.invite_user_to_base(base_id, email_lower, target_role):
                    nocodb_result.update({"status": SyncStatus.SUCCESS.value, "action": action_verb})
                    if mm_user_data.get("mm_user_id") and config.NOCODB_URL:
                        nocodb_base_link = f"{config.NOCODB_URL.rstrip('/')}/#/nc/{base_id}/dashboard"
                        dm_text = (
                            f"Bonjour @{mm_username}, vous avez été invité(e) à la base NoCoDb "
                            f"**{base_title}** (rôle: {target_role}).\n"
                            f"Vous pouvez y accéder ici : {nocodb_base_link}"
                        )
                        if mattermost_client.send_dm(mm_user_data["mm_user_id"], dm_text):
                            nocodb_result["action"] = f"{action_verb}_AND_DM_SENT"
                        else:
                            nocodb_result["action"] = f"{action_verb}_DM_FAILED"
                    elif not config.NOCODB_URL:
                        logging.warning(
                            f"NOCODB_URL not configured. Cannot send DM for NoCoDB invite to {mm_username} for base {base_title}."
                        )
                        nocodb_result["action"] = f"{action_verb}_DM_SKIPPED_NO_URL"
                else:
                    nocodb_result.update(
                        {
                            "action": "FAILED_TO_INVITE_NOCODB_USER",
                            "error_message": "API call to invite user failed.",
                        }
                    )

            results.append(nocodb_result)

        return results, targeted_emails_in_base

    def _remove_user_from_nocodb_base(
        self,
        nocodb_client: "NocoDBClient",
        base_id: str,
        base_title: str,
        user_id: str,
        user_email: str,
        mm_channel_context_name: str,
    ) -> dict:
        """Removes a user from a NocoDB base and returns a result dictionary."""
        result = {
            "service": "NOCODB",
            "target_resource_name": base_title,
            "mm_user_email": user_email,
            "mm_channel_display_name": mm_channel_context_name,
            "status": SyncStatus.FAILURE.value,
            "action": "FAILED_TO_REMOVE_NOCODB_USER",
        }
        if nocodb_client.delete_base_user(base_id, user_id):
            result["status"] = SyncStatus.SUCCESS.value
            result["action"] = NocoDBAction.USER_REMOVED_FROM_BASE.value
        else:
            result["error_message"] = "API call to remove user from NoCoDB base failed."
        return result

    def _map_nocodb_base_to_entity_and_base_name(
        self, base_title: str, permissions_matrix: dict
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Attempts to map a NoCoDB base title to an entity key and base_name from the PERMISSIONS_MATRIX.
        """
        for entity_key, entity_cfg in permissions_matrix.items():
            nocodb_cfg = entity_cfg.get("nocodb")
            if nocodb_cfg:
                pattern = nocodb_cfg.get("base_title_pattern")
                if pattern:
                    base_name = _extract_base_name(base_title, pattern)
                    if base_name is not None:
                        return entity_key, base_name
        return None, None

    async def group_sync(
        self,
        base_name,
        entity_config,
        all_authentik_groups_by_name,
        std_mm_users_in_channel,
        adm_mm_users_in_channel,
        mm_users_for_services,
        std_mm_channel_name_for_log,
        entity_key,
    ):
        nocodb_client = self.client
        mattermost_client = self.mattermost_client
        config = entity_config.get("nocodb")
        if not config:
            return []
        log_channel_name = std_mm_channel_name_for_log
        if entity_key not in ["ANTENNE", "POLES"]:
            return []
        nocodb_base_title_pattern = config.get("base_title_pattern", "nocodb_{base_name}")
        default_permission = config.get("default_access", "viewer")
        admin_permission = config.get("admin_access", "owner")
        return self._sync_single_nocodb_base(
            nocodb_client,
            mattermost_client,
            nocodb_base_title_pattern,
            base_name,
            mm_users_for_services,
            default_permission,
            admin_permission,
            log_channel_name,
        )

    async def differential_sync(self, mm_channel_members: dict):
        results = []
        all_bases = self.client.list_bases()
        if not all_bases:
            logging.warning("TOOLS_TO_MM: No NoCoDB bases found to sync.")
            return results

        for base in all_bases["list"]:
            base_title = base.get("title")
            base_id = base.get("id")
            entity_key, base_name = self._map_nocodb_base_to_entity_and_base_name(base_title, self.permissions_matrix)

            if not entity_key or not base_name:
                continue

            entity_config = self.permissions_matrix.get(entity_key, {})
            mm_users_for_services, _, _ = self.get_mm_users_for_entity(base_name, entity_config, mm_channel_members)
            mm_user_emails = {email.lower() for email in mm_users_for_services.keys()}

            nocodb_users = self.client.list_base_users(base_id)
            nocodb_user_emails = {user.get("email", "").lower() for user in nocodb_users if user.get("email")}

            # Remove users from NocoDB base if they are not in Mattermost
            for user in nocodb_users:
                user_email = user.get("email", "").lower()
                if user_email and user_email not in mm_user_emails:
                    results.append(
                        self._remove_user_from_nocodb_base(
                            self.client,
                            base_id,
                            base_title,
                            user["id"],
                            user_email,
                            base_name,
                        )
                    )

            # Add users to NocoDB base if they are in Mattermost but not in NocoDB
            missing_mm_users_for_permission = {
                email: data for email, data in mm_users_for_services.items() if email not in nocodb_user_emails
            }
            if missing_mm_users_for_permission:
                default_permission = entity_config.get("nocodb", {}).get("default_access", "viewer")
                admin_permission = entity_config.get("nocodb", {}).get("admin_access", "owner")
                add_results, _ = self._ensure_users_in_nocodb_base(
                    self.client,
                    self.mattermost_client,
                    base_id,
                    base_title,
                    missing_mm_users_for_permission,
                    default_permission,
                    admin_permission,
                    {},
                    base_name,
                )
                results.extend(add_results)

        return results
