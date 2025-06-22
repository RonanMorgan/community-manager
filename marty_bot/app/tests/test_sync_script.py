import unittest
from unittest.mock import patch, MagicMock
import logging
import sys
import os

# Adjust path to import from the app and scripts directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.authentik_client import AuthentikClient
from app.mattermost_client import MattermostClient, slugify

# Import the script module itself to call its functions
# The functions will be called as sync_mm_authentik_groups.function_name
import scripts.sync_mm_authentik_groups as sync_mm_authentik_groups


class TestSyncScriptLogic(unittest.TestCase):

    def setUp(self):
        self.mock_auth_client_instance = MagicMock(spec=AuthentikClient)
        self.mock_mm_client_instance = MagicMock(spec=MattermostClient)
        self.test_mm_team_id_for_single_sync = "test_team_id_for_single_sync"

        # Suppress most logging during tests by default for cleaner output
        # This will be overridden by the script's own logging config if DEBUG is True
        logging.getLogger("scripts.sync_mm_authentik_groups").setLevel(logging.CRITICAL + 1)
        logging.getLogger("app.authentik_client").setLevel(logging.CRITICAL + 1)
        logging.getLogger("app.mattermost_client").setLevel(logging.CRITICAL + 1)

    # Tests for initialize_clients
    # We patch the config attributes directly in the namespace where initialize_clients will look them up.
    @patch("scripts.sync_mm_authentik_groups.MattermostClient")
    @patch("scripts.sync_mm_authentik_groups.AuthentikClient")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_initialize_clients_success(self, mock_config, MockAuthentikClient, MockMattermostClient):
        mock_config.AUTHENTIK_URL = "http://auth.example.com"
        mock_config.AUTHENTIK_TOKEN = "auth_token"
        mock_config.MATTERMOST_URL = "http://mm.example.com"
        mock_config.BOT_TOKEN = "mm_bot_token"
        mock_config.MATTERMOST_TEAM_ID = "mm_team_id"
        mock_config.DEBUG = False

        mock_auth_instance = MockAuthentikClient.return_value
        mock_mm_instance = MockMattermostClient.return_value

        auth_client, mm_client = sync_mm_authentik_groups.initialize_clients()

        MockAuthentikClient.assert_called_once_with("http://auth.example.com", "auth_token")
        MockMattermostClient.assert_called_once_with("http://mm.example.com", "mm_bot_token", "mm_team_id")
        self.assertEqual(auth_client, mock_auth_instance)
        self.assertEqual(mm_client, mock_mm_instance)

    @patch("scripts.sync_mm_authentik_groups.MattermostClient")
    @patch("scripts.sync_mm_authentik_groups.AuthentikClient")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_initialize_clients_auth_missing_config(self, mock_config, MockAuthentikClient, MockMattermostClient):
        mock_config.AUTHENTIK_URL = None
        mock_config.AUTHENTIK_TOKEN = None
        mock_config.MATTERMOST_URL = "http://mm.example.com"
        mock_config.BOT_TOKEN = "mm_bot_token"
        mock_config.MATTERMOST_TEAM_ID = "mm_team_id"
        mock_config.DEBUG = False

        mock_mm_instance = MockMattermostClient.return_value
        auth_client, mm_client = sync_mm_authentik_groups.initialize_clients()

        self.assertIsNone(auth_client)
        MockAuthentikClient.assert_not_called()
        self.assertEqual(mm_client, mock_mm_instance)
        MockMattermostClient.assert_called_once_with("http://mm.example.com", "mm_bot_token", "mm_team_id")

    @patch("scripts.sync_mm_authentik_groups.MattermostClient")
    @patch("scripts.sync_mm_authentik_groups.AuthentikClient")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_initialize_clients_mm_missing_config(self, mock_config, MockAuthentikClient, MockMattermostClient):
        mock_config.AUTHENTIK_URL = "http://auth.example.com"
        mock_config.AUTHENTIK_TOKEN = "auth_token"
        mock_config.MATTERMOST_URL = None
        mock_config.BOT_TOKEN = None
        mock_config.MATTERMOST_TEAM_ID = None
        mock_config.DEBUG = False

        mock_auth_instance = MockAuthentikClient.return_value
        auth_client, mm_client = sync_mm_authentik_groups.initialize_clients()

        self.assertIsNone(mm_client)
        MockMattermostClient.assert_not_called()
        self.assertEqual(auth_client, mock_auth_instance)
        MockAuthentikClient.assert_called_once_with("http://auth.example.com", "auth_token")

    # Tests for get_all_authentik_groups_and_user_map (passes client as arg)
    def test_get_all_authentik_groups_and_user_map_passthrough(self):
        mock_groups_data = [{"name": "group1"}]
        mock_email_map_data = {"email@example.com": "pk1"}
        self.mock_auth_client_instance.get_groups_with_users.return_value = (mock_groups_data, mock_email_map_data)

        groups, email_map = sync_mm_authentik_groups.get_all_authentik_groups_and_user_map(
            self.mock_auth_client_instance
        )

        self.mock_auth_client_instance.get_groups_with_users.assert_called_once()
        self.assertEqual(groups, mock_groups_data)
        self.assertEqual(email_map, mock_email_map_data)

    # Tests for sync_single_authentik_group_with_mattermost (passes clients and team_id as args)
    def test_sync_single_group_user_added_successfully(self):
        auth_group = {"pk": "auth_g_pk1", "name": "Dev Team Sync", "users": []}
        email_map = {"dev1@example.com": "auth_user_pk1"}
        mm_users = [{"email": "dev1@example.com", "id": "mm_id_1"}]
        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id1",
            "display_name": "Dev Team Sync",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = mm_users
        self.mock_auth_client_instance.add_user_to_group.return_value = True

        sync_mm_authentik_groups.sync_single_authentik_group_with_mattermost(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            self.test_mm_team_id_for_single_sync,
            auth_group,
            email_map,
        )
        expected_slug = slugify(auth_group["name"])
        self.mock_mm_client_instance.get_channel_by_name.assert_called_once_with(
            self.test_mm_team_id_for_single_sync, expected_slug
        )
        self.mock_mm_client_instance.get_users_in_channel.assert_called_once_with("mm_chan_id1")
        self.mock_auth_client_instance.add_user_to_group.assert_called_once_with("auth_g_pk1", "auth_user_pk1")

    def test_sync_single_group_user_already_in_group(self):
        auth_group = {"pk": "auth_g_pk1", "name": "Dev Team Sync", "users": ["auth_user_pk1"]}
        email_map = {"dev1@example.com": "auth_user_pk1"}
        mm_users = [{"email": "dev1@example.com", "id": "mm_id_1"}]
        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id1",
            "display_name": "Dev Team Sync",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = mm_users
        sync_mm_authentik_groups.sync_single_authentik_group_with_mattermost(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            self.test_mm_team_id_for_single_sync,
            auth_group,
            email_map,
        )
        self.mock_auth_client_instance.add_user_to_group.assert_not_called()

    def test_sync_single_group_mm_user_not_in_authentik_map(self):
        auth_group = {"pk": "auth_g_pk1", "name": "Dev Team Sync", "users": []}
        email_map = {"another_user@example.com": "auth_user_pk_X"}
        mm_users = [{"email": "dev1@example.com", "id": "mm_id_1"}]
        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id1",
            "display_name": "Dev Team Sync",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = mm_users
        sync_mm_authentik_groups.sync_single_authentik_group_with_mattermost(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            self.test_mm_team_id_for_single_sync,
            auth_group,
            email_map,
        )
        self.mock_auth_client_instance.add_user_to_group.assert_not_called()

    def test_sync_single_group_mm_channel_not_found(self):
        auth_group = {"pk": "auth_g_pk1", "name": "NoChannelHere", "users": []}
        email_map = {}
        self.mock_mm_client_instance.get_channel_by_name.return_value = None
        sync_mm_authentik_groups.sync_single_authentik_group_with_mattermost(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            self.test_mm_team_id_for_single_sync,
            auth_group,
            email_map,
        )
        self.mock_mm_client_instance.get_users_in_channel.assert_not_called()
        self.mock_auth_client_instance.add_user_to_group.assert_not_called()

    def test_sync_single_group_no_users_in_mm_channel(self):
        auth_group = {"pk": "auth_g_pk1", "name": "EmptyChannel", "users": []}
        email_map = {}
        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id_empty",
            "display_name": "EmptyChannel",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = []
        sync_mm_authentik_groups.sync_single_authentik_group_with_mattermost(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            self.test_mm_team_id_for_single_sync,
            auth_group,
            email_map,
        )
        self.mock_auth_client_instance.add_user_to_group.assert_not_called()

    # Tests for main_sync_logic
    @patch("scripts.sync_mm_authentik_groups.sync_single_authentik_group_with_mattermost")
    @patch("scripts.sync_mm_authentik_groups.get_all_authentik_groups_and_user_map")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_main_sync_logic_orchestration(
        self, mock_script_config, mock_init_clients, mock_get_auth_groups_map, mock_sync_single
    ):
        # Configure the mock_script_config that main_sync_logic will see
        mock_script_config.MATTERMOST_TEAM_ID = "mm_team1_orchestration"
        # These are needed because initialize_clients (though mocked) might be called by main_sync_logic
        # and its internal logging uses config.DEBUG. Also, main_sync_logic itself might have config checks.
        mock_script_config.AUTHENTIK_URL = "http://auth.example.com"
        mock_script_config.AUTHENTIK_TOKEN = "auth_token"
        mock_script_config.MATTERMOST_URL = "http://mm.example.com"
        mock_script_config.BOT_TOKEN = "mm_bot_token"
        mock_script_config.DEBUG = False

        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_init_clients.return_value = (mock_auth_client, mock_mm_client)

        mock_groups_list = [{"name": "group1", "pk": "g1"}, {"name": "group2", "pk": "g2"}]
        mock_email_pk_map = {"user1@example.com": "upk1"}
        mock_get_auth_groups_map.return_value = (mock_groups_list, mock_email_pk_map)

        sync_mm_authentik_groups.main_sync_logic()

        mock_init_clients.assert_called_once()
        mock_get_auth_groups_map.assert_called_once_with(mock_auth_client)
        self.assertEqual(mock_sync_single.call_count, 2)
        mock_sync_single.assert_any_call(
            mock_auth_client, mock_mm_client, "mm_team1_orchestration", mock_groups_list[0], mock_email_pk_map
        )
        mock_sync_single.assert_any_call(
            mock_auth_client, mock_mm_client, "mm_team1_orchestration", mock_groups_list[1], mock_email_pk_map
        )

    @patch("scripts.sync_mm_authentik_groups.get_all_authentik_groups_and_user_map")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_main_sync_logic_auth_client_init_fails(self, mock_script_config, mock_init_clients, mock_get_groups):
        mock_script_config.AUTHENTIK_URL = None  # This will make initialize_clients return None for auth_client
        mock_script_config.AUTHENTIK_TOKEN = None
        mock_script_config.MATTERMOST_URL = "http://mm.example.com"
        mock_script_config.BOT_TOKEN = "mm_bot_token"
        mock_script_config.MATTERMOST_TEAM_ID = "mm_team1"
        mock_script_config.DEBUG = False

        # If we let the real initialize_clients run (by not patching it), it will see the mocked config
        # and return (None, <mm_client_instance_or_mock>).
        # Then main_sync_logic should exit early.

        # To make this test more robust, we ensure initialize_clients is called and control its output
        # to specifically test main_sync_logic's reaction to a None auth_client.
        mock_mm_client_inst = MagicMock(spec=MattermostClient)
        mock_init_clients.return_value = (None, mock_mm_client_inst)

        sync_mm_authentik_groups.main_sync_logic()
        mock_init_clients.assert_called_once()
        mock_get_groups.assert_not_called()

    @patch("scripts.sync_mm_authentik_groups.sync_single_authentik_group_with_mattermost")
    @patch("scripts.sync_mm_authentik_groups.get_all_authentik_groups_and_user_map")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_main_sync_logic_no_groups_found(
        self, mock_script_config, mock_init_clients, mock_get_auth_groups_map, mock_sync_single
    ):
        mock_script_config.AUTHENTIK_URL = "http://auth.example.com"
        mock_script_config.AUTHENTIK_TOKEN = "auth_token"
        mock_script_config.MATTERMOST_URL = "http://mm.example.com"
        mock_script_config.BOT_TOKEN = "mm_bot_token"
        mock_script_config.MATTERMOST_TEAM_ID = "mm_team1"
        mock_script_config.DEBUG = False

        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_init_clients.return_value = (mock_auth_client, mock_mm_client)
        mock_get_auth_groups_map.return_value = ([], {})  # No groups

        sync_mm_authentik_groups.main_sync_logic()
        mock_init_clients.assert_called_once()
        mock_get_auth_groups_map.assert_called_once_with(mock_auth_client)
        mock_sync_single.assert_not_called()


if __name__ == "__main__":
    unittest.main()
