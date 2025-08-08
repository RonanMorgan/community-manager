# libraries/group_sync_services.py
# This module will contain core business logic for services like group synchronization.
# It will be used by both the bot (app) and standalone scripts.

import logging
import os
import sys
import config
from app.enums import SyncStatus
from libraries.services.authentik import AuthentikService
from libraries.services.brevo import BrevoService
from libraries.services.nocodb import NocoDBService
from libraries.services.outline import OutlineService
from libraries.services.vaultwarden import VaultwardenService
from libraries.services.mattermost import (
    _map_mm_channel_to_entity_and_base_name,
)
from libraries.utils import check_clients

from libraries.services.mattermost import slugify

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


async def orchestrate_group_synchronization(
    clients: dict,
    mm_team_id: str,
    sync_mode: str = "WITH_AUTHENTIK",
    skip_services: list[str] | None = None,
) -> tuple[bool, list[dict]]:
    authentik_client = clients.get("authentik")
    mattermost_client = clients.get("mattermost")
    skip_services = skip_services or []
    logging.info(
        f"Starting group synchronization task (async)... " f"(Sync Mode: {sync_mode}, Skip Services: {skip_services})"
    )
    detailed_results = []

    if sync_mode not in ["MM_TO_TOOLS", "WITH_AUTHENTIK"]:
        logging.error(f"Invalid sync_mode: {sync_mode}. Must be one of MM_TO_TOOLS, WITH_AUTHENTIK.")
        return False, [
            {
                "service": "ORCHESTRATOR",
                "target_resource_name": "N/A",
                "status": SyncStatus.FAILURE.value,
                "action": "INVALID_SYNC_MODE",
                "error_message": f"Invalid sync_mode: {sync_mode}",
            }
        ]

    if not mattermost_client:
        logging.error("Mattermost client not provided to orchestrator. Cannot proceed with core logic.")
        return False, detailed_results
    if not mm_team_id:
        logging.error("Mattermost Team ID not provided to orchestrator. Cannot proceed.")
        return False, detailed_results

    check_clients(clients)

    all_auth_groups_by_name = {}
    entities_to_process = {}
    authentik_service = AuthentikService(
        clients.get("authentik"), mattermost_client, config.PERMISSIONS_MATRIX, mm_team_id
    )
    all_auth_groups_list = []
    if authentik_client:
        all_auth_groups_list, _ = authentik_client.get_groups_with_users()
        if not all_auth_groups_list:
            logging.info("No Authentik groups found or an error occurred during fetching for discovery.")
        all_auth_groups_by_name = {g["name"]: g for g in all_auth_groups_list}
    else:
        logging.warning("Authentik client not available for WITH_AUTHENTIK discovery.")
        all_auth_groups_by_name = {}

    if sync_mode == "WITH_AUTHENTIK":
        logging.info("Sync Mode: WITH_AUTHENTIK. Discovering entities from Authentik groups...")

        if not all_auth_groups_list and authentik_client:
            logging.info("No Authentik groups found to process for WITH_AUTHENTIK. Synchronization might be limited.")

        for auth_group_name_iter in all_auth_groups_by_name.keys():
            found_entity_key_auth, current_base_name_auth = authentik_service._map_auth_group_to_entity_and_base_name(
                auth_group_name_iter, config.PERMISSIONS_MATRIX
            )
            if found_entity_key_auth and current_base_name_auth:
                entity_tuple = (found_entity_key_auth, current_base_name_auth)
                if entity_tuple not in entities_to_process:
                    entities_to_process[entity_tuple] = config.PERMISSIONS_MATRIX[found_entity_key_auth]
            else:
                logging.debug(
                    f"Authentik group '{auth_group_name_iter}' did not map to a known entity pattern for WITH_AUTHENTIK."
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

    if not entities_to_process:
        logging.info(
            f"No entities found to process after discovery phase for sync_mode '{sync_mode}'. Synchronization finished."
        )
        return True, detailed_results

    services = [
        AuthentikService(clients.get("authentik"), mattermost_client, config.PERMISSIONS_MATRIX, mm_team_id),
        OutlineService(clients.get("outline"), mattermost_client, config.PERMISSIONS_MATRIX, mm_team_id),
        BrevoService(clients.get("brevo"), mattermost_client, config.PERMISSIONS_MATRIX, mm_team_id),
        NocoDBService(clients.get("nocodb"), mattermost_client, config.PERMISSIONS_MATRIX, mm_team_id),
        VaultwardenService(clients.get("vaultwarden"), mattermost_client, config.PERMISSIONS_MATRIX, mm_team_id),
    ]

    for (entity_key, base_name), entity_config in entities_to_process.items():
        logging.info(
            f"Orchestrating sync for entity: {entity_key}, base_name: {base_name}, " f"sync_mode: {sync_mode}"
        )

        # Common user and channel data preparation
        std_config = entity_config.get("standard", {})
        admin_config = entity_config.get("admin")
        std_mm_channel_name = std_config.get("mattermost_channel_name_pattern", "{base_name}").format(
            base_name=base_name
        )
        std_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(std_mm_channel_name))
        std_mm_users_in_channel = (
            mattermost_client.get_users_in_channel(std_mm_channel["id"]) if std_mm_channel else []
        )
        std_mm_channel_name_for_log = std_mm_channel.get("display_name") if std_mm_channel else std_mm_channel_name

        adm_mm_users_in_channel = []
        if admin_config:
            adm_mm_channel_name = admin_config.get("mattermost_channel_name_pattern", "{base_name} Admin").format(
                base_name=base_name
            )
            adm_mm_channel = mattermost_client.get_channel_by_name(mm_team_id, slugify(adm_mm_channel_name))
            if adm_mm_channel:
                adm_mm_users_in_channel = mattermost_client.get_users_in_channel(adm_mm_channel["id"])

        mm_users_for_services = {}
        for mm_user in std_mm_users_in_channel:
            email = mm_user.get("email", "").lower()
            if email:
                mm_users_for_services[email] = {
                    "username": mm_user.get("username"),
                    "mm_user_id": mm_user.get("id"),
                    "is_admin_channel_member": False,
                }
        for mm_user in adm_mm_users_in_channel:
            email = mm_user.get("email", "").lower()
            if email:
                mm_users_for_services[email] = {
                    "username": mm_user.get("username"),
                    "mm_user_id": mm_user.get("id"),
                    "is_admin_channel_member": True,
                }

        for service in services:
            if service.client and service.SERVICE_NAME.lower() not in skip_services:
                service_results = await service.group_sync(
                    base_name,
                    entity_config,
                    all_auth_groups_by_name,
                    std_mm_users_in_channel,
                    adm_mm_users_in_channel,
                    mm_users_for_services,
                    std_mm_channel_name_for_log,
                    entity_key,
                )
                detailed_results.extend(service_results)

    log_msg = (
        f"Synchronization task completed. Mode: {sync_mode}, "
        f"skip_services: {skip_services}). "
        f"Processed {len(entities_to_process)} unique entities. "
        f"Total individual operations/results reported: {len(detailed_results)}."
    )
    logging.info(log_msg)
    return True, detailed_results


