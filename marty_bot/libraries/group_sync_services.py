# marty_bot/libraries/group_sync_services.py
# This module will contain core business logic for services like group synchronization.
# It will be used by both the bot (app) and standalone scripts.

import logging
from typing import TYPE_CHECKING, Optional

from app import config  # Import config to access EXCLUDED_USERS

# Import client-specific utilities and classes for type hinting
from clients.mattermost_client import slugify  # For URL construction

if TYPE_CHECKING:
    from clients.authentik_client import AuthentikClient
    from clients.mattermost_client import MattermostClient
    from clients.outline_client import OutlineClient


# Helper function to determine Outline permission (REMOVED as logic is now in _sync_single_outline_collection)
# def _determine_outline_permission(auth_group_name: str, mm_channel_type: str) -> str:
#     ...


def get_all_authentik_groups_and_user_map(authentik_client: "AuthentikClient"):
    """
    Fetches all Authentik groups and constructs a user email-to-PK map.
    Uses the get_groups_with_users method from AuthentikClient.
    """
    logging.info("Fetching all Authentik groups and constructing user email-to-PK map...")
    if not authentik_client:
        logging.error("Authentik client not provided to get_all_authentik_groups_and_user_map.")
        return [], {}

    groups, email_map = authentik_client.get_groups_with_users()

    if not groups:
        logging.warning("No Authentik groups found or an error occurred during fetching.")
    if not email_map:
        logging.warning("Authentik user email-to-PK map is empty or could not be constructed.")

    return groups, email_map


def sync_entity_permissions(
    authentik_client: "AuthentikClient",
    mattermost_client: "MattermostClient",
    outline_client: Optional["OutlineClient"],
    mm_team_id: str,
    base_name: str,
    entity_key: str,
    entity_config: dict,
    all_authentik_groups_by_name: dict,
    email_to_authentik_user_pk_map: dict,
) -> list[dict]:
    """
    Synchronizes permissions for a single entity (e.g., a project, an antenne)
    across Authentik, Mattermost, and Outline.
    """
    results = []
    logging.info(f"Processing sync for entity '{base_name}' (type: {entity_key})")

    std_config = entity_config.get("standard", {})
    admin_config = entity_config.get("admin")
    outline_cfg = entity_config.get("outline", {})

    std_auth_group_name = std_config.get("authentik_group_name_pattern", "{base_name}").format(base_name=base_name)
    std_mm_channel_name = std_config.get("mattermost_channel_name_pattern", "{base_name}").format(base_name=base_name)

    std_auth_group_obj = all_authentik_groups_by_name.get(std_auth_group_name)
    if not std_auth_group_obj:
        logging.warning(
            f"Authentik group '{std_auth_group_name}' for entity '{base_name}' not found. Skipping standard Authentik sync."
        )

    std_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(std_mm_channel_name))
    std_mm_users_in_channel = []
    if std_mm_channel:
        std_mm_users_in_channel = mattermost_client.get_users_in_channel(std_mm_channel["id"])
    else:
        logging.warning(
            f"Mattermost channel '{std_mm_channel_name}' for entity '{base_name}' not found. Standard sync might be incomplete."
        )

    adm_auth_group_obj = None
    adm_mm_users_in_channel = []
    adm_mm_channel_name_for_log = "N/A"

    if admin_config:
        adm_auth_group_name = admin_config.get("authentik_group_name_pattern", "{base_name} Admin").format(
            base_name=base_name
        )
        adm_mm_channel_name = admin_config.get("mattermost_channel_name_pattern", "{base_name} Admin").format(
            base_name=base_name
        )
        adm_mm_channel_name_for_log = adm_mm_channel_name  # For logging context
        adm_auth_group_obj = all_authentik_groups_by_name.get(adm_auth_group_name)
        if not adm_auth_group_obj:
            logging.warning(
                f"Authentik group '{adm_auth_group_name}' for entity '{base_name}' (admin) not found. Skipping admin Authentik sync."
            )

        adm_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(adm_mm_channel_name))
        if adm_mm_channel:
            adm_mm_users_in_channel = mattermost_client.get_users_in_channel(adm_mm_channel["id"])
            adm_mm_channel_name_for_log = adm_mm_channel.get("display_name", adm_mm_channel_name)
        else:
            logging.warning(
                f"Mattermost channel '{adm_mm_channel_name}' for entity '{base_name}' (admin) not found. Admin sync might be incomplete."
            )

    mm_users_for_outline_permission = {}
    for mm_user in std_mm_users_in_channel:
        email = mm_user.get("email", "").lower()
        if email:
            mm_users_for_outline_permission[email] = {
                "username": mm_user.get("username"),
                "mm_user_id": mm_user.get("id"),
                "is_admin_channel_member": False,
            }

    if admin_config:
        for mm_user in adm_mm_users_in_channel:
            email = mm_user.get("email", "").lower()
            if email:
                mm_users_for_outline_permission[email] = {
                    "username": mm_user.get("username"),
                    "mm_user_id": mm_user.get("id"),
                    "is_admin_channel_member": True,
                }

    std_mm_channel_name_for_log = std_mm_channel.get("display_name") if std_mm_channel else std_mm_channel_name

    if std_auth_group_obj:
        results.extend(
            _sync_single_authentik_group(
                authentik_client,
                std_auth_group_obj,
                std_mm_users_in_channel,
                email_to_authentik_user_pk_map,
                std_mm_channel_name_for_log,
            )
        )
    if admin_config and adm_auth_group_obj:
        results.extend(
            _sync_single_authentik_group(
                authentik_client,
                adm_auth_group_obj,
                adm_mm_users_in_channel,
                email_to_authentik_user_pk_map,
                adm_mm_channel_name_for_log,
            )
        )

    if outline_client and outline_cfg:
        outline_coll_name_pattern = outline_cfg.get("collection_name_pattern", "{base_name}")
        outline_coll_name = outline_coll_name_pattern.format(base_name=base_name)
        default_permission = outline_cfg.get("default_access", "read")
        admin_permission = outline_cfg.get("admin_access", "read_write")
        results.extend(
            _sync_single_outline_collection(
                outline_client,
                mattermost_client,
                outline_coll_name,
                mm_users_for_outline_permission,
                default_permission,
                admin_permission,
                std_mm_channel_name_for_log,
            )
        )

    logging.info(f"Finished sync for entity '{base_name}'. Total results: {len(results)}")
    return results


