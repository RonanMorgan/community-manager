import logging
from typing import TYPE_CHECKING, Optional

import config
from app.enums import SyncStatus
from clients.outline_client import OutlineAction

from .base import Service as SyncService
from .mattermost import _extract_base_name

if TYPE_CHECKING:
    from clients.mattermost_client import MattermostClient
    from clients.outline_client import OutlineClient


class OutlineService(SyncService):
    SERVICE_NAME = "OUTLINE"

    def _ensure_users_in_outline_collection(
        self,
        outline_client: "OutlineClient",
        mattermost_client: "MattermostClient",  # For DMs
        collection_id: str,
        collection_name: str,
        mm_users_for_permission: dict,  # email_lower -> {username, mm_user_id, is_admin_channel_member}
        default_permission: str,
        admin_permission: str,
        current_outline_member_ids: set,  # Set of Outline user IDs currently in the collection
        mm_channel_context_name: str,
    ) -> tuple[list[dict], set]:  # Returns results and set of targeted Outline user IDs
        """
        Ensures that the given Mattermost users are members of the specified Outline collection
        with the correct permissions. Adds or updates users in the collection.
        Sends DMs for new additions.
        Returns a list of action results and a set of Outline user IDs that were targeted.
        """
        results = []
        targeted_outline_user_ids = set()

        if not collection_id:
            logging.error(
                f"No Outline collection ID provided to _ensure_users_in_outline_collection for collection name {collection_name}."
            )
            return results, targeted_outline_user_ids

        for email_lower, mm_user_data in mm_users_for_permission.items():
            mm_username = mm_user_data["username"]
            base_user_info = {
                "mm_username": mm_username,
                "mm_user_email": email_lower,
                "mm_channel_display_name": mm_channel_context_name,
                "target_resource_name": collection_name,
                "service": "OUTLINE",
            }
            outline_result = {
                **base_user_info,
                "status": "FAILURE",
                "action": "OUTLINE_COLLECTION_UNCHANGED",
            }

            if mm_username in config.EXCLUDED_USERS:
                logging.debug(
                    f"User '{mm_username}' is excluded. Skipping Outline ensure for collection '{collection_name}'."
                )
                # If an excluded user is already in the collection, their ID should be added to
                # targeted_outline_user_ids by the caller (_sync_single_outline_collection)
                # to prevent removal. This function focuses on adding non-excluded users.
                continue

            outline_user_api = outline_client.get_user_by_email(email_lower)
            if not outline_user_api:
                outline_result.update(
                    {
                        "status": SyncStatus.SKIPPED.value,
                        "action": "SKIPPED_USER_NOT_IN_OUTLINE_FOR_ENSURE",
                        "error_message": f"User email '{email_lower}' not found in Outline.",
                    }
                )
                results.append(outline_result)
                continue

            outline_user_id = outline_user_api.get("id")
            targeted_outline_user_ids.add(outline_user_id)

            permission_to_set = admin_permission if mm_user_data["is_admin_channel_member"] else default_permission
            is_already_member = outline_user_id in current_outline_member_ids

            action_verb_prefix = (
                OutlineAction.USER_ALREADY_IN_COLLECTION_PERMISSION_ENSURED.value
                if is_already_member
                else f"USER_ADDED_TO_OUTLINE_COLLECTION_WITH_{permission_to_set.upper()}_ACCESS"
            )

            if outline_client.add_user_to_collection(collection_id, outline_user_id, permission=permission_to_set):
                current_action = action_verb_prefix
                outline_result.update({"status": SyncStatus.SUCCESS.value})

                if not is_already_member:
                    coll_details = outline_client.get_collection_details(collection_id)
                    if (
                        coll_details
                        and coll_details.get("name")
                        and coll_details.get("urlId")
                        and mm_user_data.get("mm_user_id")
                    ):
                        coll_name_for_dm = coll_details.get("name")
                        collection_url_id = coll_details.get("urlId")
                        outline_base_url = config.OUTLINE_URL

                        if outline_base_url:
                            coll_url = f"{outline_base_url.rstrip('/')}/collection/{collection_url_id}"
                            dm_text = (
                                f"Bonjour @{mm_username}, vous avez été ajouté(e) à la collection Outline "
                                f"**{coll_name_for_dm}**.\nVous pouvez y accéder ici : {coll_url}"
                            )
                            if mattermost_client.send_dm(mm_user_data["mm_user_id"], dm_text):
                                current_action = f"{action_verb_prefix}_AND_DM_SENT"
                            else:
                                current_action = f"{action_verb_prefix}_DM_FAILED"
                        else:
                            logging.warning(
                                f"OUTLINE_URL not configured. Cannot send DM for Outline collection '{coll_name_for_dm}' to user '{mm_username}'."
                            )
                            current_action = f"{action_verb_prefix}_DM_SKIPPED_NO_URL"
                    elif mm_user_data.get("mm_user_id"):
                        logging.warning(
                            f"Could not send DM for Outline collection (ID: {collection_id}) to user '{mm_username}' due to missing details."
                        )
                        if not config.OUTLINE_URL:
                            current_action = f"{action_verb_prefix}_DM_SKIPPED_NO_URL"
                        elif not (coll_details and coll_details.get("name") and coll_details.get("urlId")):
                            current_action = f"{action_verb_prefix}_DM_SKIPPED_INCOMPLETE_COLL_DETAILS"
                        else:
                            current_action = f"{action_verb_prefix}_DM_SKIPPED_UNKNOWN_REASON"
                outline_result["action"] = current_action
            else:
                verb_failed = (
                    "FAILED_TO_UPDATE_OUTLINE_PERMISSION"
                    if is_already_member
                    else "FAILED_TO_ADD_TO_OUTLINE_COLLECTION"
                )
                outline_result.update({"action": verb_failed, "error_message": "API call to Outline failed."})

            results.append(outline_result)

        return results, targeted_outline_user_ids

    def _sync_single_outline_collection(
        self,
        outline_client: "OutlineClient",
        mattermost_client: "MattermostClient",
        collection_name: str,
        mm_users_for_permission: dict,  # email_lower -> {username, mm_user_id, is_admin_channel_member}
        default_permission: str,
        admin_permission: str,
        mm_channel_context_name: str,  # For logging/reporting context
    ) -> list[dict]:
        results = []
        # Attempt to get or create the Outline collection.
        # Assuming outline_client.create_group ensures the collection exists and returns its object, or None on failure.
        # The name `create_group` is a bit generic if it's also used for getting; `ensure_collection_exists` might be clearer.
        # For now, using `create_group` as per existing code in `_create_resources_for_entity`.
        outline_collection_obj = outline_client.create_group(collection_name)  # Renamed from get_collection_by_name

        if not outline_collection_obj or not outline_collection_obj.get("id"):
            logging.error(
                f"Failed to get or create Outline collection '{collection_name}'. Cannot sync this collection."
            )
            return [
                {
                    "service": "OUTLINE",
                    "target_resource_name": collection_name,
                    "status": SyncStatus.FAILURE.value,
                    "action": "FAILED_TO_ENSURE_OUTLINE_COLLECTION",
                    "error_message": "Failed to get or create collection in Outline.",
                }
            ]

        outline_collection_id = outline_collection_obj.get("id")
        # get_collection_members should be called after we know the collection exists.
        current_outline_member_ids = set(outline_client.get_collection_members(outline_collection_id) or [])
        target_outline_ids_for_collection = set()
        # Map Outline user ID to their MM details (username, mm_user_id, email) for logging during removal
        outline_id_to_mm_user_map = (
            {}
        )  # This map will be populated by _ensure_users_in_outline_collection indirectly if needed, or built here for removals.
        # For excluded users, we still need to know their Outline ID if they are already members.

        # Populate outline_id_to_mm_user_map for all users in mm_users_for_permission
        # This is useful for the removal step to log details of users being removed.
        for email_lower, mm_user_data_val in mm_users_for_permission.items():
            temp_outline_user_obj = outline_client.get_user_by_email(email_lower)
            if temp_outline_user_obj and temp_outline_user_obj.get("id"):
                outline_id_to_mm_user_map[temp_outline_user_obj.get("id")] = {
                    "username": mm_user_data_val.get("username"),
                    "mm_user_id": mm_user_data_val.get("mm_user_id"),
                    "email": email_lower,
                }

        # Preserve excluded users if they are already in the collection
        for email_l, mm_user_d in mm_users_for_permission.items():
            if mm_user_d.get("username") in config.EXCLUDED_USERS:
                excluded_outline_user = outline_client.get_user_by_email(email_l)
                if excluded_outline_user and excluded_outline_user.get("id") in current_outline_member_ids:
                    target_outline_ids_for_collection.add(excluded_outline_user.get("id"))
                    logging.info(
                        f"User '{mm_user_d.get('username')}' is excluded and already in Outline collection '{collection_name}'. Will be preserved."
                    )

        # Ensure users from Mattermost channels are in the Outline collection
        add_update_results, mm_targeted_outline_ids = self._ensure_users_in_outline_collection(
            outline_client=outline_client,
            mattermost_client=mattermost_client,
            collection_id=outline_collection_id,
            collection_name=collection_name,
            mm_users_for_permission=mm_users_for_permission,
            default_permission=default_permission,
            admin_permission=admin_permission,
            current_outline_member_ids=current_outline_member_ids,
            mm_channel_context_name=mm_channel_context_name,
        )
        results.extend(add_update_results)
        target_outline_ids_for_collection.update(mm_targeted_outline_ids)
        return results

    def _remove_user_from_outline_collection(
        self,
        outline_client: "OutlineClient",
        collection_id: str,
        collection_name: str,
        user_id: str,
        user_email: str,
        mm_channel_context_name: str,
    ) -> dict:
        """Removes a user from an Outline collection and returns a result dictionary."""
        result = {
            "service": "OUTLINE",
            "target_resource_name": collection_name,
            "mm_user_email": user_email,
            "mm_channel_display_name": mm_channel_context_name,
            "status": SyncStatus.FAILURE.value,
            "action": "FAILED_TO_REMOVE_FROM_OUTLINE_COLLECTION",
        }
        if outline_client.remove_user_from_collection(collection_id, user_id):
            result["status"] = SyncStatus.SUCCESS.value
            result["action"] = OutlineAction.USER_REMOVED_FROM_COLLECTION.value
        else:
            result["error_message"] = "API call to remove user from Outline collection failed."
        return result

    def _map_outline_collection_to_entity_and_base_name(
        self, collection_name: str, permissions_matrix: dict
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Attempts to map an Outline collection name to an entity key and base_name from the PERMISSIONS_MATRIX.
        """
        for entity_key, entity_cfg in permissions_matrix.items():
            outline_cfg = entity_cfg.get("outline")
            if outline_cfg:
                pattern = outline_cfg.get("collection_name_pattern")
                if pattern:
                    base_name = _extract_base_name(collection_name, pattern)
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
        outline_client = self.client
        mattermost_client = self.mattermost_client
        config = entity_config.get("outline")
        if not config:
            return []
        log_channel_name = std_mm_channel_name_for_log
        outline_coll_name = config.get("collection_name_pattern", "{base_name}").format(base_name=base_name)
        default_permission = config.get("default_access", "read")
        admin_permission = config.get("admin_access", "read_write")
        return self._sync_single_outline_collection(
            outline_client,
            mattermost_client,
            outline_coll_name,
            mm_users_for_services,
            default_permission,
            admin_permission,
            log_channel_name,
        )

    async def differential_sync(self, mm_channel_members: dict):
        results = []
        try:
            all_collections = self.client.list_collections()
            if not all_collections:
                logging.warning("TOOLS_TO_MM: No Outline collections found to sync.")
                return results
        except (AttributeError, NotImplementedError):
            logging.error("`outline_client.list_collections()` method not implemented. Skipping Outline sync.")
            return results

        for collection in all_collections:
            collection_name = collection.get("name")
            collection_id = collection.get("id")
            entity_key, base_name = self._map_outline_collection_to_entity_and_base_name(
                collection_name, self.permissions_matrix
            )

            if not entity_key or not base_name:
                continue

            entity_config = self.permissions_matrix.get(entity_key, {})
            mm_users_for_services, _, _ = self.get_mm_users_for_entity(base_name, entity_config, mm_channel_members)

            mm_user_emails = {email.lower() for email in mm_users_for_services.keys()}

            outline_users = self.client.get_collection_members_with_details(collection_id)
            outline_user_emails = {user.get("email", "").lower() for user in outline_users if user.get("email")}

            # Remove users from Outline collection if they are not in Mattermost
            for user in outline_users:
                user_email = user.get("email", "").lower()
                if user_email and user_email not in mm_user_emails:
                    results.append(
                        self._remove_user_from_outline_collection(
                            self.client,
                            collection_id,
                            collection_name,
                            user["id"],
                            user_email,
                            base_name,
                        )
                    )

            # Add users to Outline collection if they are in Mattermost but not in Outline
            missing_mm_users_for_permission = {
                email: data for email, data in mm_users_for_services.items() if email not in outline_user_emails
            }
            if missing_mm_users_for_permission:
                default_permission = entity_config.get("outline", {}).get("default_access", "read")
                admin_permission = entity_config.get("outline", {}).get("admin_access", "read_write")
                add_results, _ = self._ensure_users_in_outline_collection(
                    self.client,
                    self.mattermost_client,
                    collection_id,
                    collection_name,
                    missing_mm_users_for_permission,
                    default_permission,
                    admin_permission,
                    set(),
                    base_name,
                )
                results.extend(add_results)

        return results
