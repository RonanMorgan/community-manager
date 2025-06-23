import unittest
from unittest.mock import patch, MagicMock
import logging
import sys
import os

# Adjust path to import from the project root directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Client classes for type hinting and MagicMock spec
from clients.authentik_client import AuthentikClient
from clients.mattermost_client import MattermostClient  # slugify is used by library code

# Functions/modules to be tested
import scripts.sync_mm_authentik_groups as script_module
from libraries.group_sync_services import (
    get_all_authentik_groups_and_user_map,
    sync_single_authentik_group_with_mattermost,
    orchestrate_authentik_mattermost_sync,
)


class TestSyncLogic(unittest.TestCase):

    def setUp(self):
        self.mock_auth_client_instance = MagicMock(spec=AuthentikClient)
        self.mock_mm_client_instance = MagicMock(spec=MattermostClient)
        self.test_mm_team_id = "test_team_id"

        # Suppress most logging during tests
        loggers_to_suppress = [
            "scripts.sync_mm_authentik_groups",
            "libraries.group_sync_services",
            "clients.authentik_client",  # Updated path
            "clients.mattermost_client",  # Updated path
        ]
        for logger_name in loggers_to_suppress:
            logging.getLogger(logger_name).setLevel(logging.CRITICAL + 1)

    # --- Tests for initialize_clients (from scripts.sync_mm_authentik_groups) ---
    @patch("scripts.sync_mm_authentik_groups.MattermostClient")
    @patch("scripts.sync_mm_authentik_groups.AuthentikClient")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_script_initialize_clients_success(self, mock_script_config, MockScriptAuthClient, MockScriptMMClient):
        mock_script_config.AUTHENTIK_URL = "http://auth.example.com"
        mock_script_config.AUTHENTIK_TOKEN = "auth_token"
        mock_script_config.MATTERMOST_URL = "http://mm.example.com"
        mock_script_config.BOT_TOKEN = "mm_bot_token"
        mock_script_config.MATTERMOST_TEAM_ID = "mm_team_id"

        mock_auth_instance = MockScriptAuthClient.return_value
        mock_mm_instance = MockScriptMMClient.return_value

        auth_client, mm_client = script_module.initialize_clients()

        MockScriptAuthClient.assert_called_once_with("http://auth.example.com", "auth_token")
        MockScriptMMClient.assert_called_once_with("http://mm.example.com", "mm_bot_token", "mm_team_id")
        self.assertEqual(auth_client, mock_auth_instance)
        self.assertEqual(mm_client, mock_mm_instance)

    @patch("scripts.sync_mm_authentik_groups.AuthentikClient")  # Only need to patch this one for this test
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_script_initialize_clients_auth_missing_config(self, mock_script_config, MockScriptAuthClient):
        mock_script_config.AUTHENTIK_URL = None  # Simulate missing Authentik URL
        mock_script_config.AUTHENTIK_TOKEN = "token"
        # Assume MM config is valid for this test case if we want MM client to init
        mock_script_config.MATTERMOST_URL = "http://mm.example.com"
        mock_script_config.BOT_TOKEN = "mm_bot_token"
        mock_script_config.MATTERMOST_TEAM_ID = "mm_team_id"

        auth_client, _ = script_module.initialize_clients()

        self.assertIsNone(auth_client)
        MockScriptAuthClient.assert_not_called()
        # Not explicitly testing MM client here, covered by other tests.

    @patch("scripts.sync_mm_authentik_groups.MattermostClient")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_script_initialize_clients_mm_missing_config(self, mock_script_config, MockScriptMMClient):
        mock_script_config.MATTERMOST_URL = None  # Simulate missing Mattermost URL
        mock_script_config.BOT_TOKEN = "token"
        mock_script_config.MATTERMOST_TEAM_ID = "team_id"
        # Assume Authentik config is valid
        mock_script_config.AUTHENTIK_URL = "http://auth.example.com"
        mock_script_config.AUTHENTIK_TOKEN = "auth_token"

        _, mm_client = script_module.initialize_clients()
        self.assertIsNone(mm_client)
        MockScriptMMClient.assert_not_called()

    # --- Tests for get_all_authentik_groups_and_user_map (from libraries.group_sync_services) ---
    def test_library_get_all_authentik_groups_and_user_map(self):
        mock_groups_data = [{"name": "group1"}]
        mock_email_map_data = {"email@example.com": "pk1"}
        self.mock_auth_client_instance.get_groups_with_users.return_value = (mock_groups_data, mock_email_map_data)

        groups, email_map = get_all_authentik_groups_and_user_map(self.mock_auth_client_instance)

        self.mock_auth_client_instance.get_groups_with_users.assert_called_once()
        self.assertEqual(groups, mock_groups_data)
        self.assertEqual(email_map, mock_email_map_data)

    def test_library_get_all_authentik_groups_no_client(self):
        groups, email_map = get_all_authentik_groups_and_user_map(None)
        self.assertEqual(groups, [])
        self.assertEqual(email_map, {})

    # --- Tests for sync_single_authentik_group_with_mattermost (from libraries.group_sync_services) ---
    def test_library_sync_single_group_user_added_successfully(self):
        auth_group = {"pk": "auth_g_pk1", "name": "Dev Team Sync", "users": []}
        email_map = {"dev1@example.com": "auth_user_pk1"}
        mm_users = [{"email": "dev1@example.com", "id": "mm_id_1"}]
        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id1",
            "display_name": "Dev Team Sync",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = mm_users
        self.mock_auth_client_instance.add_user_to_group.return_value = True

        results = sync_single_authentik_group_with_mattermost(
            self.mock_auth_client_instance, self.mock_mm_client_instance, self.test_mm_team_id, auth_group, email_map
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["action"], "ADDED_TO_AUTHENTIK_GROUP")
        self.assertEqual(results[0]["mm_username"], "UnknownUsername") # Assuming default from code
        self.mock_mm_client_instance.get_channel_by_name.assert_called_once()
        self.mock_mm_client_instance.get_users_in_channel.assert_called_once_with("mm_chan_id1")
        self.mock_auth_client_instance.add_user_to_group.assert_called_once_with("auth_g_pk1", "auth_user_pk1")

    def test_library_sync_single_group_mm_channel_not_found(self):
        auth_group = {"pk": "auth_g_pk1", "name": "NoChannelHere", "users": []}
        self.mock_mm_client_instance.get_channel_by_name.return_value = None
        results = sync_single_authentik_group_with_mattermost(
            self.mock_auth_client_instance, self.mock_mm_client_instance, self.test_mm_team_id, auth_group, {}
        )
        self.assertEqual(results, []) # Expect an empty list as per new return type
        self.mock_mm_client_instance.get_users_in_channel.assert_not_called()

    def test_library_sync_single_group_no_users_added(self):
        auth_group = {"pk": "auth_g_pk1", "name": "Dev Team Sync", "users": ["auth_user_pk1"]}  # User already in group
        email_map = {"dev1@example.com": "auth_user_pk1"}
        mm_users = [{"email": "dev1@example.com", "id": "mm_id_1"}]
        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id1",
            "display_name": "Dev Team Sync",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = mm_users

        results = sync_single_authentik_group_with_mattermost(
            self.mock_auth_client_instance, self.mock_mm_client_instance, self.test_mm_team_id, auth_group, email_map
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["action"], "ALREADY_IN_AUTHENTIK_GROUP")
        self.mock_auth_client_instance.add_user_to_group.assert_not_called()

    def test_library_sync_single_group_client_missing(self):
        results = sync_single_authentik_group_with_mattermost(
            None, self.mock_mm_client_instance, self.test_mm_team_id, {}, {}
        )
        self.assertEqual(results, []) # Expect an empty list

    # --- Tests for orchestrate_authentik_mattermost_sync (from libraries.group_sync_services) ---
    @patch("libraries.group_sync_services.sync_single_authentik_group_with_mattermost")
    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    def test_library_orchestrate_sync_success(self, mock_get_groups_map, mock_sync_single):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_team_id = "team123"

        mock_groups_list = [{"name": "group1", "pk": "g1"}, {"name": "group2", "pk": "g2"}]
        mock_email_pk_map = {"user1@example.com": "upk1"}
        mock_get_groups_map.return_value = (mock_groups_list, mock_email_pk_map)

        # Simulate sync_single returning a list of results
        mock_sync_single.side_effect = [
            [{"action": "ADDED_TO_AUTHENTIK_GROUP", "status": "SUCCESS"}], # For group1
            [{"action": "ALREADY_IN_AUTHENTIK_GROUP", "status": "SUCCESS"}]  # For group2
        ]
        expected_detailed_results = [
            {"action": "ADDED_TO_AUTHENTIK_GROUP", "status": "SUCCESS"},
            {"action": "ALREADY_IN_AUTHENTIK_GROUP", "status": "SUCCESS"}
        ]

        success, detailed_results = orchestrate_authentik_mattermost_sync(mock_auth_client, mock_mm_client, mock_team_id)

        self.assertTrue(success)
        self.assertEqual(detailed_results, expected_detailed_results)
        mock_get_groups_map.assert_called_once_with(mock_auth_client)
        self.assertEqual(mock_sync_single.call_count, 2)
        mock_sync_single.assert_any_call(
            mock_auth_client, mock_mm_client, mock_team_id, mock_groups_list[0], mock_email_pk_map
        )
        mock_sync_single.assert_any_call(
            mock_auth_client, mock_mm_client, mock_team_id, mock_groups_list[1], mock_email_pk_map
        )
        # Check logs or a return value from orchestrate indicating total users added if implemented

    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    def test_library_orchestrate_sync_no_groups_found(self, mock_get_groups_map):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_team_id = "team123"
        mock_get_groups_map.return_value = ([], {})  # No groups

        success, detailed_results = orchestrate_authentik_mattermost_sync(mock_auth_client, mock_mm_client, mock_team_id)
        self.assertTrue(success)
        self.assertEqual(detailed_results, []) # Expect empty list of results
        mock_get_groups_map.assert_called_once_with(mock_auth_client)

    def test_library_orchestrate_sync_clients_missing(self):
        # Test with Authentik client missing
        success_auth, results_auth = orchestrate_authentik_mattermost_sync(None, MagicMock(spec=MattermostClient), "team_id")
        self.assertFalse(success_auth)
        self.assertEqual(results_auth, [])

        # Test with Mattermost client missing
        success_mm, results_mm = orchestrate_authentik_mattermost_sync(MagicMock(spec=AuthentikClient), None, "team_id")
        self.assertFalse(success_mm)
        self.assertEqual(results_mm, [])

        # Test with team_id missing
        success_team, results_team = orchestrate_authentik_mattermost_sync(
            MagicMock(spec=AuthentikClient), MagicMock(spec=MattermostClient), None
        )
        self.assertFalse(success_team)
        self.assertEqual(results_team, [])


    # --- Tests for main_sync_logic (from scripts.sync_mm_authentik_groups) ---
    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_authentik_mattermost_sync")
    def test_script_main_sync_logic_orchestration(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = "script_team_id"
        mock_auth_instance = MagicMock(spec=AuthentikClient)
        mock_mm_instance = MagicMock(spec=MattermostClient)
        mock_script_init_clients.return_value = (mock_auth_instance, mock_mm_instance)
        mock_orchestrate_lib.return_value = True  # Simulate library success

        script_module.main_sync_logic()

        mock_script_init_clients.assert_called_once()
        mock_orchestrate_lib.assert_called_once_with(mock_auth_instance, mock_mm_instance, "script_team_id")

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_authentik_mattermost_sync")
    def test_script_main_sync_logic_init_auth_fails(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = "script_team_id"
        mock_script_init_clients.return_value = (None, MagicMock(spec=MattermostClient))  # Auth client init fails

        script_module.main_sync_logic()
        mock_orchestrate_lib.assert_not_called()

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_authentik_mattermost_sync")
    def test_script_main_sync_logic_init_mm_fails(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = "script_team_id"
        mock_script_init_clients.return_value = (MagicMock(spec=AuthentikClient), None)  # MM client init fails

        script_module.main_sync_logic()
        mock_orchestrate_lib.assert_not_called()

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_authentik_mattermost_sync")
    def test_script_main_sync_logic_no_team_id(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = None  # Team ID missing
        mock_script_init_clients.return_value = (MagicMock(spec=AuthentikClient), MagicMock(spec=MattermostClient))

        script_module.main_sync_logic()
        mock_orchestrate_lib.assert_not_called()


if __name__ == "__main__":
    unittest.main()
