import logging
from typing import TYPE_CHECKING, Optional

from app import config
from app.enums import SyncStatus
from clients.brevo_client import BrevoAction

if TYPE_CHECKING:
    from clients.brevo_client import BrevoClient


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# Brevo Synchronization Logic (merged from brevo_sync_utils.py)
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
def _ensure_contacts_in_brevo_list(
    brevo_client: "BrevoClient",
    list_id: int,
    list_name: str,
    mm_users_to_ensure: list[dict],  # Users from Mattermost channel
    mm_channel_display_name_for_log: str,
) -> tuple[list[dict], set]:  # Returns results and set of targeted emails
    """
    Ensures that the given Mattermost users are contacts in the specified Brevo list.
    Adds contacts to the list. The Brevo client handles idempotency.
    Returns a list of action results and a set of emails that were targeted.
    """
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
    brevo_client: "BrevoClient",
    brevo_list_name: str,
    mm_users_in_channel: list[dict],  # Users from the Mattermost channel
    mm_channel_display_name_for_log: str,
    perform_deletions: bool,
) -> list[dict]:
    """
    Synchronizes a single Brevo contact list with members of a Mattermost channel.
    - Creates the list in Brevo if it doesn't exist.
    - Adds Mattermost channel members to the list.
    - Removes users from the list if they are no longer in the Mattermost channel (if perform_deletions is True).
    - Excludes users defined in EXCLUDED_USERS.
    """
    results = []
    logging.info(
        f"Starting Brevo list sync for '{brevo_list_name}' based on MM channel '{mm_channel_display_name_for_log}'. "
        f"Deletions: {perform_deletions}"
    )

    if not brevo_client:
        logging.error("Brevo client not provided to _sync_single_brevo_list.")
        return results

    # 1. Get or Create the Brevo list
    brevo_lists = brevo_client.get_lists(name=brevo_list_name)
    brevo_list_obj = brevo_lists[0] if brevo_lists else None
    if not brevo_list_obj:
        brevo_list_obj = brevo_client.create_list(brevo_list_name)
        if not brevo_list_obj:
            logging.error(f"Failed to create or retrieve Brevo list '{brevo_list_name}'. Skipping sync for this list.")
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

    # 2. Process Mattermost users for adding to the list
    # target_emails_in_list will be populated by _ensure_contacts_in_brevo_list
    # and also needs to account for excluded users if they were already in the list (though Brevo sync typically doesn't preserve them if not in MM)

    # For Brevo, excluded users are typically NOT added. If they are in a list and removed from MM channel,
    # they would be removed by the deletion logic if perform_deletions is true.
    # So, we don't need special handling for target_emails_in_list for excluded users here.

    add_results, mm_targeted_emails = _ensure_contacts_in_brevo_list(
        brevo_client,
        brevo_list_id,
        brevo_list_name,
        mm_users_in_channel,
        mm_channel_display_name_for_log,
    )
    results.extend(add_results)
    target_emails_in_list = mm_targeted_emails  # These are the emails that should be in the list based on MM users

    # 3. Handle removals if perform_deletions is True
    if perform_deletions:
        logging.info(f"Performing deletions for Brevo list '{brevo_list_name}' (ID: {brevo_list_id}).")
        current_contacts_in_brevo_list = []
        offset = 0
        limit = 50
        while True:
            page_contacts = brevo_client.get_contacts_from_list(brevo_list_id)
            if page_contacts:
                current_contacts_in_brevo_list.extend(page_contacts)
                if len(page_contacts) < 50:
                    break
                offset += 50
            else:
                logging.warning(
                    f"Could not fetch contacts from Brevo list '{brevo_list_name}' (ID: {brevo_list_id}) for deletion check, or list is empty."
                )
                break

        current_emails_in_brevo_list = {
            contact.get("email", "").lower() for contact in current_contacts_in_brevo_list if contact.get("email")
        }
        emails_to_remove = current_emails_in_brevo_list - target_emails_in_list

        for email_to_remove in emails_to_remove:
            mm_username_for_log = "UnknownUser (removed)"
            base_removal_info = {
                "mm_username": mm_username_for_log,
                "mm_user_email": email_to_remove,
                "mm_channel_display_name": mm_channel_display_name_for_log,
                "target_resource_name": brevo_list_name,
                "service": "BREVO",
            }
            if brevo_client.remove_contact_from_list(email=email_to_remove, list_id=brevo_list_id):
                results.append(
                    {
                        **base_removal_info,
                        "status": SyncStatus.SUCCESS.value,
                        "action": BrevoAction.CONTACT_REMOVED.value,
                    }
                )
            else:
                results.append(
                    {
                        **base_removal_info,
                        "status": SyncStatus.FAILURE.value,
                        "action": BrevoAction.FAILED_TO_REMOVE_CONTACT.value,
                        "error_message": f"API call to remove contact '{email_to_remove}' from Brevo list '{brevo_list_name}' failed.",
                    }
                )

    logging.info(f"Finished Brevo list sync for '{brevo_list_name}'. Total results: {len(results)}")
    return results


from .mattermost import _extract_base_name


def _map_brevo_list_to_entity_and_base_name(
    list_name: str, permissions_matrix: dict
) -> tuple[Optional[str], Optional[str]]:
    """
    Attempts to map a Brevo list name to an entity key and base_name from the PERMISSIONS_MATRIX.
    """
    for entity_key, entity_cfg in permissions_matrix.items():
        brevo_cfg = entity_cfg.get("brevo")
        if brevo_cfg:
            pattern = brevo_cfg.get("list_name_pattern")
            if pattern:
                base_name = _extract_base_name(list_name, pattern)
                if base_name is not None:
                    return entity_key, base_name
    return None, None


def _sync_brevo_for_entity(brevo_client, mattermost_client, base_name, config, all_authentik_groups_by_name, email_to_authentik_user_pk_map, std_mm_users, admin_mm_users, mm_users_for_services, log_channel_name, perform_deletions, entity_key):
    brevo_list_name = config.get("list_name_pattern", "mm_{base_name}").format(base_name=base_name)
    return _sync_single_brevo_list(brevo_client, brevo_list_name, std_mm_users, log_channel_name, perform_deletions)
