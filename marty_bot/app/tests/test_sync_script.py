import unittest
from unittest.mock import patch, MagicMock
import logging
import sys
import os

# Adjust path to import from the project root directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Client classes for type hinting and MagicMock spec
from clients.authentik_client import AuthentikClient
from clients.mattermost_client import MattermostClient
from clients.outline_client import OutlineClient

# Functions/modules to be tested
import scripts.sync_mm_authentik_groups as script_module
from libraries.group_sync_services import (
    get_all_authentik_groups_and_user_map,
    orchestrate_group_synchronization,
    # sync_entity_permissions removed as it's not directly used by these tests after refactor
)


class TestSyncLogic(unittest.TestCase):

    def setUp(self):
        self.mock_auth_client_instance = MagicMock(spec=AuthentikClient)
        self.mock_mm_client_instance = MagicMock(spec=MattermostClient)
        self.mock_outline_client_instance = MagicMock(spec=OutlineClient)
        self.test_mm_team_id = "test_team_id"

        loggers_to_suppress = [
            "scripts.sync_mm_authentik_groups",
            "libraries.group_sync_services",
            "clients.authentik_client",
            "clients.mattermost_client",
        ]
        for logger_name in loggers_to_suppress:
            logging.getLogger(logger_name).setLevel(logging.CRITICAL + 1)

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

    @patch("scripts.sync_mm_authentik_groups.AuthentikClient")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_script_initialize_clients_auth_missing_config(self, mock_script_config, MockScriptAuthClient):
        mock_script_config.AUTHENTIK_URL = None
        mock_script_config.AUTHENTIK_TOKEN = "token"
        mock_script_config.MATTERMOST_URL = "http://mm.example.com"
        mock_script_config.BOT_TOKEN = "mm_bot_token"
        mock_script_config.MATTERMOST_TEAM_ID = "mm_team_id"
        auth_client, _ = script_module.initialize_clients()
        self.assertIsNone(auth_client)
        MockScriptAuthClient.assert_not_called()

    @patch("scripts.sync_mm_authentik_groups.MattermostClient")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_script_initialize_clients_mm_missing_config(self, mock_script_config, MockScriptMMClient):
        mock_script_config.MATTERMOST_URL = None
        mock_script_config.BOT_TOKEN = "token"
        mock_script_config.MATTERMOST_TEAM_ID = "team_id"
        mock_script_config.AUTHENTIK_URL = "http://auth.example.com"
        mock_script_config.AUTHENTIK_TOKEN = "auth_token"
        _, mm_client = script_module.initialize_clients()
        self.assertIsNone(mm_client)
        MockScriptMMClient.assert_not_called()

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

    @patch("libraries.group_sync_services.sync_entity_permissions")
    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    @patch("libraries.group_sync_services.config")
    def test_library_orchestrate_sync_success_all_clients(
        self, mock_lib_config, mock_get_groups_map, mock_sync_entity_permissions
    ):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_outline_client = MagicMock(spec=OutlineClient)
        mock_team_id = "team123"
        mock_groups_list = [
            {"name": "projet_alpha", "pk": "g1_std", "users": [], "users_obj": []},
            {"name": "projet_alpha Admin", "pk": "g1_adm", "users": [], "users_obj": []},
            {"name": "antenne_beta", "pk": "g2_std", "users": [], "users_obj": []},
        ]
        mock_email_pk_map = {"user1@example.com": "upk1"}
        mock_get_groups_map.return_value = (mock_groups_list, mock_email_pk_map)
        mock_lib_config.PERMISSIONS_MATRIX = {
            "PROJET": {
                "standard": {"authentik_group_name_pattern": "projet_{base_name}"},
                "admin": {"authentik_group_name_pattern": "projet_{base_name} Admin"},
            },
            "ANTENNE": {"standard": {"authentik_group_name_pattern": "antenne_{base_name}"}},
        }
        mock_sync_entity_permissions.side_effect = [
            [{"service": "PROJET_ALPHA_SYNC", "status": "SUCCESS"}],
            [{"service": "ANTENNE_BETA_SYNC", "status": "SUCCESS"}],
        ]
        expected_detailed_results = [
            {"service": "PROJET_ALPHA_SYNC", "status": "SUCCESS"},
            {"service": "ANTENNE_BETA_SYNC", "status": "SUCCESS"},
        ]
        success, detailed_results = orchestrate_group_synchronization(
            mock_auth_client, mock_mm_client, mock_outline_client, mock_team_id, perform_deletions=True
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, expected_detailed_results)
        mock_get_groups_map.assert_called_once_with(mock_auth_client)
        self.assertEqual(mock_sync_entity_permissions.call_count, 2)
        mock_sync_entity_permissions.assert_any_call(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client,
            mock_team_id,
            "alpha",
            "PROJET",
            mock_lib_config.PERMISSIONS_MATRIX["PROJET"],
            unittest.mock.ANY, # all_authentik_groups_by_name
            mock_email_pk_map,
            True, # perform_deletions
        )
        mock_sync_entity_permissions.assert_any_call(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client,
            mock_team_id,
            "beta",
            "ANTENNE",
            mock_lib_config.PERMISSIONS_MATRIX["ANTENNE"],
            unittest.mock.ANY, # all_authentik_groups_by_name
            mock_email_pk_map,
            True, # perform_deletions
        )

    @patch("libraries.group_sync_services.sync_entity_permissions")
    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    @patch("libraries.group_sync_services.config")
    def test_library_orchestrate_sync_success_outline_client_none(
        self, mock_lib_config, mock_get_groups_map, mock_sync_entity_permissions
    ):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_team_id = "team123"
        mock_outline_client_none = None
        mock_groups_list = [{"name": "projet_gamma", "pk": "g_gamma", "users": [], "users_obj": []}]
        mock_email_pk_map = {"usergamma@example.com": "upk_gamma"}
        mock_get_groups_map.return_value = (mock_groups_list, mock_email_pk_map)
        mock_lib_config.PERMISSIONS_MATRIX = {
            "PROJET": {"standard": {"authentik_group_name_pattern": "projet_{base_name}"}}
        }
        mock_sync_entity_permissions.return_value = [{"service": "AUTHENTIK_ONLY", "status": "SUCCESS"}]
        expected_detailed_results = [{"service": "AUTHENTIK_ONLY", "status": "SUCCESS"}]
        success, detailed_results = orchestrate_group_synchronization(
            mock_auth_client, mock_mm_client, mock_outline_client_none, mock_team_id, perform_deletions=True
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, expected_detailed_results)
        mock_sync_entity_permissions.assert_called_once_with(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client_none,
            mock_team_id,
            "gamma",
            "PROJET",
            mock_lib_config.PERMISSIONS_MATRIX["PROJET"],
            unittest.mock.ANY, # all_authentik_groups_by_name
            mock_email_pk_map,
            True, # perform_deletions
        )

    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    @patch("libraries.group_sync_services.config")
    def test_library_orchestrate_sync_no_groups_found(self, mock_lib_config, mock_get_groups_map):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_outline_client = MagicMock(spec=OutlineClient)
        mock_team_id = "team123"
        mock_get_groups_map.return_value = ([], {})
        success, detailed_results = orchestrate_group_synchronization(
            mock_auth_client, mock_mm_client, mock_outline_client, mock_team_id, perform_deletions=True
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, [])
        mock_get_groups_map.assert_called_once_with(mock_auth_client)

    def test_library_orchestrate_sync_core_clients_missing(self):
        mock_outline_client = MagicMock(spec=OutlineClient)
        success_auth, results_auth = orchestrate_group_synchronization(
            None, MagicMock(spec=MattermostClient), mock_outline_client, "team_id", perform_deletions=True
        )
        self.assertFalse(success_auth)
        self.assertEqual(results_auth, [])
        success_mm, results_mm = orchestrate_group_synchronization(
            MagicMock(spec=AuthentikClient), None, mock_outline_client, "team_id", perform_deletions=True
        )
        self.assertFalse(success_mm)
        self.assertEqual(results_mm, [])
        success_team, results_team = orchestrate_group_synchronization(
            MagicMock(spec=AuthentikClient), MagicMock(spec=MattermostClient), mock_outline_client, None, perform_deletions=True
        )
        self.assertFalse(success_team)
        self.assertEqual(results_team, [])

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_group_synchronization")
    def test_script_main_sync_logic_orchestration(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = "script_team_id"
        mock_script_config.OUTLINE_URL = None
        mock_script_config.OUTLINE_TOKEN = None
        mock_auth_instance = MagicMock(spec=AuthentikClient)
        mock_mm_instance = MagicMock(spec=MattermostClient)
        mock_script_init_clients.return_value = (mock_auth_instance, mock_mm_instance)
        mock_orchestrate_lib.return_value = (True, [])
        script_module.main_sync_logic()
        mock_script_init_clients.assert_called_once()
        # Script main_sync_logic calls orchestrate_group_synchronization without explicitly setting perform_deletions,
        # so it relies on the default value (True) in the function's definition.
        # The mock assertion should reflect the actual call made by the script.
        mock_orchestrate_lib.assert_called_once_with(mock_auth_instance, mock_mm_instance, None, "script_team_id")

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_group_synchronization")
    def test_script_main_sync_logic_init_auth_fails(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = "script_team_id"
        mock_script_config.OUTLINE_URL = None
        mock_script_config.OUTLINE_TOKEN = None
        mock_script_init_clients.return_value = (None, MagicMock(spec=MattermostClient))
        script_module.main_sync_logic()
        mock_orchestrate_lib.assert_not_called()

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_group_synchronization")
    def test_script_main_sync_logic_init_mm_fails(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = "script_team_id"
        mock_script_init_clients.return_value = (MagicMock(spec=AuthentikClient), None)
        mock_script_config.OUTLINE_URL = None
        mock_script_config.OUTLINE_TOKEN = None
        script_module.main_sync_logic()
        mock_orchestrate_lib.assert_not_called()

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_group_synchronization")
    def test_script_main_sync_logic_no_team_id(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = None
        mock_script_init_clients.return_value = (MagicMock(spec=AuthentikClient), MagicMock(spec=MattermostClient))
        script_module.main_sync_logic()
        mock_orchestrate_lib.assert_not_called()


if __name__ == "__main__":
    unittest.main()
