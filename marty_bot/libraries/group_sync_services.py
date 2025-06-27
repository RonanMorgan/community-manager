# marty_bot/libraries/group_sync_services.py
# This module will contain core business logic for services like group synchronization.
# It will be used by both the bot (app) and standalone scripts.

import logging
from typing import TYPE_CHECKING, Optional  # Added Optional

from app import config  # Import config to access EXCLUDED_USERS

# Import client-specific utilities and classes for type hinting
from clients.mattermost_client import slugify  # For URL construction

if TYPE_CHECKING:
    from clients.authentik_client import AuthentikClient
    from clients.mattermost_client import MattermostClient
    from clients.outline_client import OutlineClient


# Helper function to determine Outline permission
def _determine_outline_permission(auth_group_name: str, mm_channel_type: str) -> str:
    """
    Determines the Outline permission ('read' or 'read_write') based on
    the Authentik group name prefix and Mattermost channel type.
    Defaults to 'read' if specific conditions aren't met or errors occur.
    """
    permission_category_key = None
    # Use the original auth_group_name for prefix checking, assuming it follows the convention
    # (e.g., "projet_My Project" or "pole_My Pole")
    # Slugification for channel lookup is separate from this logic.
    # Normalizing to lower for robust prefix checking.
    normalized_group_name = auth_group_name.lower()

    if normalized_group_name.startswith("projet_"):
        permission_category_key = "PROJET_ADMIN" if mm_channel_type == "P" else "PROJET"
    elif normalized_group_name.startswith("antenne_"):
        permission_category_key = "ANTENNE_ADMIN" if mm_channel_type == "P" else "ANTENNE"
    elif normalized_group_name.startswith("pole_") or normalized_group_name.startswith("pôle_"):
        permission_category_key = "POLES_ADMIN" if mm_channel_type == "P" else "POLES"
    else:
        logging.warning(
            f"Outline Permission: Could not determine category for group '{auth_group_name}' "
            f"based on known prefixes (projet_, antenne_, pole_). Defaulting to 'read'."
        )
        return "read"

    if permission_category_key:
        # config.PERMISSIONS_MATRIX is loaded as a dict keyed by category string
        category_config = config.PERMISSIONS_MATRIX.get(permission_category_key)
        if category_config:
            outline_access = category_config.get("outline", {}).get("access")
            if outline_access == "rw":
                return "read_write"
            elif outline_access == "read":
                return "read"
            else:
                logging.warning(
                    f"Outline Permission: Access value '{outline_access}' for category "
                    f"'{permission_category_key}' is invalid. Defaulting to 'read'."
                )
        else:
            logging.warning(
                f"Outline Permission: Category '{permission_category_key}' not found in "
                f"PERMISSIONS_MATRIX. Defaulting to 'read'."
            )

    return "read"  # Fallback default


def get_all_authentik_groups_and_user_map(authentik_client: "AuthentikClient"):
    """
    Fetches all Authentik groups and constructs a user email-to-PK map.
    Uses the get_groups_with_users method from AuthentikClient.
    """
    logging.info("Fetching all Authentik groups and constructing user email-to-PK map...")
    if not authentik_client:
        logging.error("Authentik client not provided to get_all_authentik_groups_and_user_map.")
        return [], {}

    groups, email_map = authentik_client.get_groups_with_users()  # This method handles pagination

    if not groups:
        logging.warning("No Authentik groups found or an error occurred during fetching.")
    if not email_map:
        logging.warning("Authentik user email-to-PK map is empty or could not be constructed.")

    return groups, email_map