def _sync_single_authentik_group(
    authentik_client: "AuthentikClient",
    auth_group_obj: dict,
    mm_users_in_corresponding_channel: list[dict],
    email_to_authentik_user_pk_map: dict,
    mm_channel_display_name_for_log: str,
) -> list[dict]:
    results = []
    auth_group_name = auth_group_obj.get("name")
    auth_group_pk = auth_group_obj.get("pk")
    current_auth_user_pks_in_group = set(auth_group_obj.get("users", []))
    auth_pk_to_auth_user_obj_map = {user.get("pk"): user for user in auth_group_obj.get("users_obj", [])}
    target_auth_pks_for_this_group = set()

    for mm_user in mm_users_in_corresponding_channel:
        mm_username = mm_user.get("username", "UnknownUser")
        mm_user_email_lower = mm_user.get("email", "").lower()
        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": mm_user.get("email") or "NoEmailProvided",
            "mm_channel_display_name": mm_channel_display_name_for_log,
            "target_resource_name": auth_group_name,
        }

        if mm_username in config.EXCLUDED_USERS:
            if mm_user_email_lower and mm_user_email_lower in email_to_authentik_user_pk_map:
                auth_pk = email_to_authentik_user_pk_map[mm_user_email_lower]
                if auth_pk in current_auth_user_pks_in_group:
                    target_auth_pks_for_this_group.add(auth_pk)
            continue

        if not mm_user_email_lower:
            continue

        auth_pk_for_mm_user = email_to_authentik_user_pk_map.get(mm_user_email_lower)
        auth_user_result = {
            **base_user_info,
            "service": "AUTHENTIK",
            "status": "FAILURE",
            "action": "AUTHENTIK_GROUP_UNCHANGED",
        }

        if auth_pk_for_mm_user is None:
            auth_user_result.update(
                {
                    "status": "SKIPPED",
                    "action": "SKIPPED_USER_NOT_IN_AUTHENTIK",
                    "error_message": f"User email '{mm_user_email_lower}' not in Authentik.",
                }
            )
        else:
            target_auth_pks_for_this_group.add(auth_pk_for_mm_user)
            if auth_pk_for_mm_user not in current_auth_user_pks_in_group:
                if authentik_client.add_user_to_group(auth_group_pk, auth_pk_for_mm_user):
                    auth_user_result.update({"status": "SUCCESS", "action": "USER_ADDED_TO_AUTHENTIK_GROUP"})
                else:
                    auth_user_result.update(
                        {
                            "action": "FAILED_TO_ADD_TO_AUTHENTIK_GROUP",
                            "error_message": "API call to add user to Authentik group failed.",
                        }
                    )
            else:
                auth_user_result.update({"status": "SUCCESS", "action": "USER_ALREADY_IN_AUTHENTIK_GROUP"})
        results.append(auth_user_result)

    for auth_pk_in_group_obj in list(current_auth_user_pks_in_group):
        auth_user_details = auth_pk_to_auth_user_obj_map.get(auth_pk_in_group_obj)
        auth_username_for_check = auth_user_details.get("username") if auth_user_details else None

        if auth_username_for_check and auth_username_for_check in config.EXCLUDED_USERS:
            continue

        if auth_pk_in_group_obj not in target_auth_pks_for_this_group:
            removal_base_info = {
                "mm_username": auth_username_for_check or f"AuthUserPK_{auth_pk_in_group_obj}",
                "mm_user_email": auth_user_details.get("email", "N/A") if auth_user_details else "N/A",
                "mm_channel_display_name": mm_channel_display_name_for_log,
                "target_resource_name": auth_group_name,
            }
            removal_result = {
                **removal_base_info,
                "service": "AUTHENTIK",
                "status": "FAILURE",
                "action": "FAILED_TO_REMOVE_FROM_AUTHENTIK_GROUP",
            }
            if authentik_client.remove_user_from_group(auth_group_pk, auth_pk_in_group_obj):
                removal_result.update({"status": "SUCCESS", "action": "USER_REMOVED_FROM_AUTHENTIK_GROUP"})
            else:
                removal_result["error_message"] = "API call to remove user from Authentik group failed."
            results.append(removal_result)
    return results


