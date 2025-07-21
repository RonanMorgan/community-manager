# marty_bot/libraries/group_sync_services.py
# This module will contain core business logic for services like group synchronization.
# It will be used by both the bot (app) and standalone scripts.

import logging
import re
from typing import TYPE_CHECKING, Optional

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import config
from app.enums import SyncStatus
from clients.vaultwarden_client import VaultwardenAction
from libraries.services.outline import (
    _sync_single_outline_collection,
    _remove_user_from_outline_collection,
    _map_outline_collection_to_entity_and_base_name,
    _sync_outline_for_entity,
)
from libraries.services.nocodb import (
    _sync_single_nocodb_base,
    _remove_user_from_nocodb_base,
    _map_nocodb_base_to_entity_and_base_name,
    _sync_nocodb_for_entity,
)
from libraries.services.vaultwarden import (
    _sync_single_vaultwarden_collection_members,
    _map_vaultwarden_collection_to_entity_and_base_name,
    _sync_vaultwarden_for_entity,
)
from libraries.services.brevo import (
    _sync_single_brevo_list,
    _map_brevo_list_to_entity_and_base_name,
    _sync_brevo_for_entity,
)
from libraries.services.authentik import (
    get_all_authentik_groups_and_user_map,
    _sync_single_authentik_group,
    remove_user_from_authentik_group,
    _map_auth_group_to_entity_and_base_name,
    _sync_authentik_for_entity,
)
from libraries.services.mattermost import _map_mm_channel_to_entity_and_base_name, _extract_base_name


if TYPE_CHECKING:
    from clients.authentik_client import AuthentikClient
    from clients.mattermost_client import MattermostClient
    from clients.outline_client import OutlineClient
    from clients.brevo_client import BrevoClient
    from clients.nocodb_client import NocoDBClient
    from clients.vaultwarden_client import VaultwardenClient  # Added VaultwardenClient


from libraries.services.mattermost import slugify, _get_mm_users_for_entity


# Helper function to determine Outline permission (REMOVED as logic is now in _sync_single_outline_collection)
# def _determine_outline_permission(auth_group_name: str, mm_channel_type: str) -> str:
#     ...
def sync_entity_permissions(
    clients: dict,
    mm_team_id: str,
    base_name: str,
    entity_key: str,
    entity_config: dict,
    all_authentik_groups_by_name: dict,
    email_to_authentik_user_pk_map: dict,
    perform_deletions: bool,
    skip_services: list[str] | None = None,
) -> list[dict]:
    """
    Synchronizes permissions for a single entity across configured services.
    """
    results = []
    skip_services = skip_services or []
    mattermost_client = clients.get("mattermost")

    logging.info(f"Processing sync for entity '{base_name}' (type: {entity_key}, deletions: {perform_deletions})")

    # Common user and channel data preparation
    std_config = entity_config.get("standard", {})
    admin_config = entity_config.get("admin")
    std_mm_channel_name = std_config.get("mattermost_channel_name_pattern", "{base_name}").format(base_name=base_name)
    std_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(std_mm_channel_name))
    std_mm_users_in_channel = mattermost_client.get_users_in_channel(std_mm_channel["id"]) if std_mm_channel else []
    std_mm_channel_name_for_log = std_mm_channel.get("display_name") if std_mm_channel else std_mm_channel_name

    adm_mm_users_in_channel = []
    if admin_config:
        adm_mm_channel_name = admin_config.get("mattermost_channel_name_pattern", "{base_name} Admin").format(base_name=base_name)
        adm_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(adm_mm_channel_name))
        if adm_mm_channel:
            adm_mm_users_in_channel = mattermost_client.get_users_in_channel(adm_mm_channel["id"])

    mm_users_for_services = {}
    for mm_user in std_mm_users_in_channel:
        email = mm_user.get("email", "").lower()
        if email:
            mm_users_for_services[email] = {"username": mm_user.get("username"), "mm_user_id": mm_user.get("id"), "is_admin_channel_member": False}
    for mm_user in adm_mm_users_in_channel:
        email = mm_user.get("email", "").lower()
        if email:
            mm_users_for_services[email] = {"username": mm_user.get("username"), "mm_user_id": mm_user.get("id"), "is_admin_channel_member": True}

    # Service-specific logic
    service_registry = {
        "authentik": {
            "client": clients.get("authentik"),
            "sync_function": _sync_authentik_for_entity,
            "config": {"standard": std_config, "admin": admin_config},
        },
        "outline": {
            "client": clients.get("outline"),
            "sync_function": _sync_outline_for_entity,
            "config": entity_config.get("outline"),
        },
        "brevo": {
            "client": clients.get("brevo"),
            "sync_function": _sync_brevo_for_entity,
            "config": entity_config.get("brevo"),
        },
        "nocodb": {
            "client": clients.get("nocodb"),
            "sync_function": _sync_nocodb_for_entity,
            "config": entity_config.get("nocodb"),
        },
        "vaultwarden": {
            "client": clients.get("vaultwarden"),
            "sync_function": _sync_vaultwarden_for_entity,
            "config": entity_config.get("vaultwarden"),
        },
    }

    for service_name, service_data in service_registry.items():
        if service_name not in skip_services and service_data["client"] and service_data["config"]:
            results.extend(service_data["sync_function"](
                service_data["client"],
                mattermost_client,
                base_name,
                service_data["config"],
                all_authentik_groups_by_name,
                email_to_authentik_user_pk_map,
                std_mm_users_in_channel,
                adm_mm_users_in_channel,
                mm_users_for_services,
                std_mm_channel_name_for_log,
                perform_deletions,
                entity_key,
            ))

    logging.info(f"Finished sync for entity '{base_name}'. Total results: {len(results)}")
    return results