def sync_single_group_to_services(
    authentik_client: "AuthentikClient",
    mattermost_client: "MattermostClient",
    outline_client: Optional["OutlineClient"],
    mm_team_id: str,
    authentik_group: dict,
    email_to_authentik_user_pk_map: dict,
) -> list[dict]:
    """
    Synchronizes members from a Mattermost channel (matched by name to the Authentik group)
    into the corresponding Authentik group and an Outline collection.
    Returns a list of dictionaries, each detailing an attempted sync operation for a user/service.
    Returns an empty list if a critical setup error occurred for core components (MM, Authentik).
    """
    results = []
    # Critical clients for fetching users and primary group sync
    if not authentik_client or not mattermost_client or not mm_team_id:
        logging.error(
            "Core client (Authentik/Mattermost) or team_id missing for sync_single_group_to_services."
        )  # noqa: E501
        # Not adding a result here as it's a setup failure before any specific group/user processing.
        # The higher level function `orchestrate_authentik_mattermost_sync` handles the boolean False for critical errors.
        return []

    auth_group_name = authentik_group.get("name")
    auth_group_pk = authentik_group.get("pk")
    current_auth_user_pks_in_group = set(authentik_group.get("users", []))

    if not auth_group_name or not auth_group_pk:
        logging.warning(f"Skipping Authentik group due to missing name or PK: {authentik_group}")
        return []

    logging.info(f"Processing sync for Authentik group: '{auth_group_name}' (PK: {auth_group_pk})")
    mm_channel_slug = slugify(auth_group_name)
    mm_channel = mattermost_client.get_channel_by_name(mm_team_id, mm_channel_slug)

    mm_channel_display_name = f"'{mm_channel_slug}' (derived from Authentik group)"
    if mm_channel:
        mm_channel_display_name = mm_channel.get("display_name", mm_channel_slug)

    if not mm_channel:
        logging.warning(
            f"No Mattermost channel found with slug '{mm_channel_slug}' "
            f"(derived from Authentik group '{auth_group_name}'). Skipping."
        )
        # results.append({ # Potentially add a record for this skip
        # "status": "SKIPPED_NO_MM_CHANNEL" ... })
        return []  # No user operations if no channel

    mm_channel_id = mm_channel.get("id")
    logging.info(f"Found corresponding Mattermost channel '{mm_channel_display_name}' " f"(ID: {mm_channel_id})")

    mm_users_in_channel = mattermost_client.get_users_in_channel(mm_channel_id)
    if not mm_users_in_channel:
        logging.info(
            f"No users in Mattermost channel '{mm_channel_display_name}'. "
            f"Nothing to sync to Authentik group '{auth_group_name}'."
        )
        return []

    logging.info(f"Found {len(mm_users_in_channel)} users in Mattermost channel " f"'{mm_channel_display_name}'.")

    # Determine Outline permission for this group/channel once
    # This permission will apply to all users being added to this collection in this run
    outline_permission_for_collection = "read"  # Default
    if outline_client and mm_channel:
        mm_channel_type = mm_channel.get("type", "")
        outline_permission_for_collection = _determine_outline_permission(auth_group_name, mm_channel_type)

    # Mattermost users are the source of truth
    # mm_user_emails_in_channel_set = {user["email"].lower() for user in mm_users_in_channel if user.get("email")} # F841 Unused
    # mm_email_to_username_map = { # F841 Unused
    #     user["email"].lower(): user.get("username", "UnknownUser") for user in mm_users_in_channel if user.get("email")
    # }

    # --- Authentik Synchronization ---
    # PKs of Authentik users that should be in the group based on Mattermost
    target_auth_pks_for_group = set()

    # 1. Process users from Mattermost channel (additions/ensuring presence)
    for mm_user in mm_users_in_channel:
        mm_user_email_lower = mm_user.get("email", "").lower()
        mm_username = mm_user.get("username", "UnknownUser")

        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": mm_user.get("email") or "NoEmailProvided",
            "mm_channel_display_name": mm_channel_display_name,
            "target_resource_name": auth_group_name,
        }

        if mm_username in config.EXCLUDED_USERS:
            logging.info(f"User '{mm_username}' is excluded. Skipping for all services.")
            # If this user (by email) is in Authentik's email_to_authentik_user_pk_map,
            # ensure their PK is added to target_auth_pks_for_group so they are NOT removed.
            if mm_user_email_lower and mm_user_email_lower in email_to_authentik_user_pk_map:
                excluded_auth_pk = email_to_authentik_user_pk_map[mm_user_email_lower]
                target_auth_pks_for_group.add(excluded_auth_pk)
            # Similar logic will be needed for Outline if an excluded user should remain in a collection
            continue

        if not mm_user_email_lower:
            results.append(
                {
                    **base_user_info,
                    "service": "ALL_SERVICES",
                    "status": "SKIPPED",
                    "action": "SKIPPED_NO_MM_EMAIL",
                    "error_message": "Mattermost user has no email.",
                }
            )
            continue

        # Authentik: Add/verify user
        auth_user_result = {
            **base_user_info,
            "service": "AUTHENTIK",
            "status": "FAILURE",
            "action": "AUTHENTIK_GROUP_UNCHANGED",
        }
        auth_pk_for_mm_user = email_to_authentik_user_pk_map.get(mm_user_email_lower)

        if auth_pk_for_mm_user is None:
            auth_user_result.update(
                {
                    "status": "SKIPPED",
                    "action": "SKIPPED_USER_NOT_IN_AUTHENTIK",
                    "error_message": f"User email '{mm_user_email_lower}' not in Authentik.",
                }
            )
        else:
            target_auth_pks_for_group.add(auth_pk_for_mm_user)  # This user should be in the group
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

        # --- Outline Synchronization (Additions/Ensuring Presence) ---
        # (Outline removal will be handled separately after this loop)
        if outline_client:
            # ... (Outline add/verify logic - largely similar to existing, but ensure target_outline_ids are collected)
            # This part will be refined in a subsequent step. For now, focusing on Authentik removal.
            # For now, we'll keep the existing Outline add/verify logic for users in MM channel.
            # A more comprehensive Outline sync (including removals) will require careful handling of Outline user IDs.
            outline_user_result = {
                **base_user_info,
                "service": "OUTLINE",
                "status": "FAILURE",
                "action": "OUTLINE_COLLECTION_UNCHANGED",
                "error_message": None,
            }
            outline_user = outline_client.get_user_by_email(mm_user_email_lower)

            if not outline_user:
                outline_user_result["status"] = "SKIPPED"
                outline_user_result["action"] = "SKIPPED_USER_NOT_IN_OUTLINE"
                outline_user_result["error_message"] = f"User email '{mm_user_email_lower}' not found in Outline."
            else:
                outline_user_id = outline_user.get("id")
                mm_user_id_for_dm = mm_user.get("id")

                outline_collection_obj = outline_client.get_collection_by_name(auth_group_name)
                if not outline_collection_obj:
                    outline_user_result.update(
                        {
                            "status": "SKIPPED",
                            "action": "SKIPPED_OUTLINE_COLLECTION_NOT_FOUND",
                            "error_message": f"Outline collection '{auth_group_name}' not found.",
                        }
                    )
                else:
                    outline_collection_id = outline_collection_obj.get("id")
                    collection_members = outline_client.get_collection_members(outline_collection_id)
                    is_already_member = False
                    if collection_members is not None:
                        is_already_member = outline_user_id in collection_members

                    if is_already_member:  # Assuming permission update is handled by add_user_to_collection if needed
                        if outline_client.add_user_to_collection(
                            outline_collection_id, outline_user_id, permission=outline_permission_for_collection
                        ):
                            outline_user_result.update(
                                {
                                    "status": "SUCCESS",
                                    "action": "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED",
                                }
                            )
                        else:
                            outline_user_result.update(
                                {
                                    "action": "FAILED_TO_UPDATE_OUTLINE_PERMISSION",
                                    "error_message": "API call to update user permission in Outline collection failed.",
                                }
                            )
                    else:  # User not member, try to add
                        if outline_client.add_user_to_collection(
                            outline_collection_id, outline_user_id, permission=outline_permission_for_collection
                        ):
                            outline_user_result["status"] = "SUCCESS"
                            base_action_str = f"USER_ADDED_TO_OUTLINE_COLLECTION_WITH_{outline_permission_for_collection.upper()}_ACCESS"
                            # User was newly added, try to send DM
                            collection_details = outline_client.get_collection_details(outline_collection_id)
                            if collection_details and collection_details.get("name") and mm_user_id_for_dm:
                                coll_name = collection_details.get("name")
                                collection_url_slug_part = slugify(coll_name)
                                # Ensure config.OUTLINE_URL is available or handled if None
                                outline_base_url_for_dm = config.OUTLINE_URL or "http://default-outline-url.com"
                                collection_url = f"{outline_base_url_for_dm.rstrip('/')}/collection/{collection_url_slug_part}-{outline_collection_id}"
                                dm_message = (
                                    f"Bonjour @{mm_username}, vous avez été ajouté(e) à la collection Outline **{coll_name}**.\n"
                                    f"Vous pouvez y accéder ici : {collection_url}"
                                )
                                if mattermost_client.send_dm(mm_user_id_for_dm, dm_message):
                                    outline_user_result["action"] = f"{base_action_str}_AND_DM_SENT"
                                    logging.info(f"Sent DM to {mm_username} for Outline collection {coll_name}.")
                                else:
                                    outline_user_result["action"] = f"{base_action_str}_DM_FAILED"
                                    logging.warning(
                                        f"User added to Outline collection {coll_name} (permission: {outline_permission_for_collection}), but failed to send DM to {mm_username}."
                                    )
                            else:
                                # If DM can't be attempted, action remains base_action_string
                                logging.warning(
                                    f"User added to Outline collection {auth_group_name} (ID: {outline_collection_id}, permission: {outline_permission_for_collection}), "
                                    f"but could not get collection details or MM user ID to send DM. Action was: {base_action_str}"
                                )
                                outline_user_result["action"] = (
                                    base_action_str  # Ensure action is set if DM part is skipped
                                )
                        else:
                            outline_user_result.update(
                                {
                                    "action": "FAILED_TO_ADD_TO_OUTLINE_COLLECTION",
                                    "error_message": "API call to add user to Outline collection failed.",
                                }
                            )
            results.append(outline_user_result)

    # --- Authentik: Determine users to keep vs remove ---
    # Preamble: Collect PKs of Authentik users who are in the MM channel and not excluded
    target_auth_pks_in_group_based_on_mm = set()
    for mm_user_in_chan in mm_users_in_channel:
        mm_username = mm_user_in_chan.get("username", "UnknownUser")
        if mm_username in config.EXCLUDED_USERS:
            continue  # Skip excluded users for additions or for being a target member

        mm_email_lower = mm_user_in_chan.get("email", "").lower()
        if not mm_email_lower:
            continue  # Skip users without email

        auth_pk = email_to_authentik_user_pk_map.get(mm_email_lower)
        if auth_pk:
            target_auth_pks_in_group_based_on_mm.add(auth_pk)

    # Authentik: Process removals
    # users_obj is part of the authentik_group dict from get_groups_with_users
    auth_pk_to_auth_user_obj_map = {user.get("pk"): user for user in authentik_group.get("users_obj", [])}

    for auth_pk_initially_in_group in list(current_auth_user_pks_in_group):  # Iterate a copy
        auth_user_details = auth_pk_to_auth_user_obj_map.get(auth_pk_initially_in_group)
        auth_username_for_check = auth_user_details.get("username") if auth_user_details else None
        auth_email_for_log = auth_user_details.get("email") if auth_user_details else "N/A"

        if auth_username_for_check and auth_username_for_check in config.EXCLUDED_USERS:
            logging.info(
                f"Authentik user '{auth_username_for_check}' (PK: {auth_pk_initially_in_group}) is in EXCLUDED_USERS. Will not be removed from Authentik group '{auth_group_name}'."
            )
            # This user will be kept, so no further action for removal.
            # Add to target_auth_pks_in_group_based_on_mm to ensure they are not caught by the "add" logic if somehow not there.
            # More accurately, they are already in current_auth_user_pks_in_group, and we just don't remove them.
            continue

        if auth_pk_initially_in_group not in target_auth_pks_in_group_based_on_mm:
            # This user is in Authentik group, not excluded, and not in the target set from MM
            removal_result = {
                "mm_username": auth_username_for_check or f"AuthUserPK_{auth_pk_initially_in_group}",
                "mm_user_email": auth_email_for_log,
                "mm_channel_display_name": mm_channel_display_name,
                "target_resource_name": auth_group_name,
                "service": "AUTHENTIK",
                "status": "FAILURE",
                "action": "FAILED_TO_REMOVE_FROM_AUTHENTIK_GROUP",
            }
            if authentik_client.remove_user_from_group(auth_group_pk, auth_pk_initially_in_group):
                removal_result.update({"status": "SUCCESS", "action": "USER_REMOVED_FROM_AUTHENTIK_GROUP"})
            else:
                removal_result["error_message"] = "API call to remove user from Authentik group failed."
            results.append(removal_result)

    # --- Outline: Determine users to keep vs remove ---
    if outline_client:
        outline_collection_obj = outline_client.get_collection_by_name(auth_group_name)
        if outline_collection_obj:
            outline_collection_id = outline_collection_obj.get("id")
            current_outline_member_ids = set(outline_client.get_collection_members(outline_collection_id) or [])

            target_outline_ids_based_on_mm = set()
            # We need a map from Outline user ID to their MM username for checking exclusions
            # This requires fetching details for Outline users if not already available.
            # Let's assume for now we can get this map.
            # outline_id_to_mm_username_map = get_outline_id_to_mm_username_map(outline_client, current_outline_member_ids, mm_email_to_username_map)
            # This helper function would be complex.
            # Alternative: Iterate MM users, find their Outline ID, and if not excluded, add to target_outline_ids.

            # For users in MM Channel, determine their corresponding Outline ID if they exist in Outline
            # and should be in the collection (i.e., not excluded).
            temp_outline_id_to_mm_username = {}  # Used for logging/checking exclusion during removal

            for mm_user_in_chan in mm_users_in_channel:
                mm_username = mm_user_in_chan.get("username", "UnknownUser")
                mm_email_lower = mm_user_in_chan.get("email", "").lower()

                if not mm_email_lower:
                    continue  # Skip if no email

                outline_user_obj = outline_client.get_user_by_email(mm_email_lower)
                if outline_user_obj:
                    outline_id = outline_user_obj.get("id")
                    temp_outline_id_to_mm_username[outline_id] = mm_username
                    if mm_username not in config.EXCLUDED_USERS:
                        target_outline_ids_based_on_mm.add(outline_id)
                    elif mm_username in config.EXCLUDED_USERS and outline_id in current_outline_member_ids:
                        # If user is excluded BUT already in the Outline collection, we intend to keep them there.
                        target_outline_ids_based_on_mm.add(outline_id)

            # Outline: Process removals
            for outline_member_id_initially in list(current_outline_member_ids):
                member_mm_username = temp_outline_id_to_mm_username.get(outline_member_id_initially)
                # If member_mm_username is None, it means this Outline member's email wasn't found among MM channel users.
                # Or they had no email.

                if member_mm_username and member_mm_username in config.EXCLUDED_USERS:
                    logging.info(
                        f"Outline user '{member_mm_username}' (ID: {outline_member_id_initially}) is in EXCLUDED_USERS. Will not be removed from Outline collection '{auth_group_name}'."
                    )
                    # User is excluded, ensure they are considered "target" to prevent removal
                    # This is already handled by the logic above that adds excluded users (if in collection) to target_outline_ids_based_on_mm
                    continue

                if outline_member_id_initially not in target_outline_ids_based_on_mm:
                    # This user is in Outline collection, not identified as excluded (or username unknown), and not in target set from MM
                    removal_result = {
                        "mm_username": member_mm_username or f"OutlineUser_{outline_member_id_initially}",
                        "mm_user_email": "N/A_for_Outline_direct_member",  # Email not readily available here
                        "mm_channel_display_name": mm_channel_display_name,
                        "target_resource_name": auth_group_name,
                        "service": "OUTLINE",
                        "status": "FAILURE",
                        "action": "FAILED_TO_REMOVE_FROM_OUTLINE_COLLECTION",
                    }
                    if outline_client.remove_user_from_collection(outline_collection_id, outline_member_id_initially):
                        removal_result.update({"status": "SUCCESS", "action": "USER_REMOVED_FROM_OUTLINE_COLLECTION"})
                    else:
                        removal_result["error_message"] = "API call to remove user from Outline collection failed."
                    results.append(removal_result)
        else:  # Outline collection object not found
            if current_auth_user_pks_in_group:  # If group had members, but collection doesn't exist
                logging.warning(
                    f"Outline collection for group '{auth_group_name}' not found, but Authentik group has members. No Outline removals possible."
                )

    logging.info(
        f"Finished sync for group '{auth_group_name}' (MM channel '{mm_channel_display_name}'). "
        f"Processed {len(mm_users_in_channel)} MM users. Total results generated: {len(results)}."
    )
    return results