def _sync_single_outline_collection(
    outline_client: "OutlineClient",
    mattermost_client: "MattermostClient",
    collection_name: str,
    mm_users_for_permission: dict,
    default_permission: str,
    admin_permission: str,
    mm_channel_context_name: str,
) -> list[dict]:
    results = []
    outline_collection_obj = outline_client.get_collection_by_name(collection_name)
    if not outline_collection_obj:
        logging.warning(f"Outline collection '{collection_name}' not found. Cannot sync.")
        return [
            {
                "service": "OUTLINE",
                "target_resource_name": collection_name,
                "status": "SKIPPED",
                "action": "SKIPPED_OUTLINE_COLLECTION_NOT_FOUND",
                "error_message": "Collection not found in Outline.",
            }
        ]

    outline_collection_id = outline_collection_obj.get("id")
    current_outline_member_ids = set(outline_client.get_collection_members(outline_collection_id) or [])
    target_outline_ids_for_collection = set()
    outline_id_to_mm_user_map = {}

    for email_lower, mm_user_data in mm_users_for_permission.items():
        mm_username = mm_user_data["username"]

        if mm_username in config.EXCLUDED_USERS:
            logging.info(
                f"User '{mm_username}' is in EXCLUDED_USERS list, skipping Outline collection add/permission update for '{collection_name}'."
            )
            # If an excluded user is already in the collection, we want to ensure they are not removed.
            # We also don't want to update their permissions via sync.
            # To achieve this, find their Outline ID and add it to target_ids if they are a current member.
            # This ensures they are not caught by the removal logic later.
            temp_outline_user = outline_client.get_user_by_email(email_lower)
            if temp_outline_user and temp_outline_user.get("id") in current_outline_member_ids:
                target_outline_ids_for_collection.add(temp_outline_user.get("id"))
                # Also populate map for removal loop's exclusion check if needed, though this path might be redundant
                outline_id_to_mm_user_map[temp_outline_user.get("id")] = {
                    "username": mm_username,
                    "mm_user_id": mm_user_data.get("mm_user_id"),
                    "email": email_lower,
                }
            continue

        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": email_lower,
            "mm_channel_display_name": mm_channel_context_name,
            "target_resource_name": collection_name,
        }
        outline_user_api = outline_client.get_user_by_email(email_lower)
        outline_result = {
            **base_user_info,
            "service": "OUTLINE",
            "status": "FAILURE",
            "action": "OUTLINE_COLLECTION_UNCHANGED",
        }

        if not outline_user_api:
            outline_result.update(
                {
                    "status": "SKIPPED",
                    "action": "SKIPPED_USER_NOT_IN_OUTLINE",
                    "error_message": f"User email '{email_lower}' not found in Outline.",
                }
            )
        else:
            outline_user_id = outline_user_api.get("id")
            target_outline_ids_for_collection.add(outline_user_id)
            outline_id_to_mm_user_map[outline_user_id] = {
                "username": mm_username,
                "mm_user_id": mm_user_data["mm_user_id"],
                "email": email_lower,
            }  # Store email too

            permission_to_set = admin_permission if mm_user_data["is_admin_channel_member"] else default_permission
            is_already_member = outline_user_id in current_outline_member_ids
            action_verb = (
                "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED"
                if is_already_member
                else f"USER_ADDED_TO_OUTLINE_COLLECTION_WITH_{permission_to_set.upper()}_ACCESS"
            )

            if outline_client.add_user_to_collection(
                outline_collection_id, outline_user_id, permission=permission_to_set
            ):
                outline_result.update({"status": "SUCCESS", "action": action_verb})
                if not is_already_member:
                    coll_details = outline_client.get_collection_details(outline_collection_id)
                    if coll_details and coll_details.get("name") and mm_user_data["mm_user_id"]:
                        coll_name_for_dm = coll_details.get("name")
                        slug_part = slugify(coll_name_for_dm)
                        outline_base_url = config.OUTLINE_URL or "http://default-outline.com"
                        coll_url = f"{outline_base_url.rstrip('/')}/collection/{slug_part}-{outline_collection_id}"
                        dm_text = f"Bonjour @{mm_username}, vous avez été ajouté(e) à la collection Outline **{coll_name_for_dm}**.\nVous pouvez y accéder ici : {coll_url}"
                        if mattermost_client.send_dm(mm_user_data["mm_user_id"], dm_text):
                            outline_result["action"] = f"{action_verb}_AND_DM_SENT"
                        else:
                            outline_result["action"] = f"{action_verb}_DM_FAILED"
            else:
                verb_failed = (
                    "FAILED_TO_UPDATE_OUTLINE_PERMISSION"
                    if is_already_member
                    else "FAILED_TO_ADD_TO_OUTLINE_COLLECTION"
                )
                outline_result.update({"action": verb_failed, "error_message": "API call to Outline failed."})
        results.append(outline_result)

    for outline_member_id in list(current_outline_member_ids):
        mm_user_details_for_this_outline_member = outline_id_to_mm_user_map.get(outline_member_id)

        is_excluded_member = False
        if (
            mm_user_details_for_this_outline_member
            and mm_user_details_for_this_outline_member.get("username") in config.EXCLUDED_USERS
        ):
            is_excluded_member = True

        if is_excluded_member:
            logging.info(
                f"Outline user '{mm_user_details_for_this_outline_member.get('username')}' (ID: {outline_member_id}) "
                f"is excluded and already in collection '{collection_name}'. Will not be removed by sync."
            )
            # Ensure they are not accidentally removed if they weren't processed in the add loop (e.g. not in any MM channel)
            # This was the original intent of adding to target_ids here.
            target_outline_ids_for_collection.add(outline_member_id)
            continue

        if outline_member_id not in target_outline_ids_for_collection:
            username_for_log = f"OutlineUser_{outline_member_id}"
            user_email_for_log = "N/A"  # Default if not found in map
            if mm_user_details_for_this_outline_member:
                username_for_log = mm_user_details_for_this_outline_member.get("username", username_for_log)
                user_email_for_log = mm_user_details_for_this_outline_member.get("email", "N/A")

            removal_base_info = {
                "mm_username": username_for_log,
                "mm_user_email": user_email_for_log,
                "mm_channel_display_name": mm_channel_context_name,
                "target_resource_name": collection_name,
            }
            removal_result = {
                **removal_base_info,
                "service": "OUTLINE",
                "status": "FAILURE",
                "action": "FAILED_TO_REMOVE_FROM_OUTLINE_COLLECTION",
            }
            if outline_client.remove_user_from_collection(outline_collection_id, outline_member_id):
                removal_result.update({"status": "SUCCESS", "action": "USER_REMOVED_FROM_OUTLINE_COLLECTION"})
            else:
                removal_result["error_message"] = "API call to remove user from Outline collection failed."
            results.append(removal_result)
    return results


