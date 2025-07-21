import logging
from typing import TYPE_CHECKING, Optional

import config
from app.enums import SyncStatus
from clients.vaultwarden_client import VaultwardenAction

if TYPE_CHECKING:
    from clients.mattermost_client import MattermostClient
    from clients.vaultwarden_client import VaultwardenClient


def _ensure_users_invited_to_vaultwarden_collection(
    vaultwarden_client: "VaultwardenClient",
    mattermost_client: "MattermostClient",
    collection_id: str,
    collection_name: str,
    mm_users_for_services: dict,  # email_lower -> {username, mm_user_id, ...}
    mm_channel_context_name: str,
    access_token: str,  # Vaultwarden API access token
) -> list[dict]:  # Returns results
    """
    Ensures that the given Mattermost users are invited to the specified Vaultwarden collection.
    Sends DMs for new invites. This function is additive.
    Returns a list of action results.
    """
    results = []

    if not collection_id:
        logging.error(
            f"No Vaultwarden collection ID provided to _ensure_users_invited_to_vaultwarden_collection for collection name {collection_name}."
        )
        # Could append a result indicating this failure
        return results

    if not access_token:
        logging.error(f"No Vaultwarden access token provided for collection '{collection_name}'. Cannot invite users.")
        results.append(
            {
                "service": "VAULTWARDEN",
                "target_resource_name": collection_name,
                "status": SyncStatus.FAILURE.value,
                "action": "VW_ENSURE_FAILED_NO_TOKEN",
                "error_message": "Missing Vaultwarden access token.",
            }
        )
        return results

    for email_lower, mm_user_data in mm_users_for_services.items():
        mm_username = mm_user_data.get("username", "UnknownUser")

        base_user_info = {
            "mm_username": mm_username,
            "mm_user_email": email_lower,
            "mm_channel_display_name": mm_channel_context_name,
            "target_resource_name": collection_name,
            "service": "VAULTWARDEN",
        }
        invite_result = {**base_user_info, "status": "FAILURE", "action": "VAULTWARDEN_USER_INVITE_UNCHANGED"}

        if mm_username in config.EXCLUDED_USERS:
            logging.debug(
                f"User '{mm_username}' is excluded. Skipping Vaultwarden invite for collection '{collection_name}'."
            )
            continue

        if not email_lower:
            logging.warning(
                f"Skipping user with no email for Vaultwarden invite: {mm_username} to collection {collection_name}"
            )
            invite_result.update({"status": SyncStatus.SKIPPED.value, "action": "SKIPPED_NO_EMAIL_FOR_VW_INVITE"})
            results.append(invite_result)
            continue

        logging.debug(
            f"Attempting to invite {email_lower} to Vaultwarden collection '{collection_name}' (ID: {collection_id}) via ensure function."
        )
        success = vaultwarden_client.invite_user_to_collection(
            user_email=email_lower,
            collection_id=collection_id,
            organization_id=vaultwarden_client.organization_id,
            access_token=access_token,
        )

        action_verb = VaultwardenAction.USER_INVITED_TO_COLLECTION.value
        if success:
            invite_result.update({"status": SyncStatus.SUCCESS.value, "action": action_verb})
            if mm_user_data.get("mm_user_id"):
                if config.VAULTWARDEN_SERVER_URL:
                    dm_text = (
                        f"Bonjour @{mm_username}, vous avez été invité(e) à la collection Vaultwarden "
                        f"**{collection_name}**.\n"
                        f"Vous pouvez accéder à Vaultwarden ici : {config.VAULTWARDEN_SERVER_URL.rstrip('/')}"
                    )
                    if mattermost_client.send_dm(mm_user_data["mm_user_id"], dm_text):
                        invite_result["action"] = VaultwardenAction.USER_INVITED_TO_COLLECTION_AND_DM_SENT.value
                    else:
                        invite_result["action"] = VaultwardenAction.USER_INVITED_TO_COLLECTION_DM_FAILED.value
                else:
                    logging.warning(
                        f"VAULTWARDEN_SERVER_URL not configured. Cannot send DM for Vaultwarden invite to "
                        f"{mm_username} for collection {collection_name}."
                    )
                    invite_result["action"] = VaultwardenAction.USER_INVITED_TO_COLLECTION_DM_SKIPPED_NO_URL.value
            else:
                invite_result["action"] = VaultwardenAction.USER_INVITED_TO_COLLECTION_DM_SKIPPED_NO_MM_USER_ID.value
        else:
            invite_result.update(
                {
                    "action": VaultwardenAction.FAILED_TO_INVITE_TO_COLLECTION.value,
                    "error_message": f"API call to invite {email_lower} to VW collection {collection_name} "
                    "failed or user already member/invited. See client logs.",
                }
            )
        results.append(invite_result)

    return results


