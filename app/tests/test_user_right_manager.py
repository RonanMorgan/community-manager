from unittest.mock import MagicMock

import pytest

from app.user_right_manager import UserRightManager


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.mattermost_api_client = MagicMock()
    bot.config = MagicMock()
    return bot


@pytest.mark.asyncio
async def test_is_admin_true(mock_bot):
    mock_bot.mattermost_api_client.get_user_roles.return_value = ["system_admin"]
    user_right_manager = UserRightManager(mock_bot)
    assert await user_right_manager.is_admin("user_id") is True


@pytest.mark.asyncio
async def test_is_admin_false(mock_bot):
    mock_bot.mattermost_api_client.get_user_roles.return_value = ["system_user"]
    user_right_manager = UserRightManager(mock_bot)
    assert await user_right_manager.is_admin("user_id") is False


@pytest.mark.asyncio
async def test_is_channel_admin_true(mock_bot):
    mock_bot.mattermost_api_client.get_channel_by_id.return_value = {
        "name": "projet-test-admin",
        "display_name": "Projet Test Admin",
    }
    mock_bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": "user_id"}]
    mock_bot.config.PERMISSIONS_MATRIX = {
        "projet": {"admin": {"mattermost_channel_name_pattern": "projet-{base_name}-admin"}}
    }
    user_right_manager = UserRightManager(mock_bot)
    assert await user_right_manager.is_channel_admin("user_id", "channel_id") is True


@pytest.mark.asyncio
async def test_is_channel_admin_false_not_admin_channel(mock_bot):
    mock_bot.mattermost_api_client.get_channel_by_id.return_value = {
        "name": "projet-test",
        "display_name": "Projet Test",
    }
    mock_bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": "user_id"}]
    mock_bot.config.PERMISSIONS_MATRIX = {
        "projet": {"admin": {"mattermost_channel_name_pattern": "projet-{base_name}-admin"}}
    }
    user_right_manager = UserRightManager(mock_bot)
    assert await user_right_manager.is_channel_admin("user_id", "channel_id") is False


@pytest.mark.asyncio
async def test_is_channel_admin_false_not_member(mock_bot):
    mock_bot.mattermost_api_client.get_channel_by_id.return_value = {
        "name": "projet-test-admin",
        "display_name": "Projet Test Admin",
    }
    mock_bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": "other_user_id"}]
    mock_bot.config.PERMISSIONS_MATRIX = {
        "projet": {"admin": {"mattermost_channel_name_pattern": "projet-{base_name}-admin"}}
    }
    user_right_manager = UserRightManager(mock_bot)
    assert await user_right_manager.is_channel_admin("user_id", "channel_id") is False