async def differential_sync(
    clients: dict,
    mm_team_id: str,
    skip_services: list[str] | None = None,
) -> tuple[bool, list[dict]]:
    mattermost_client = clients.get("mattermost")
    skip_services = skip_services or []
    logging.info(f"Starting group diff synchronization task (async)... " f"Skip Services: {skip_services})")
    detailed_results = []

    if not mattermost_client:
        logging.error("Mattermost client not provided to orchestrator. Cannot proceed with core logic.")
        return False, detailed_results
    if not mm_team_id:
        logging.error("Mattermost Team ID not provided to orchestrator. Cannot proceed.")
        return False, detailed_results

    check_clients(clients)

    logging.info("Pre-fetching all Mattermost channel members for differential sync...")
    all_mm_channels = mattermost_client.get_channels_for_team(mm_team_id)
    mm_channel_members = {}
    for channel in all_mm_channels:
        channel_id = channel.get("id")
        # Check if channel is relevant to any service based on permissions matrix
        entity_key, base_name = _map_mm_channel_to_entity_and_base_name(
            channel.get("name"), channel.get("display_name"), config.PERMISSIONS_MATRIX
        )
        if entity_key and base_name:
            logging.debug(
                f"Channel '{channel.get('display_name')}' maps to entity '{base_name}' ({entity_key}). Fetching members."
            )
            mm_channel_members[channel_id] = mattermost_client.get_users_in_channel(channel_id)
        else:
            logging.debug(
                f"Channel '{channel.get('display_name')}' does not map to a configured entity. Skipping member fetch."
            )

    logging.info("Iterating through configured services.")
    services = [
        AuthentikService(clients.get("authentik"), mattermost_client, config.PERMISSIONS_MATRIX, mm_team_id),
        OutlineService(clients.get("outline"), mattermost_client, config.PERMISSIONS_MATRIX, mm_team_id),
        BrevoService(clients.get("brevo"), mattermost_client, config.PERMISSIONS_MATRIX, mm_team_id),
        NocoDBService(clients.get("nocodb"), mattermost_client, config.PERMISSIONS_MATRIX, mm_team_id),
        VaultwardenService(clients.get("vaultwarden"), mattermost_client, config.PERMISSIONS_MATRIX, mm_team_id),
    ]

    for service in services:
        if service.client and service.SERVICE_NAME.lower() not in skip_services:
            service_results = await service.differential_sync(mm_channel_members)
            detailed_results.extend(service_results)
        else:
            logging.info(f"Service client for {service.SERVICE_NAME} not configured, skipping for differential sync.")

    log_msg = (
        f"Differential Synchronization task completed., "
        f"skip_services: {skip_services}). "
        f"Total individual operations/results reported: {len(detailed_results)}."
    )
    logging.info(log_msg)
    return True, detailed_results