def orchestrate_group_synchronization(
    authentik_client: "AuthentikClient",
    mattermost_client: "MattermostClient",
    outline_client: Optional["OutlineClient"],
    mm_team_id: str,
) -> tuple[bool, list[dict]]:
    logging.info("Starting group synchronization task for Authentik and Outline...")
    detailed_results = []

    if not authentik_client:
        logging.error("Authentik client not provided to orchestrator. Cannot proceed with Authentik sync.")
        return False, detailed_results
    if not mattermost_client:
        logging.error("Mattermost client not provided to orchestrator. Cannot proceed.")
        return False, detailed_results
    if not mm_team_id:
        logging.error("Mattermost Team ID not provided to orchestrator. Cannot proceed.")
        return False, detailed_results

    all_auth_groups_list, email_to_auth_pk_map = get_all_authentik_groups_and_user_map(authentik_client)

    if not all_auth_groups_list:
        logging.info("No Authentik groups to process. Synchronization finished.")
        return True, detailed_results

    all_auth_groups_by_name = {g["name"]: g for g in all_auth_groups_list}

    if not email_to_auth_pk_map:
        logging.warning(
            "Authentik email-to-user-PK map is empty. Authentik sync operations might not find users effectively."
        )

    if not outline_client:
        logging.info("Outline client not provided. Outline synchronization will be skipped.")

    processed_entities = set()

    for auth_group_name_iter, auth_group_obj_iter in all_auth_groups_by_name.items():
        found_entity_key = None
        current_base_name = None

        for entity_key_matrix, entity_cfg_matrix in config.PERMISSIONS_MATRIX.items():
            std_pattern = entity_cfg_matrix.get("standard", {}).get("authentik_group_name_pattern")
            if std_pattern:
                prefix = std_pattern.split("{base_name}")[0]
                if auth_group_name_iter.startswith(prefix) and len(auth_group_name_iter) > len(prefix):
                    is_admin_group_name = False
                    if entity_cfg_matrix.get("admin"):
                        admin_suffix_in_pattern = (
                            entity_cfg_matrix.get("admin", {})
                            .get("authentik_group_name_pattern", "")
                            .split("{base_name}")[-1]
                        )
                        if auth_group_name_iter.endswith(admin_suffix_in_pattern) and len(admin_suffix_in_pattern) > 0:
                            is_admin_group_name = True
                    if not is_admin_group_name:
                        current_base_name = auth_group_name_iter[len(prefix) :]
                        found_entity_key = entity_key_matrix
                        break

            if found_entity_key is None and entity_cfg_matrix.get("admin"):
                adm_pattern = entity_cfg_matrix.get("admin", {}).get("authentik_group_name_pattern")
                if adm_pattern:
                    prefix = adm_pattern.split("{base_name}")[0]
                    suffix = adm_pattern.split("{base_name}")[-1] if "{base_name}" in adm_pattern else ""
                    if (
                        auth_group_name_iter.startswith(prefix)
                        and auth_group_name_iter.endswith(suffix)
                        and len(auth_group_name_iter) > len(prefix) + len(suffix)
                    ):
                        current_base_name = (
                            auth_group_name_iter[len(prefix) : -len(suffix)]
                            if suffix
                            else auth_group_name_iter[len(prefix) :]
                        )
                        found_entity_key = entity_key_matrix
                        break

        if found_entity_key and current_base_name:
            entity_tuple = (found_entity_key, current_base_name)
            if entity_tuple in processed_entities:
                continue

            logging.info(f"Orchestrating sync for entity: {found_entity_key}, base_name: {current_base_name}")
            entity_sync_results = sync_entity_permissions(
                authentik_client,
                mattermost_client,
                outline_client,
                mm_team_id,
                current_base_name,
                found_entity_key,
                config.PERMISSIONS_MATRIX[found_entity_key],
                all_auth_groups_by_name,  # Corrected variable name
                email_to_auth_pk_map,
            )
            detailed_results.extend(entity_sync_results)
            processed_entities.add(entity_tuple)
        else:
            logging.warning(
                f"Could not map Authentik group '{auth_group_name_iter}' to any entity in PERMISSIONS_MATRIX. Skipping."
            )

    log_msg = (
        f"Synchronization task completed. Processed {len(processed_entities)} unique entities. "
        f"Total individual operations/results reported: {len(detailed_results)}."
    )
    logging.info(log_msg)
    return True, detailed_results