async def orchestrate_group_synchronization(
    clients: dict,
    mm_team_id: str,
    perform_deletions: bool = True,
    sync_mode: str = "FULL_SYNC",
    skip_services: list[str] | None = None,
) -> tuple[bool, list[dict]]:
    authentik_client = clients.get("authentik")
    mattermost_client = clients.get("mattermost")
    outline_client = clients.get("outline")
    brevo_client = clients.get("brevo")
    nocodb_client = clients.get("nocodb")
    vaultwarden_client = clients.get("vaultwarden")
    skip_services = skip_services or []
    logging.info(
        f"Starting group synchronization task (async)... "
        f"(Perform Deletions: {perform_deletions}, Sync Mode: {sync_mode}, Skip Services: {skip_services})"
    )
    detailed_results = []

    if sync_mode not in ["MM_TO_TOOLS", "TOOLS_TO_MM", "FULL_SYNC"]:
        logging.error(f"Invalid sync_mode: {sync_mode}. Must be one of MM_TO_TOOLS, TOOLS_TO_MM, FULL_SYNC.")
        return False, [
            {
                "service": "ORCHESTRATOR",
                "target_resource_name": "N/A",
                "status": SyncStatus.FAILURE.value,
                "action": "INVALID_SYNC_MODE",
                "error_message": f"Invalid sync_mode: {sync_mode}",
            }
        ]

    # Client checks
    if not authentik_client:
        logging.error("Authentik client not provided to orchestrator. Authentik sync will be skipped.")
    if not mattermost_client:
        logging.error("Mattermost client not provided to orchestrator. Cannot proceed with core logic.")
        return False, detailed_results
    if not mm_team_id:
        logging.error("Mattermost Team ID not provided to orchestrator. Cannot proceed.")
        return False, detailed_results

    if not outline_client:
        logging.info("Outline client not provided. Outline synchronization will be skipped.")
    if not brevo_client:
        logging.info("Brevo client not provided. Brevo synchronization will be skipped.")
    if not nocodb_client:
        logging.info("NocoDB client not provided. NocoDB synchronization will be skipped.")
    if not vaultwarden_client:
        logging.info("Vaultwarden client not provided. Vaultwarden synchronization will be skipped.")

    _, email_to_auth_pk_map = get_all_authentik_groups_and_user_map(authentik_client)
    if not email_to_auth_pk_map and authentik_client:  # Only warn if client was available
        logging.warning(
            "Authentik email-to-user-PK map is empty. Authentik sync operations might not find users effectively."
        )

    all_auth_groups_by_name = {}
    entities_to_process = {}

    if sync_mode == "FULL_SYNC":
        logging.info("Sync Mode: FULL_SYNC. Discovering entities from Authentik groups...")
        all_auth_groups_list = []
        if authentik_client:
            all_auth_groups_list, _ = authentik_client.get_groups_with_users()
            if not all_auth_groups_list:
                logging.info("No Authentik groups found or an error occurred during fetching for discovery.")
            all_auth_groups_by_name = {g["name"]: g for g in all_auth_groups_list}
        else:
            logging.warning("Authentik client not available for FULL_SYNC discovery.")
            all_auth_groups_by_name = {}

        if not all_auth_groups_list and authentik_client:
            logging.info("No Authentik groups found to process for FULL_SYNC. Synchronization might be limited.")

        for auth_group_name_iter in all_auth_groups_by_name.keys():
            found_entity_key_auth, current_base_name_auth = _map_auth_group_to_entity_and_base_name(
                auth_group_name_iter, config.PERMISSIONS_MATRIX
            )
            if found_entity_key_auth and current_base_name_auth:
                entity_tuple = (found_entity_key_auth, current_base_name_auth)
                if entity_tuple not in entities_to_process:
                    entities_to_process[entity_tuple] = config.PERMISSIONS_MATRIX[found_entity_key_auth]
            else:
                logging.debug(
                    f"Authentik group '{auth_group_name_iter}' did not map to a known entity pattern for FULL_SYNC."
                )

    elif sync_mode == "MM_TO_TOOLS":
        logging.info("Sync Mode: MM_TO_TOOLS. Discovering entities based on Mattermost channels...")
        mm_channels = mattermost_client.get_channels_for_team(mm_team_id)
        if not mm_channels:
            logging.warning(
                "No Mattermost channels found for the team. Cannot discover entities for MM_TO_TOOLS sync."
            )
            return True, detailed_results

        for channel in mm_channels:
            channel_name = channel.get("name")
            channel_display_name = channel.get("display_name")
            found_entity_key_mm, current_base_name_mm = _map_mm_channel_to_entity_and_base_name(
                channel_name, channel_display_name, config.PERMISSIONS_MATRIX
            )
            if found_entity_key_mm and current_base_name_mm:
                entity_tuple = (found_entity_key_mm, current_base_name_mm)
                if entity_tuple not in entities_to_process:
                    entities_to_process[entity_tuple] = config.PERMISSIONS_MATRIX[found_entity_key_mm]
                    logging.info(
                        f"Discovered entity '{current_base_name_mm}' (type: {found_entity_key_mm}) from MM channel '{channel_display_name}' for MM_TO_TOOLS sync."
                    )
            else:
                logging.debug(
                    f"MM channel '{channel_display_name}' (slug: {channel_name}) did not map to a known entity pattern for MM_TO_TOOLS sync."
                )
    # TOOLS_TO_MM discovery is handled within its loop by _sync_entity_permissions_tools_to_mm

    if not entities_to_process and sync_mode not in ["TOOLS_TO_MM"]:
        logging.info(
            f"No entities found to process after discovery phase for sync_mode '{sync_mode}'. Synchronization finished."
        )
        return True, detailed_results

    if sync_mode == "TOOLS_TO_MM":
        logging.info("TOOLS_TO_MM sync mode: Iterating through configured services.")
        service_clients_map = {
            "AUTHENTIK": authentik_client,
            "OUTLINE": outline_client,
            "BREVO": brevo_client,
            "NOCODB": nocodb_client,
            "VAULTWARDEN": vaultwarden_client,
        }
        for service_name, service_client in service_clients_map.items():
            if service_client:
                service_results = await _sync_entity_permissions_tools_to_mm(
                    service_client=service_client,
                    service_name=service_name,
                    mattermost_client=mattermost_client,
                    mm_team_id=mm_team_id,
                    email_to_authentik_user_pk_map=email_to_auth_pk_map if service_name == "AUTHENTIK" else None,
                    perform_deletions=perform_deletions,
                    permissions_matrix=config.PERMISSIONS_MATRIX,
                    skip_services=skip_services,
                )
                detailed_results.extend(service_results)
            else:
                logging.info(f"Service client for {service_name} not configured, skipping for TOOLS_TO_MM sync.")
    else:  # For FULL_SYNC and MM_TO_TOOLS
        clients = {
            "authentik": authentik_client,
            "mattermost": mattermost_client,
            "outline": outline_client,
            "brevo": brevo_client,
            "nocodb": nocodb_client,
            "vaultwarden": vaultwarden_client,
        }
        for (entity_key, base_name), entity_config_to_use in entities_to_process.items():
            logging.info(
                f"Orchestrating sync for entity: {entity_key}, base_name: {base_name}, "
                f"sync_mode: {sync_mode}, perform_deletions: {perform_deletions}"
            )
            entity_sync_results = sync_entity_permissions(
                clients,
                mm_team_id,
                base_name,
                entity_key,
                entity_config_to_use,
                all_auth_groups_by_name,
                email_to_auth_pk_map,
                perform_deletions,
                skip_services=skip_services,
            )
            detailed_results.extend(entity_sync_results)

    log_msg = (
        f"Synchronization task completed. Mode: {sync_mode}, "
        f"deletions: {perform_deletions}, skip_services: {skip_services}). "
        f"Processed {len(entities_to_process) if sync_mode != 'TOOLS_TO_MM' else 'N/A (TOOLS_TO_MM)'} unique entities. "
        f"Total individual operations/results reported: {len(detailed_results)}."
    )
    logging.info(log_msg)
    return True, detailed_results


