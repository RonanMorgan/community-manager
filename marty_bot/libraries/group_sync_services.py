# marty_bot/libraries/group_sync_services.py
# This module will contain core business logic for services like group synchronization.
# It will be used by both the bot (app) and standalone scripts.

import logging
from typing import TYPE_CHECKING, Optional  # Added Optional

from app import config  # Import config to access EXCLUDED_USERS

# Import client-specific utilities and classes for type hinting
from clients.mattermost_client import slugify # For URL construction

if TYPE_CHECKING:
    from clients.authentik_client import AuthentikClient
    from clients.mattermost_client import MattermostClient
    from clients.outline_client import OutlineClient


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

    for mm_user in mm_users_in_channel:
        mm_user_email = mm_user.get("email")
        mm_username = mm_user.get("username", "UnknownUser")

        # --- Check for User Exclusion ---
        if mm_username in config.EXCLUDED_USERS:
            logging.info(
                f"User '{mm_username}' is in the exclusion list and will be completely ignored for sync and reporting in channel '{mm_channel_display_name}'."
            )
            # No result is added to the 'results' list for this user.
            # This ensures they are not mentioned in any summary/report generated from these results.
            continue # Move to the next user in the Mattermost channel

        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": mm_user_email or "NoEmailProvided",
            "mm_channel_display_name": mm_channel_display_name,
            "target_resource_name": auth_group_name,  # Group/Collection name
        }

        if not mm_user_email:
            logging.debug(f"MM user {mm_username} in channel {mm_channel_display_name} has no email. Skipping.")
            results.append(
                {
                    **base_user_info,
                    "service": "ALL_SERVICES",  # Special marker
                    "status": "SKIPPED",
                    "action": "SKIPPED_NO_MM_EMAIL",
                    "error_message": "Mattermost user has no email address.",
                }
            )
            continue

        # --- Authentik Synchronization ---
        auth_user_result = {
            **base_user_info,
            "service": "AUTHENTIK",
            "status": "FAILURE",
            "action": "AUTHENTIK_GROUP_UNCHANGED",
            "error_message": None,
        }
        auth_pk_to_add = email_to_authentik_user_pk_map.get(mm_user_email.lower())

        if auth_pk_to_add is None:
            auth_user_result["status"] = "SKIPPED"
            auth_user_result["action"] = "SKIPPED_USER_NOT_IN_AUTHENTIK"
            auth_user_result["error_message"] = f"User email '{mm_user_email}' not found in Authentik."
        elif auth_pk_to_add not in current_auth_user_pks_in_group:
            if authentik_client.add_user_to_group(auth_group_pk, auth_pk_to_add):
                current_auth_user_pks_in_group.add(auth_pk_to_add)
                auth_user_result["status"] = "SUCCESS"
                auth_user_result["action"] = "USER_ADDED_TO_AUTHENTIK_GROUP"
            else:
                auth_user_result["action"] = "FAILED_TO_ADD_TO_AUTHENTIK_GROUP"
                auth_user_result["error_message"] = "API call to add user to Authentik group failed."
        else:
            auth_user_result["status"] = "SUCCESS"
            auth_user_result["action"] = "USER_ALREADY_IN_AUTHENTIK_GROUP"
        results.append(auth_user_result)

        # --- Outline Synchronization ---
        if outline_client:
            outline_user_result = {
                **base_user_info,
                "service": "OUTLINE",
                "status": "FAILURE",
                "action": "OUTLINE_COLLECTION_UNCHANGED",
                "error_message": None,
            }
            outline_user = outline_client.get_user_by_email(mm_user_email)

            if not outline_user:
                outline_user_result["status"] = "SKIPPED"
                outline_user_result["action"] = "SKIPPED_USER_NOT_IN_OUTLINE"
                outline_user_result["error_message"] = f"User email '{mm_user_email}' not found in Outline."
            else:
                outline_user_id = outline_user.get("id")
                mm_user_id = mm_user.get("id") # Mattermost user ID for DM

                # Convention: Outline collection name is the same as Authentik group name
                # First, get the collection by name to find its ID
                outline_collection_obj = outline_client.get_collection_by_name(auth_group_name)

                if not outline_collection_obj:
                    outline_user_result["status"] = "SKIPPED"
                    outline_user_result["action"] = "SKIPPED_OUTLINE_COLLECTION_NOT_FOUND"
                    error_msg = f"Outline collection named '{auth_group_name}' not found (to get its ID)."
                    outline_user_result["error_message"] = error_msg
                else:
                    outline_collection_id = outline_collection_obj.get("id")

                    # Check if user is already a member
                    collection_members = outline_client.get_collection_members(outline_collection_id)
                    is_already_member = False
                    if collection_members is not None: # If None, API call failed, proceed to add tentatively
                        is_already_member = outline_user_id in collection_members

                    if is_already_member:
                        outline_user_result["status"] = "SUCCESS"
                        outline_user_result["action"] = "USER_ALREADY_IN_OUTLINE_COLLECTION"
                    else:
                        # Attempt to add the user
                        if outline_client.add_user_to_collection(outline_collection_id, outline_user_id):
                            outline_user_result["status"] = "SUCCESS"
                            outline_user_result["action"] = "USER_ADDED_TO_OUTLINE_COLLECTION"

                            # User was newly added, try to send DM
                            collection_details = outline_client.get_collection_details(outline_collection_id)
                            if collection_details and collection_details.get("name") and mm_user_id:
                                coll_name = collection_details.get("name")
                                # Construct URL: OUTLINE_URL/collection/collection_name-collection_id
                                # The API returns an 'id' (UUID) and a 'urlId' (short human-readable).
                                # The example URL format `OUTLINE_URL/collection/collection_name-collection_id` seems to imply
                                # using the name and the main UUID. Let's try that.
                                # A safer bet might be `OUTLINE_URL/c/{collection_id}` or using `urlId` if it's the public one.
                                # Given the user's example: collection_name-collection_id
                                # Let's assume collection_id is the UUID.
                                collection_url_slug_part = slugify(coll_name) # slugify the name part
                                collection_url = f"{config.OUTLINE_URL}/collection/{collection_url_slug_part}-{outline_collection_id}"

                                dm_message = (
                                    f"Bonjour @{mm_username}, vous avez été ajouté(e) à la collection Outline **{coll_name}**.\n"
                                    f"Vous pouvez y accéder ici : {collection_url}"
                                )
                                if mattermost_client.send_dm(mm_user_id, dm_message):
                                    outline_user_result["action"] = "USER_ADDED_TO_OUTLINE_COLLECTION_AND_DM_SENT"
                                    logging.info(f"Sent DM to {mm_username} for Outline collection {coll_name}.")
                                else:
                                    outline_user_result["action"] = "USER_ADDED_TO_OUTLINE_COLLECTION_DM_FAILED"
                                    logging.warning(f"User added to Outline collection {coll_name}, but failed to send DM to {mm_username}.")
                            else:
                                logging.warning(
                                    f"User added to Outline collection {auth_group_name} (ID: {outline_collection_id}), "
                                    "but could not get collection details or MM user ID to send DM."
                                )
                        else:
                            # add_user_to_collection failed
                            outline_user_result["action"] = "FAILED_TO_ADD_TO_OUTLINE_COLLECTION"
                            error_msg = "API call to add user to Outline collection failed."
                            outline_user_result["error_message"] = error_msg
            results.append(outline_user_result)

    logging.info(
        f"Finished sync for group '{auth_group_name}' (MM channel '{mm_channel_display_name}'). "
        f"Processed {len(mm_users_in_channel)} MM users for Authentik and Outline (if configured)."
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
