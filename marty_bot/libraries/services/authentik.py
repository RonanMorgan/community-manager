import logging
from typing import TYPE_CHECKING, Optional

import config
from app.enums import SyncStatus
from clients.authentik_client import AuthentikAction
from .base import Service as SyncService
from .mattermost import _extract_base_name

if TYPE_CHECKING:
    from clients.authentik_client import AuthentikClient


class AuthentikService(SyncService):
    SERVICE_NAME = "AUTHENTIK"

    def _ensure_users_in_authentik_group(
        self,
        authentik_client: "AuthentikClient",
        auth_group_pk: str,
        auth_group_name: str,
        mm_users_to_ensure: list[dict],  # List of Mattermost user objects
        email_to_authentik_user_pk_map: dict,
        mm_channel_display_name_for_log: str,
        current_auth_user_pks_in_group: set,
    ) -> tuple[list[dict], set]:  # Returns results and set of targeted authentik pks
        """
        Ensures that the given Mattermost users are in the specified Authentik group.
        Adds users to the group if they are not already members.
        Returns a list of action results and a set of Authentik PKs that were targeted (found in MM and Authentik).
        """
        results = []
        targeted_auth_pks = set()

        if not auth_group_pk:
            logging.error(
                f"No Authentik group PK provided to _ensure_users_in_authentik_group for group name {auth_group_name}."
            )
            # Potentially return a result indicating this failure
            return results, targeted_auth_pks

        for mm_user in mm_users_to_ensure:
            mm_username = mm_user.get("username", "UnknownUser")
            mm_user_email_lower = mm_user.get("email", "").lower()
            base_user_info = {
                "mm_username": mm_username,
                "mm_user_email": mm_user.get("email") or "NoEmailProvided",
                "mm_channel_display_name": mm_channel_display_name_for_log,
                "target_resource_name": auth_group_name,
                "service": "AUTHENTIK",
            }
            auth_user_result = {
                **base_user_info,
                "status": "FAILURE",
                "action": "AUTHENTIK_GROUP_UNCHANGED",
            }

            if mm_username in config.EXCLUDED_USERS:
                logging.debug(
                    f"User '{mm_username}' is excluded. Skipping ensure in Authentik group '{auth_group_name}'."
                )
                continue

            if not mm_user_email_lower:
                auth_user_result.update(
                    {
                        "status": SyncStatus.SKIPPED.value,
                        "action": "SKIPPED_NO_MM_EMAIL_FOR_AUTHENTIK_ENSURE",
                        "error_message": "User has no email in Mattermost for Authentik mapping.",
                    }
                )
                results.append(auth_user_result)
                continue

            auth_pk_for_mm_user = email_to_authentik_user_pk_map.get(mm_user_email_lower)

            if auth_pk_for_mm_user is None:
                auth_user_result.update(
                    {
                        "status": "SKIPPED",
                        "action": "SKIPPED_USER_NOT_IN_AUTHENTIK_FOR_ENSURE",
                        "error_message": f"User email '{mm_user_email_lower}' not in Authentik.",
                    }
                )
            else:
                targeted_auth_pks.add(auth_pk_for_mm_user)
                if auth_pk_for_mm_user not in current_auth_user_pks_in_group:
                    if authentik_client.add_user_to_group(auth_group_pk, auth_pk_for_mm_user):
                        auth_user_result.update(
                            {
                                "status": SyncStatus.SUCCESS.value,
                                "action": AuthentikAction.USER_ADDED_TO_GROUP.value,
                            }
                        )
                    else:
                        auth_user_result.update(
                            {
                                "action": "FAILED_TO_ADD_TO_AUTHENTIK_GROUP",
                                "error_message": "API call to add user to Authentik group failed.",
                            }
                        )
                else:
                    auth_user_result.update(
                        {
                            "status": SyncStatus.SUCCESS.value,
                            "action": AuthentikAction.USER_ALREADY_IN_GROUP.value,
                        }
                    )
            results.append(auth_user_result)

        return results, targeted_auth_pks

    def _sync_single_authentik_group(
        self,
        authentik_client: "AuthentikClient",
        auth_group_obj: dict,
        mm_users_in_corresponding_channel: list[dict],
        email_to_authentik_user_pk_map: dict,
        mm_channel_display_name_for_log: str,
    ) -> list[dict]:
        results = []
        auth_group_name = auth_group_obj.get("name")
        auth_group_pk = auth_group_obj.get("pk")

        if not auth_group_pk or not auth_group_name:
            logging.error(
                f"Authentik group PK or name missing in auth_group_obj: {auth_group_obj}. Skipping sync for this group."
            )
            return [
                {
                    "service": "AUTHENTIK",
                    "target_resource_name": str(auth_group_obj.get("name", "UnknownGroup")),
                    "status": SyncStatus.FAILURE.value,
                    "action": "MISSING_GROUP_PK_OR_NAME",
                    "error_message": "Group PK or name missing.",
                }
            ]

        current_auth_user_pks_in_group = set(auth_group_obj.get("users", []))
        auth_pk_to_auth_user_obj_map = {user.get("pk"): user for user in auth_group_obj.get("users_obj", [])}

        target_auth_pks_for_this_group = set()
        for mm_user_email_lower, auth_pk_val in email_to_authentik_user_pk_map.items():
            auth_user_obj = auth_pk_to_auth_user_obj_map.get(auth_pk_val)
            if auth_user_obj and auth_user_obj.get("username") in config.EXCLUDED_USERS:
                if auth_pk_val in current_auth_user_pks_in_group:
                    target_auth_pks_for_this_group.add(auth_pk_val)

        add_results, mm_targeted_pks = self._ensure_users_in_authentik_group(
            authentik_client,
            auth_group_pk,
            auth_group_name,
            mm_users_in_corresponding_channel,
            email_to_authentik_user_pk_map,
            mm_channel_display_name_for_log,
            current_auth_user_pks_in_group,
        )
        results.extend(add_results)
        target_auth_pks_for_this_group.update(mm_targeted_pks)

        return results

    def remove_user_from_authentik_group(
        self,
        authentik_client: "AuthentikClient",
        group_pk: str,
        group_name: str,
        user_pk: int,
        user_email: str,
        mm_channel_context_name: str,
    ) -> dict:
        """Removes a user from an Authentik group and returns a result dictionary."""
        result = {
            "service": "AUTHENTIK",
            "target_resource_name": group_name,
            "mm_user_email": user_email,
            "mm_channel_display_name": mm_channel_context_name,
            "status": SyncStatus.FAILURE.value,
            "action": "FAILED_TO_REMOVE_FROM_AUTHENTIK_GROUP",
        }
        if authentik_client.remove_user_from_group(group_pk, user_pk):
            result["status"] = SyncStatus.SUCCESS.value
            result["action"] = AuthentikAction.USER_REMOVED_FROM_GROUP.value
        else:
            result["error_message"] = "API call to remove user from Authentik group failed."
        return result

    def _map_auth_group_to_entity_and_base_name(
        self, auth_group_name: str, permissions_matrix: dict
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Attempts to map an Authentik group name to an entity key and base_name from the PERMISSIONS_MATRIX.
        Returns (None, None) if no unambiguous match is found.
        Prioritizes admin patterns if a name could ambiguously match both standard and admin.
        """
        for entity_key, entity_cfg in permissions_matrix.items():
            if entity_cfg.get("admin"):
                adm_pattern = entity_cfg.get("admin", {}).get("authentik_group_name_pattern")
                if adm_pattern:
                    base_name = _extract_base_name(auth_group_name, adm_pattern)
                    if base_name is not None:
                        return entity_key, base_name

        for entity_key, entity_cfg in permissions_matrix.items():
            std_pattern = entity_cfg.get("standard", {}).get("authentik_group_name_pattern")
            if std_pattern:
                base_name = _extract_base_name(auth_group_name, std_pattern)
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
        authentik_client = self.client
        config = entity_config
        std_mm_users = std_mm_users_in_channel
        admin_mm_users = adm_mm_users_in_channel
        log_channel_name = std_mm_channel_name_for_log
        results = []

        if authentik_client:
            logging.info("Fetching all Authentik users to build email-to-PK map...")
            email_to_authentik_user_pk_map = authentik_client.get_all_users_pk_by_email()
            if not email_to_authentik_user_pk_map:
                logging.warning("The email-to-PK map from Authentik is empty. User validation might fail.")
        else:
            logging.warning("Authentik client not available. Cannot fetch user PK map.")

        std_auth_group_name = (
            config["standard"].get("authentik_group_name_pattern", "{base_name}").format(base_name=base_name)
        )
        std_auth_group_obj = all_authentik_groups_by_name.get(std_auth_group_name)
        if not std_auth_group_obj:
            authentik_client.create_group(std_auth_group_name)
        if std_auth_group_obj:
            results.extend(
                self._sync_single_authentik_group(
                    authentik_client,
                    std_auth_group_obj,
                    std_mm_users,
                    email_to_authentik_user_pk_map,
                    log_channel_name,
                )
            )

        if config.get("admin"):
            adm_auth_group_name = (
                config["admin"].get("authentik_group_name_pattern", "{base_name} Admin").format(base_name=base_name)
            )
            adm_auth_group_obj = all_authentik_groups_by_name.get(adm_auth_group_name)
            if not adm_auth_group_obj:
                authentik_client.create_group(adm_auth_group_name)
            if adm_auth_group_obj:
                results.extend(
                    self._sync_single_authentik_group(
                        authentik_client,
                        adm_auth_group_obj,
                        admin_mm_users,
                        email_to_authentik_user_pk_map,
                        log_channel_name,
                    )
                )
        return results

    async def differential_sync(self, mm_channel_members: dict):
        results = []
        all_auth_groups, email_to_authentik_user_pk_map = self.client.get_groups_with_users()
        if not all_auth_groups:
            logging.warning("TOOLS_TO_MM: No Authentik groups found to sync.")
            return results

        for group in all_auth_groups:
            entity_key, base_name = self._map_auth_group_to_entity_and_base_name(
                group.get("name"), self.permissions_matrix
            )
            if not entity_key or not base_name:
                logging.debug(
                    f"TOOLS_TO_MM: Authentik group '{group.get('name')}' did not map to an entity. Skipping."
                )
                continue

            logging.info(
                f"TOOLS_TO_MM: Processing Authentik group '{group.get('name')}' for entity '{base_name}' ({entity_key})"
            )
            entity_config = self.permissions_matrix.get(entity_key, {})

            admin_cfg = entity_config.get("admin", {})
            is_admin_group = False
            if admin_cfg and _extract_base_name(group.get("name"), admin_cfg.get("authentik_group_name_pattern", "")):
                is_admin_group = True

            _, std_mm_users, adm_mm_users = self.get_mm_users_for_entity(base_name, entity_config, mm_channel_members)

            mm_users_for_this_group = adm_mm_users if is_admin_group else std_mm_users
            mm_user_emails = {user["email"].lower() for user in mm_users_for_this_group if "email" in user}

            auth_users = group.get("users_obj", [])
            auth_user_emails = {user.get("email", "").lower() for user in auth_users if user.get("email")}

            # Remove users from Authentik group if they are not in Mattermost
            for user in auth_users:
                user_email = user.get("email", "").lower()
                if user_email and user_email not in mm_user_emails:
                    if user.get("username") in config.EXCLUDED_USERS:
                        continue
                    results.append(
                        self.remove_user_from_authentik_group(
                            self.client,
                            group.get("pk"),
                            group.get("name"),
                            user.get("pk"),
                            user_email,
                            base_name,
                        )
                    )

            # Add users to Authentik group if they are in Mattermost but not in Authentik
            missing_mm_users = [
                user for user in mm_users_for_this_group if user.get("email", "").lower() not in auth_user_emails
            ]
            if missing_mm_users:
                add_results, _ = self._ensure_users_in_authentik_group(
                    self.client,
                    group.get("pk"),
                    group.get("name"),
                    missing_mm_users,
                    email_to_authentik_user_pk_map,
                    base_name,
                    set(),
                )
                results.extend(add_results)

        return results