async def _sync_entity_permissions_tools_to_mm(
    service_client: object,
    service_name: str,
    mattermost_client: "MattermostClient",
    mm_team_id: str,
    email_to_authentik_user_pk_map: Optional[dict],
    perform_deletions: bool,
    permissions_matrix: dict,
    skip_services: list[str] | None,
) -> list[dict]:
    results = []
    logging.info(f"Starting TOOLS_TO_MM sync for service: {service_name}")

    if service_name.lower() in (skip_services or []):
        logging.info(f"Skipping {service_name} sync for TOOLS_TO_MM as per skip_services.")
        return results

    if service_name == "AUTHENTIK":
        authentik_client = service_client
        all_auth_groups, _ = authentik_client.get_groups_with_users()
        if not all_auth_groups:
            logging.warning("TOOLS_TO_MM: No Authentik groups found to sync.")
            return results

        for group in all_auth_groups:
            entity_key, base_name = _map_auth_group_to_entity_and_base_name(group.get("name"), permissions_matrix)
            if not entity_key or not base_name:
                logging.debug(
                    f"TOOLS_TO_MM: Authentik group '{group.get('name')}' did not map to an entity. Skipping."
                )
                continue

            logging.info(
                f"TOOLS_TO_MM: Processing Authentik group '{group.get('name')}' for entity '{base_name}' ({entity_key})"
            )
            entity_config = permissions_matrix.get(entity_key, {})

            # Determine if the current Authentik group is an admin or standard group
            # This heuristic is simple and relies on naming convention. A more robust way would be to check against both patterns.
            admin_cfg = entity_config.get("admin", {})
            is_admin_group = False
            if admin_cfg and _extract_base_name(group.get("name"), admin_cfg.get("authentik_group_name_pattern", "")):
                is_admin_group = True

            _, std_mm_users, adm_mm_users = _get_mm_users_for_entity(
                mattermost_client, mm_team_id, base_name, entity_config
            )

            mm_users_for_this_group = adm_mm_users if is_admin_group else std_mm_users

            mm_user_emails = {user["email"].lower() for user in mm_users_for_this_group if "email" in user}

            auth_users = group.get("users_obj", [])
            for user in auth_users:
                user_email = user.get("email", "").lower()
                if user_email and user_email not in mm_user_emails:
                    # Check if user is excluded
                    if user.get("username") in config.EXCLUDED_USERS:
                        continue
                    results.append(
                        remove_user_from_authentik_group(
                            authentik_client,
                            group.get("pk"),
                            group.get("name"),
                            user.get("pk"),
                            user_email,
                            base_name,
                        )
                    )

    elif service_name == "OUTLINE":
        outline_client = service_client
        try:
            all_collections = outline_client.list_collections()
            if not all_collections:
                logging.warning("TOOLS_TO_MM: No Outline collections found to sync.")
                return results
        except (AttributeError, NotImplementedError):
            logging.error("`outline_client.list_collections()` method not implemented. Skipping Outline sync.")
            return results

        for collection in all_collections:
            collection_name = collection.get("name")
            collection_id = collection.get("id")
            entity_key, base_name = _map_outline_collection_to_entity_and_base_name(
                collection_name, permissions_matrix
            )

            if not entity_key or not base_name:
                continue

            entity_config = permissions_matrix.get(entity_key, {})
            mm_users_for_services, _, _ = _get_mm_users_for_entity(
                mattermost_client, mm_team_id, base_name, entity_config
            )

            mm_user_emails = {email.lower() for email in mm_users_for_services.keys()}

            outline_users_id = outline_client.get_collection_members(collection_id)
            for id in outline_users_id:
                user = outline_client.get_user_by_id(id)
                user_email = user.get("email", "").lower()
                if user_email and user_email not in mm_user_emails:
                    results.append(
                        _remove_user_from_outline_collection(
                            outline_client,
                            collection_id,
                            collection_name,
                            user["id"],
                            user_email,
                            base_name,
                        )
                    )

    elif service_name == "NOCODB":
        nocodb_client = service_client
        all_bases = nocodb_client.list_bases()
        if not all_bases:
            logging.warning("TOOLS_TO_MM: No NoCoDB bases found to sync.")
            return results

        for base in all_bases["list"]:
            base_title = base.get("title")
            base_id = base.get("id")
            entity_key, base_name = _map_nocodb_base_to_entity_and_base_name(base_title, permissions_matrix)

            if not entity_key or not base_name:
                continue

            entity_config = permissions_matrix.get(entity_key, {})
            mm_users_for_services, _, _ = _get_mm_users_for_entity(
                mattermost_client, mm_team_id, base_name, entity_config
            )
            mm_user_emails = {email.lower() for email in mm_users_for_services.keys()}

            nocodb_users = nocodb_client.list_base_users(base_id)
            for user in nocodb_users:
                user_email = user.get("email", "").lower()
                if user_email and user_email not in mm_user_emails:
                    results.append(
                        _remove_user_from_nocodb_base(
                            nocodb_client,
                            base_id,
                            base_title,
                            user["id"],
                            user_email,
                            base_name,
                        )
                    )

    elif service_name == "BREVO":
        # Brevo sync is handled by the existing _sync_single_brevo_list
        pass

    elif service_name == "VAULTWARDEN":
        vaultwarden_client = service_client
        all_collections = vaultwarden_client.get_collections_details()
        if not all_collections:
            logging.warning("TOOLS_TO_MM: No Vaultwarden collections found to sync.")
            return results
        rc_list, sout_list, err_list = vaultwarden_client.get_collections()
        rc_user_list, sout_user_list, err_user_list = vaultwarden_client.get_members()
        for collection in all_collections:
            collection_id = collection.get("id")

            collection_name = None
            if rc_list == 0:
                collection_name = vaultwarden_client.get_name_from_collections(collection_id, sout_list)
            else:
                logging.error(f"Failed to list collections using 'bw list collections': {err_list.strip()}")
            entity_key, base_name = _map_vaultwarden_collection_to_entity_and_base_name(
                collection_name, permissions_matrix
            )

            if not entity_key or not base_name:
                continue

            entity_config = permissions_matrix.get(entity_key, {})
            mm_users_for_services, _, _ = _get_mm_users_for_entity(
                mattermost_client, mm_team_id, base_name, entity_config
            )
            mm_user_emails = {email.lower() for email in mm_users_for_services.keys()}

            vaultwarden_users_by_collection = collection.get("users", [])
            users_to_keep = []
            for user in vaultwarden_users_by_collection:
                user_id = user.get("id")

                user_email = None
                if rc_user_list == 0:
                    user_email = vaultwarden_client.get_email_from_members(user_id, sout_user_list)
                else:
                    logging.error(f"Failed to list collections using 'bw list collections': {err_user_list.strip()}")

                if user_email and user_email in mm_user_emails:
                    users_to_keep.append(user)

            if len(users_to_keep) != len(vaultwarden_users_by_collection):
                payload = {
                    "users": users_to_keep,
                    "groups": collection.get("groups", []),
                    "externalId": collection.get("externalId"),
                    "name": collection.get("name"),
                }
                if vaultwarden_client.update_collection(collection_id, payload):
                    results.append(
                        {
                            "service": "VAULTWARDEN",
                            "target_resource_name": collection_name,
                            "status": SyncStatus.SUCCESS.value,
                            "action": VaultwardenAction.USER_REMOVED_FROM_COLLECTION.value,
                        }
                    )
                else:
                    results.append(
                        {
                            "service": "VAULTWARDEN",
                            "target_resource_name": collection_name,
                            "status": SyncStatus.FAILURE.value,
                            "action": VaultwardenAction.FAILED_TO_REMOVE_FROM_COLLECTION.value,
                        }
                    )
    return results








