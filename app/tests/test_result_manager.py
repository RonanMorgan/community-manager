import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.enums import SyncStatus
from app.result_manager import ResultManager


@pytest.fixture
def mock_bot():
    """Fixture to create a mock bot with a mock envoyer_message method."""
    bot = MagicMock()
    bot.envoyer_message = MagicMock()
    return bot


@pytest.fixture
def result_manager(mock_bot):
    """Fixture to create a ResultManager instance with a mock bot."""
    return ResultManager(mock_bot)


@pytest.mark.asyncio
async def test_format_and_send_sync_results_groups_correctly(result_manager, mock_bot):
    """
    Tests that results are correctly grouped by service and resource,
    and that a separate message is sent for each group.
    """
    detailed_results = [
        # Group 1: AUTHENTIK, Resource1
        {
            "service": "AUTHENTIK",
            "target_resource_name": "Resource1",
            "action": "USER_ADDED",
            "status": SyncStatus.SUCCESS.value,
            "mm_username": "user1",
        },
        {
            "service": "AUTHENTIK",
            "target_resource_name": "Resource1",
            "action": "USER_REMOVED",
            "status": SyncStatus.FAILURE.value,
            "mm_username": "user2",
            "error_message": "API Error",
        },
        # Group 2: OUTLINE, Resource2
        {
            "service": "OUTLINE",
            "target_resource_name": "Resource2",
            "action": "USER_ADDED",
            "status": SyncStatus.SUCCESS.value,
            "mm_username": "user3",
        },
    ]

    await result_manager.format_and_send_sync_results("channel_id", "post_id", detailed_results)

    assert mock_bot.envoyer_message.call_count == 3  # 2 groups + 1 final summary

    # Check first group's message
    call_args_group1 = mock_bot.envoyer_message.call_args_list[0][0][1]
    assert "Rapport pour `AUTHENTIK` sur `Resource1`" in call_args_group1
    assert "Action : `USER_ADDED`" in call_args_group1
    assert ":white_check_mark: **Statut :** SUCCESS" in call_args_group1
    assert "Utilisateurs (1) :** `user1`" in call_args_group1
    assert "Action : `USER_REMOVED`" in call_args_group1
    assert ":x: **Statut :** FAILURE" in call_args_group1
    assert "Utilisateurs (1) :** `user2`" in call_args_group1
    assert "Erreurs/Raisons :**\n  - `API Error`" in call_args_group1

    # Check second group's message
    call_args_group2 = mock_bot.envoyer_message.call_args_list[1][0][1]
    assert "Rapport pour `OUTLINE` sur `Resource2`" in call_args_group2
    assert "Action : `USER_ADDED`" in call_args_group2
    assert "Utilisateurs (1) :** `user3`" in call_args_group2

    # Check final summary message
    call_args_summary = mock_bot.envoyer_message.call_args_list[2][0][1]
    assert "Résumé global de la synchronisation" in call_args_summary
    assert "Opérations réussies : 2" in call_args_summary
    assert "Problèmes/omissions : 1" in call_args_summary


@pytest.mark.asyncio
async def test_aggregates_multiple_users_for_same_action_and_status(result_manager, mock_bot):
    """
    Tests that multiple users for the same action and status are aggregated
    into a single line in the report.
    """
    detailed_results = [
        {
            "service": "VAULTWARDEN",
            "target_resource_name": "CollectionA",
            "action": "USER_INVITED",
            "status": SyncStatus.SUCCESS.value,
            "mm_username": "user_a",
        },
        {
            "service": "VAULTWARDEN",
            "target_resource_name": "CollectionA",
            "action": "USER_INVITED",
            "status": SyncStatus.SUCCESS.value,
            "mm_username": "user_b",
        },
        {
            "service": "VAULTWARDEN",
            "target_resource_name": "CollectionA",
            "action": "USER_INVITED",
            "status": SyncStatus.FAILURE.value,
            "mm_username": "user_c",
            "error_message": "Invitation failed",
        },
    ]

    await result_manager.format_and_send_sync_results("channel_id", "post_id", detailed_results)

    assert mock_bot.envoyer_message.call_count == 2  # 1 group + 1 final summary

    report_call = mock_bot.envoyer_message.call_args_list[0][0][1]
    assert "Rapport pour `VAULTWARDEN` sur `CollectionA`" in report_call
    assert "Action : `USER_INVITED`" in report_call
    assert "Utilisateurs (2) :** `user_a`, `user_b`" in report_call
    assert "Utilisateurs (1) :** `user_c`" in report_call
    assert "Erreurs/Raisons :**\n  - `Invitation failed`" in report_call
