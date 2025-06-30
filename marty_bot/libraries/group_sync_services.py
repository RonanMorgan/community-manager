# marty_bot/libraries/group_sync_services.py
# This module will contain core business logic for services like group synchronization.
# It will be used by both the bot (app) and standalone scripts.

import logging
import re # For slugify
from typing import TYPE_CHECKING, Optional

from app import config  # Import config to access EXCLUDED_USERS

# Import client-specific utilities and classes for type hinting
# from clients.mattermost_client import slugify # Removed to avoid potential circular dependency if this slugify is widely used
                                            # Copied slugify directly into this file for now.
                                            # Consider moving slugify to a common utils module.

if TYPE_CHECKING:
    from clients.authentik_client import AuthentikClient
    from clients.mattermost_client import MattermostClient
    from clients.outline_client import OutlineClient

# Copied from mattermost_client.py to avoid import issues and keep it self-contained here for now.
# TODO: Consider moving to a shared utils module if used in more places.
def slugify(text: str) -> str:
    """
    Simple slugify function:
    - Convert to lowercase
    - Replace spaces and underscores with hyphens
    - Remove characters that are not alphanumeric or hyphens
    - Ensure it doesn't start or end with a hyphen
    - Truncate to 64 characters (Mattermost limit for channel name)
    - Return a default name if the slug becomes empty
    """
    text = str(text).lower()
    # Replace spaces and underscores with hyphens first
    text = re.sub(r"[\s_]+", "-", text)
    # Replace any sequence of non-alphanumeric characters (excluding existing hyphens) with a single hyphen
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    # Remove leading or trailing hyphens that might have been created
    text = text.strip("-")
    # Consolidate multiple hyphens (e.g., "foo---bar" to "foo-bar").
    text = re.sub(r"-+", "-", text)

    if len(text) > 64:
        text = text[:64].strip("-")  # Re-strip if truncation creates leading/trailing hyphen

    if not text or text == "-":  # Handle if slug becomes empty or just a hyphen
        return "default-slug-name" # Changed default from 'default-channel-name' to be more generic
    return text


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
    perform_deletions: bool,
) -> list[dict]:
    """
    Synchronizes permissions for a single entity (e.g., a project, an antenne)
    across Authentik, Mattermost, and Outline.
    Includes deletion logic based on `perform_deletions` flag.
    """
    results = []
    logging.info(f"Processing sync for entity '{base_name}' (type: {entity_key}, deletions: {perform_deletions})")

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
                perform_deletions,
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
                perform_deletions,
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
                perform_deletions,
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
    perform_deletions: bool,
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
            # If no email, cannot map to Authentik user. Skip.
            # Log or add to results if needed, but for now, just continue.
            continue

        auth_pk_for_mm_user = email_to_authentik_user_pk_map.get(mm_user_email_lower)
        auth_user_result = {
            **base_user_info,
            "service": "AUTHENTIK",
            "status": "FAILURE",
            "action": "AUTHENTIK_GROUP_UNCHANGED", # Default action if nothing happens
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
            target_auth_pks_for_this_group.add(auth_pk_for_mm_user) # Mark this Authentik user as "should be in group"
            if auth_pk_for_mm_user not in current_auth_user_pks_in_group:
                if authentik_client.add_user_to_group(auth_group_pk, auth_pk_for_mm_user):
                    auth_user_result.update({"status": "SUCCESS", "action": "USER_ADDED_TO_AUTHENTIK_GROUP"})
                else:
                    auth_user_result.update(
                        { # Status remains FAILURE
                            "action": "FAILED_TO_ADD_TO_AUTHENTIK_GROUP",
                            "error_message": "API call to add user to Authentik group failed.",
                        }
                    )
            else:
                auth_user_result.update({"status": "SUCCESS", "action": "USER_ALREADY_IN_AUTHENTIK_GROUP"})
        results.append(auth_user_result)

    # Removal logic: Only if perform_deletions is True
    if perform_deletions:
        for auth_pk_in_group_obj in list(current_auth_user_pks_in_group): # Iterate over a copy for safe removal
            auth_user_details = auth_pk_to_auth_user_obj_map.get(auth_pk_in_group_obj)
            auth_username_for_check = auth_user_details.get("username") if auth_user_details else None

            # Skip removal for excluded users, they are managed manually or by other means
            if auth_username_for_check and auth_username_for_check in config.EXCLUDED_USERS:
                continue

            if auth_pk_in_group_obj not in target_auth_pks_for_this_group:
                # This Authentik user was in the group but is no longer in the target set from Mattermost
                removal_base_info = {
                    "mm_username": auth_username_for_check or f"AuthUserPK_{auth_pk_in_group_obj}",
                    "mm_user_email": auth_user_details.get("email", "N/A") if auth_user_details else "N/A",
                    "mm_channel_display_name": mm_channel_display_name_for_log,
                    "target_resource_name": auth_group_name,
                }
                removal_result = {
                    **removal_base_info,
                    "service": "AUTHENTIK",
                    "status": "FAILURE", # Default to failure
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
    mm_users_for_permission: dict, # email_lower -> {username, mm_user_id, is_admin_channel_member}
    default_permission: str,
    admin_permission: str,
    mm_channel_context_name: str, # For logging/reporting context
    perform_deletions: bool,
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
    # Map Outline user ID to their MM details (username, mm_user_id, email) for logging during removal
    outline_id_to_mm_user_map = {}

    for email_lower, mm_user_data in mm_users_for_permission.items():
        mm_username = mm_user_data["username"]

        if mm_username in config.EXCLUDED_USERS:
            logging.info(
                f"User '{mm_username}' is in EXCLUDED_USERS list, skipping Outline collection add/permission update for '{collection_name}'."
            )
            # If an excluded user is already in the collection, ensure they are not removed by adding their Outline ID
            # to the target set if they are a current member.
            temp_outline_user = outline_client.get_user_by_email(email_lower)
            if temp_outline_user and temp_outline_user.get("id") in current_outline_member_ids:
                target_outline_ids_for_collection.add(temp_outline_user.get("id"))
                # Populate map for removal loop's exclusion check (though primarily for logging if not excluded)
                outline_id_to_mm_user_map[temp_outline_user.get("id")] = {
                    "username": mm_username,
                    "mm_user_id": mm_user_data.get("mm_user_id"), # For DM context if needed
                    "email": email_lower, # For logging
                }
            continue

        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": email_lower, # Already lowercased
            "mm_channel_display_name": mm_channel_context_name,
            "target_resource_name": collection_name,
        }
        outline_user_api = outline_client.get_user_by_email(email_lower) # API should handle case if necessary
        outline_result = {
            **base_user_info,
            "service": "OUTLINE",
            "status": "FAILURE", # Default
            "action": "OUTLINE_COLLECTION_UNCHANGED", # Default
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
            # Store MM details mapped to Outline ID for potential use in removal logging
            outline_id_to_mm_user_map[outline_user_id] = {
                "username": mm_username,
                "mm_user_id": mm_user_data["mm_user_id"],
                "email": email_lower,
            }

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
                if not is_already_member: # Send DM only on first add
                    coll_details = outline_client.get_collection_details(outline_collection_id)
                    if coll_details and coll_details.get("name") and mm_user_data["mm_user_id"]:
                        coll_name_for_dm = coll_details.get("name")
                        # Construct URL (assuming slugify logic or direct link if available)
                        # For simplicity, using a placeholder or assuming direct ID linking if Outline supports it
                        # A more robust URL might involve slugifying the collection name + ID.
                        slug_part = slugify(coll_name_for_dm) # Ensure slugify is available or imported
                        outline_base_url = config.OUTLINE_URL or "http://default-outline.com" # From config
                        coll_url = f"{outline_base_url.rstrip('/')}/collection/{slug_part}-{outline_collection_id}"
                        dm_text = (
                            f"Bonjour @{mm_username}, vous avez été ajouté(e) à la collection Outline "
                            f"**{coll_name_for_dm}**.\nVous pouvez y accéder ici : {coll_url}"
                        )
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

    # Removal logic: Only if perform_deletions is True
    if perform_deletions:
        for outline_member_id in list(current_outline_member_ids): # Iterate over a copy
            mm_user_details_for_this_outline_member = outline_id_to_mm_user_map.get(outline_member_id)

            is_excluded_member = False
            if (
                mm_user_details_for_this_outline_member # Check if we have MM details for this Outline ID
                and mm_user_details_for_this_outline_member.get("username") in config.EXCLUDED_USERS
            ):
                is_excluded_member = True
            # If mm_user_details_for_this_outline_member is None, it means this Outline user
            # was not found in any of the source Mattermost channels for this entity.
            # If they are not excluded, they are a candidate for removal.

            if is_excluded_member:
                logging.info(
                    f"Outline user '{mm_user_details_for_this_outline_member.get('username')}' (ID: {outline_member_id}) "
                    f"is excluded and already in collection '{collection_name}'. Will not be removed by sync."
                )
                # Ensure they are not accidentally removed if they weren't processed in the add loop
                # (e.g. not in any MM channel but should remain in Outline due to exclusion)
                target_outline_ids_for_collection.add(outline_member_id)
                continue # Skip to next member

            if outline_member_id not in target_outline_ids_for_collection:
                # This Outline user was a member but is no longer in the target set from Mattermost users
                # AND is not an excluded user who should remain.
                username_for_log = f"OutlineUser_{outline_member_id}" # Default if no MM mapping
                user_email_for_log = "N/A" # Default
                if mm_user_details_for_this_outline_member: # We have MM details for this user
                    username_for_log = mm_user_details_for_this_outline_member.get("username", username_for_log)
                    user_email_for_log = mm_user_details_for_this_outline_member.get("email", "N/A")
                else: # No MM details, try to get email from Outline directly for logging
                    outline_user_obj = outline_client.get_user_by_id(outline_member_id) # Assumes get_user_by_id exists
                    if outline_user_obj:
                        user_email_for_log = outline_user_obj.get("email", "N/A")
                        username_for_log = outline_user_obj.get("name", username_for_log) # Outline 'name' might be display name


                removal_base_info = {
                    "mm_username": username_for_log, # Best effort username
                    "mm_user_email": user_email_for_log, # Best effort email
                    "mm_channel_display_name": mm_channel_context_name, # Context of the sync operation
                    "target_resource_name": collection_name,
                }
                removal_result = {
                    **removal_base_info,
                    "service": "OUTLINE",
                    "status": "FAILURE", # Default
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
    perform_deletions: bool = True, # Default to True for backward compatibility with script
) -> tuple[bool, list[dict]]:
    logging.info(f"Starting group synchronization task for Authentik and Outline... (Perform Deletions: {perform_deletions})")
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

        # Attempt to map Authentik group name to a base_name and entity_key from PERMISSIONS_MATRIX
        for entity_key_matrix, entity_cfg_matrix in config.PERMISSIONS_MATRIX.items():
            # Check standard group pattern first
            std_pattern = entity_cfg_matrix.get("standard", {}).get("authentik_group_name_pattern")
            if std_pattern:
                # Simple check: if pattern is "prefix_{base_name}_suffix"
                # More complex patterns might need regex. For now, assume "{base_name}" is the variable part.
                parts = std_pattern.split("{base_name}")
                prefix = parts[0]
                suffix = parts[1] if len(parts) > 1 else ""

                if auth_group_name_iter.startswith(prefix) and auth_group_name_iter.endswith(suffix):
                    # Avoid matching admin group as standard if admin pattern is similar
                    is_potentially_admin = False
                    if entity_cfg_matrix.get("admin"):
                        adm_pattern_check = entity_cfg_matrix.get("admin", {}).get("authentik_group_name_pattern")
                        if adm_pattern_check == auth_group_name_iter: # Exact match to an admin pattern
                             is_potentially_admin = True
                        elif adm_pattern_check: # Check if this std group name could also be an admin group name
                            adm_parts = adm_pattern_check.split("{base_name}")
                            adm_prefix = adm_parts[0]
                            adm_suffix = adm_parts[1] if len(adm_parts) > 1 else ""
                            if auth_group_name_iter.startswith(adm_prefix) and auth_group_name_iter.endswith(adm_suffix) and len(auth_group_name_iter) >= len(adm_prefix) + len(adm_suffix):
                                # If the current auth_group_name_iter could be formed by an admin pattern for some base_name,
                                # it's ambiguous or an admin group. Prioritize admin group interpretation later if it matches fully.
                                # This simple check might not be perfect for all overlapping patterns.
                                if len(prefix) + len(suffix) < len(adm_prefix) + len(adm_suffix): # Admin pattern is more specific
                                     is_potentially_admin = True


                    if not is_potentially_admin and len(auth_group_name_iter) > len(prefix) + len(suffix) : # Ensure there's content for base_name
                        current_base_name = auth_group_name_iter[len(prefix):len(auth_group_name_iter)-len(suffix)]
                        found_entity_key = entity_key_matrix
                        break # Found standard match

            # If not found as standard, check admin group pattern
            if found_entity_key is None and entity_cfg_matrix.get("admin"):
                adm_pattern = entity_cfg_matrix.get("admin", {}).get("authentik_group_name_pattern")
                if adm_pattern:
                    parts = adm_pattern.split("{base_name}")
                    prefix = parts[0]
                    suffix = parts[1] if len(parts) > 1 else ""
                    if auth_group_name_iter.startswith(prefix) and auth_group_name_iter.endswith(suffix) and \
                       len(auth_group_name_iter) > len(prefix) + len(suffix): # Ensure content for base_name
                        current_base_name = auth_group_name_iter[len(prefix):len(auth_group_name_iter)-len(suffix)]
                        found_entity_key = entity_key_matrix
                        break # Found admin match

        if found_entity_key and current_base_name:
            entity_tuple = (found_entity_key, current_base_name)
            if entity_tuple in processed_entities: # Avoid processing the same entity (base_name + type) multiple times
                continue

            logging.info(f"Orchestrating sync for entity: {found_entity_key}, base_name: {current_base_name}, perform_deletions: {perform_deletions}")
            entity_sync_results = sync_entity_permissions(
                authentik_client,
                mattermost_client,
                outline_client,
                mm_team_id,
                current_base_name,
                found_entity_key,
                config.PERMISSIONS_MATRIX[found_entity_key],
                all_auth_groups_by_name,
                email_to_auth_pk_map,
                perform_deletions, # Pass the flag here
            )
            detailed_results.extend(entity_sync_results)
            processed_entities.add(entity_tuple)
        else:
            logging.warning(
                f"Could not map Authentik group '{auth_group_name_iter}' to any entity in PERMISSIONS_MATRIX. Skipping."
            )

    log_msg = (
        f"Synchronization task completed (perform_deletions={perform_deletions}). "
        f"Processed {len(processed_entities)} unique entities. "
        f"Total individual operations/results reported: {len(detailed_results)}."
    )
    logging.info(log_msg)
    return True, detailed_results
