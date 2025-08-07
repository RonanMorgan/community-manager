import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.user_right_manager import UserRightManager


class TestUserRightManager(unittest.TestCase):
    def setUp(self):
        self.mock_bot = MagicMock()
        self.mock_bot.mattermost_api_client = MagicMock()
        self.mock_bot.config = MagicMock()
        self.user_right_manager = UserRightManager(self.mock_bot)

    def test_is_admin_success(self):
        self.mock_bot.mattermost_api_client.get_user_roles.return_value = ["system_admin", "user"]
        result = asyncio.run(self.user_right_manager.is_admin("admin_user_id"))
        self.assertTrue(result)

    def test_is_admin_failure(self):
        self.mock_bot.mattermost_api_client.get_user_roles.return_value = ["user"]
        result = asyncio.run(self.user_right_manager.is_admin("normal_user_id"))
        self.assertFalse(result)

    def test_is_admin_no_client(self):
        self.user_right_manager.mattermost_api_client = None
        result = asyncio.run(self.user_right_manager.is_admin("user_id"))
        self.assertFalse(result)

    def test_is_channel_admin_success(self):
        self.mock_bot.mattermost_api_client.get_channel_by_id.return_value = {
            "name": "projet_test-projet-admin",
            "display_name": "Projet Test-Projet Admin",
        }
        self.mock_bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": "user_id_1"}]
        self.mock_bot.config.PERMISSIONS_MATRIX = {
            "PROJET": {
                "admin": {"mattermost_channel_name_pattern": "projet_{base_name} Admin"}
            }
        }

        with patch('app.user_right_manager._map_mm_channel_to_entity_and_base_name', return_value=('PROJET', 'test-projet', 'admin')):
            is_admin, entity_key, base_name = asyncio.run(
                self.user_right_manager.is_channel_admin("user_id_1", "channel_id_1")
            )

        self.assertTrue(is_admin)
        self.assertEqual(entity_key, "PROJET")
        self.assertEqual(base_name, "test-projet")

    def test_is_channel_admin_not_a_member(self):
        self.mock_bot.mattermost_api_client.get_channel_by_id.return_value = {
            "name": "projet_test-projet-admin",
            "display_name": "Projet Test-Projet Admin",
        }
        self.mock_bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": "other_user_id"}]
        self.mock_bot.config.PERMISSIONS_MATRIX = {
            "PROJET": {
                "admin": {"mattermost_channel_name_pattern": "projet_{base_name} Admin"}
            }
        }

        is_admin, entity_key, base_name = asyncio.run(
            self.user_right_manager.is_channel_admin("user_id_1", "channel_id_1")
        )
        self.assertFalse(is_admin)

    def test_is_channel_admin_not_an_admin_channel(self):
        self.mock_bot.mattermost_api_client.get_channel_by_id.return_value = {
            "name": "not-an-admin-channel",
            "display_name": "Not an Admin Channel",
        }
        self.mock_bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": "user_id_1"}]
        self.mock_bot.config.PERMISSIONS_MATRIX = {
            "PROJET": {
                "admin": {"mattermost_channel_name_pattern": "projet_{base_name} Admin"}
            }
        }

        with patch('libraries.group_sync_services._map_mm_channel_to_entity_and_base_name', return_value=(None, None)):
            is_admin, entity_key, base_name = asyncio.run(
                self.user_right_manager.is_channel_admin("user_id_1", "channel_id_1")
            )
        self.assertFalse(is_admin)


if __name__ == "__main__":
    unittest.main()