def _sync_single_vaultwarden_collection_members(
    vaultwarden_client: "VaultwardenClient",
    mattermost_client: "MattermostClient",  # Added MattermostClient for DMs
    collection_name: str,
    mm_users_for_services: dict,  # email_lower -> {username, mm_user_id, is_admin_channel_member}
    mm_channel_context_name: str,  # For logging/reporting context
) -> list[dict]:
    """
    Ensures all users from mm_users_for_services are invited to the specified Vaultwarden collection and sends a DM.
    This function is additive; it only invites users and does not remove them based on MM channel membership.
    """
    results = []
    logging.info(
        f"Starting Vaultwarden collection member sync for '{collection_name}' based on MM channel '{mm_channel_context_name}'."
    )

    if not vaultwarden_client.api_username or not vaultwarden_client.api_password:
        logging.warning(f"Vaultwarden API credentials not configured. Skipping member sync for '{collection_name}'.")
        return [
            {
                "service": "VAULTWARDEN",
                "target_resource_name": collection_name,
                "status": "SKIPPED",
                "action": "SKIPPED_MISSING_API_CREDENTIALS",
                "error_message": "Vaultwarden API username or password not set.",
            }
        ]

    collection_id = vaultwarden_client.get_collection_by_name(collection_name)
    if not collection_id:
        logging.warning(
            f"Vaultwarden collection '{collection_name}' not found. It should be created by entity creation command."
        )
        return [
            {
                "service": "VAULTWARDEN",
                "target_resource_name": collection_name,
                "status": "SKIPPED",
                "action": "SKIPPED_VW_COLLECTION_NOT_FOUND",
                "error_message": f"Collection '{collection_name}' not found.",
            }
        ]

    access_token = vaultwarden_client._get_api_token()
    if not access_token:
        logging.error(f"Failed to obtain Vaultwarden API token for collection '{collection_name}'.")
        return [
            {
                "service": "VAULTWARDEN",
                "target_resource_name": collection_name,
                "status": "FAILURE",
                "action": "FAILED_TO_GET_VW_API_TOKEN",
                "error_message": "Could not obtain API token.",
            }
        ]

    # Ensure users are invited
    invite_results = _ensure_users_invited_to_vaultwarden_collection(
        vaultwarden_client=vaultwarden_client,
        mattermost_client=mattermost_client,
        collection_id=collection_id,
        collection_name=collection_name,
        mm_users_for_services=mm_users_for_services,
        mm_channel_context_name=mm_channel_context_name,
        access_token=access_token,
    )
    results.extend(invite_results)

    # Vaultwarden sync is additive only, no removal logic based on MM channel membership.
    logging.info(f"Finished Vaultwarden collection member sync for '{collection_name}'. Total results: {len(results)}")
    return results


from .mattermost import _extract_base_name


def _map_vaultwarden_collection_to_entity_and_base_name(
    collection_name: str, permissions_matrix: dict
) -> tuple[Optional[str], Optional[str]]:
    """
    Attempts to map a Vaultwarden collection name to an entity key and base_name from the PERMISSIONS_MATRIX.
    """
    for entity_key, entity_cfg in permissions_matrix.items():
        vaultwarden_cfg = entity_cfg.get("vaultwarden")
        if vaultwarden_cfg:
            pattern = vaultwarden_cfg.get("collection_name_pattern")
            if pattern:
                base_name = _extract_base_name(collection_name, pattern)
                if base_name is not None:
                    return entity_key, base_name
    return None, None


def _sync_vaultwarden_for_entity(
    vaultwarden_client,
    mattermost_client,
    base_name,
    config,
    all_authentik_groups_by_name,
    email_to_authentik_user_pk_map,
    std_mm_users,
    admin_mm_users,
    mm_users_for_services,
    log_channel_name,
    perform_deletions,
    entity_key,
):
    vw_collection_name = config.get("collection_name_pattern", "Shared - {base_name}").format(base_name=base_name)
    return _sync_single_vaultwarden_collection_members(
        vaultwarden_client, mattermost_client, vw_collection_name, mm_users_for_services, log_channel_name
    )