def orchestrate_group_synchronization(
    authentik_client: "AuthentikClient",
    mattermost_client: "MattermostClient",
    outline_client: Optional["OutlineClient"],  # Outline client is optional
    mm_team_id: str,
) -> tuple[bool, list[dict]]:
    """
    Orchestrates the full synchronization of Mattermost channel users to Authentik groups
    and Outline collections.
    Requires initialized Authentik and Mattermost clients, and the Mattermost Team ID.
    Outline client is optional; if not provided, Outline sync will be skipped.
    Returns a tuple:
        - bool: True if synchronization process initiated successfully.
        - list[dict]: A list of detailed results. Empty if critical setup error.
    """
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

    all_auth_groups, email_to_auth_pk_map = get_all_authentik_groups_and_user_map(authentik_client)

    if not all_auth_groups:
        logging.info("No Authentik groups to process. Synchronization finished.")
        return True, detailed_results

    if not email_to_auth_pk_map:
        logging.warning(
            "Authentik email-to-user-PK map is empty. Authentik sync operations might not find users effectively."
        )

    if not outline_client:
        logging.info("Outline client not provided. Outline synchronization will be skipped.")

    processed_groups_count = 0

    for auth_group in all_auth_groups:
        group_sync_results = sync_single_group_to_services(  # Updated function call
            authentik_client,
            mattermost_client,
            outline_client,  # Pass the client
            mm_team_id,
            auth_group,
            email_to_auth_pk_map,
        )
        detailed_results.extend(group_sync_results)
        processed_groups_count += 1

    # Updated logging for multiple services
    auth_actions = [r["action"] for r in detailed_results if r.get("service") == "AUTHENTIK"]
    outline_actions = [r["action"] for r in detailed_results if r.get("service") == "OUTLINE"]

    total_authentik_added = auth_actions.count("USER_ADDED_TO_AUTHENTIK_GROUP")
    total_outline_membership_ensured = outline_actions.count("USER_MEMBERSHIP_ENSURED_IN_OUTLINE_COLLECTION")
    # Could also count "FAILED_TO_ADD..." etc. for more detailed logging if needed

    log_msg = (
        f"Synchronization task completed. Processed {processed_groups_count} groups. "
        f"Authentik - Users newly added: {total_authentik_added}. "
        f"Outline - User memberships ensured/added: {total_outline_membership_ensured}. "
        f"Total operations/results reported: {len(detailed_results)}."
    )
    logging.info(log_msg)
    return True, detailed_results
