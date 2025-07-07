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
from clients.brevo_client import BrevoClient  # Added BrevoClient

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
        self.mock_brevo_client_instance = MagicMock(spec=BrevoClient)  # Added Brevo mock
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
        mock_script_config.OUTLINE_URL = "http://outline.example.com"  # Assume outline is configured
        mock_script_config.OUTLINE_TOKEN = "outline_token"
        mock_script_config.BREVO_API_URL = "http://brevo.example.com"  # Assume brevo is configured
        mock_script_config.BREVO_API_KEY = "brevo_key"

        mock_auth_instance = MockScriptAuthClient.return_value
        mock_mm_instance = MockScriptMMClient.return_value
        # Mock OutlineClient, BrevoClient, and VaultwardenClient if they are part of initialize_clients
        with patch("scripts.sync_mm_authentik_groups.OutlineClient") as MockScriptOutlineClient, \
             patch("scripts.sync_mm_authentik_groups.BrevoClient") as MockScriptBrevoClient, \
             patch("scripts.sync_mm_authentik_groups.VaultwardenClient") as MockScriptVWClient: # Added VW mock
            mock_outline_instance = MockScriptOutlineClient.return_value
            mock_brevo_instance = MockScriptBrevoClient.return_value
            mock_vw_instance = MockScriptVWClient.return_value # Get VW mock instance

            # Initialize clients now returns 5 values
            auth_client, mm_client, outline_client, brevo_client, vw_client = script_module.initialize_clients()

            MockScriptAuthClient.assert_called_once_with("http://auth.example.com", "auth_token")
            MockScriptMMClient.assert_called_once_with("http://mm.example.com", "mm_bot_token", "mm_team_id")
            MockScriptOutlineClient.assert_called_once_with("http://outline.example.com", "outline_token")
            MockScriptBrevoClient.assert_called_once_with("http://brevo.example.com", "brevo_key")
            # VW client will be None if VAULTWARDEN_ORGANIZATION_ID is not set in mock_script_config for this test
            # If it were set, we'd assert: MockScriptVWClient.assert_called_once_with(organization_id=..., server_url=...)
            # For now, just ensure it unpacks fine. vw_client might be None.

            self.assertEqual(auth_client, mock_auth_instance)
            self.assertEqual(mm_client, mock_mm_instance)
            self.assertEqual(outline_client, mock_outline_instance)
            self.assertEqual(brevo_client, mock_brevo_instance)
            # self.assertEqual(vw_client, mock_vw_instance) # Only if VW is expected to be initialized

    @patch("scripts.sync_mm_authentik_groups.AuthentikClient")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_script_initialize_clients_auth_missing_config(self, mock_script_config, MockScriptAuthClient):
        mock_script_config.AUTHENTIK_URL = None
        mock_script_config.AUTHENTIK_TOKEN = "token"
        mock_script_config.MATTERMOST_URL = "http://mm.example.com"
        mock_script_config.BOT_TOKEN = "mm_bot_token"
        mock_script_config.MATTERMOST_TEAM_ID = "mm_team_id"
        mock_script_config.OUTLINE_URL = "http://outline.example.com"
        mock_script_config.OUTLINE_TOKEN = "outline_token"
        mock_script_config.BREVO_API_URL = "http://brevo.example.com"
        mock_script_config.BREVO_API_KEY = "brevo_key"
        mock_script_config.VAULTWARDEN_ORGANIZATION_ID = None # Ensure VW client is None
        auth_client, _, _, _, _ = script_module.initialize_clients()  # Unpack 5
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
        mock_script_config.OUTLINE_URL = "http://outline.example.com"
        mock_script_config.OUTLINE_TOKEN = "outline_token"
        mock_script_config.BREVO_API_URL = "http://brevo.example.com"
        mock_script_config.BREVO_API_KEY = "brevo_key"
        mock_script_config.VAULTWARDEN_ORGANIZATION_ID = None # Ensure VW client is None
        _, mm_client, _, _, _ = script_module.initialize_clients()  # Unpack 5
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
    # Removed @patch for get_all_authentik_groups_and_user_map
    @patch("libraries.group_sync_services.config")
    def test_library_orchestrate_sync_success_all_clients(
        self, mock_lib_config, mock_sync_entity_permissions  # mock_get_groups_map removed
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
        # This is the email map that should be used by sync_entity_permissions
        mock_email_pk_map_for_sync = {"user1@example.com": "upk1"}

        # Setup mock_auth_client calls
        # get_groups_with_users returns the groups and its own derived email_map (which is ignored by orchestrate)
        mock_auth_client.get_groups_with_users.return_value = (mock_groups_list, {"temp_email@example.com": "temp_pk"})
        # get_all_user_email_to_pk_map returns the primary email map
        mock_auth_client.get_all_user_email_to_pk_map.return_value = mock_email_pk_map_for_sync

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
            mock_auth_client,
            mock_mm_client,
            mock_outline_client,
            self.mock_brevo_client_instance,
            None,  # vaultwarden_client
            mock_team_id,
            perform_deletions=True,
            fetch_remote_members=True,  # This ensures get_groups_with_users and get_all_user_email_to_pk_map are called
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, expected_detailed_results)

        mock_auth_client.get_groups_with_users.assert_called_once_with(fetch_members=True)
        mock_auth_client.get_all_user_email_to_pk_map.assert_called_once_with()

        self.assertEqual(mock_sync_entity_permissions.call_count, 2)
        # Construct expected all_auth_groups_by_name from mock_groups_list for assertion
        expected_auth_groups = {g["name"]: g for g in mock_groups_list}
        projet_cfg = mock_lib_config.PERMISSIONS_MATRIX["PROJET"]
        antenne_cfg = mock_lib_config.PERMISSIONS_MATRIX["ANTENNE"]
        email_map_sync = mock_email_pk_map_for_sync

        mock_sync_entity_permissions.assert_any_call(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client,
            self.mock_brevo_client_instance,
            None,  # vaultwarden_client
            mock_team_id,
            "alpha",
            "PROJET",
            projet_cfg,
            expected_auth_groups,
            email_map_sync,
            True,
        )
        mock_sync_entity_permissions.assert_any_call(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client,
            self.mock_brevo_client_instance,
            None,  # vaultwarden_client
            mock_team_id,
            "beta",
            "ANTENNE",
            antenne_cfg,
            expected_auth_groups,
            email_map_sync,
            True,
        )

    @patch("libraries.group_sync_services.sync_entity_permissions")
    # Removed @patch for get_all_authentik_groups_and_user_map
    @patch("libraries.group_sync_services.config")
    def test_library_orchestrate_sync_success_outline_client_none(
        self, mock_lib_config, mock_sync_entity_permissions  # mock_get_groups_map removed
    ):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_team_id = "team123"
        mock_outline_client_none = None
        mock_groups_list = [{"name": "projet_gamma", "pk": "g_gamma", "users": [], "users_obj": []}]

        mock_email_pk_map_for_sync = {"usergamma@example.com": "upk_gamma"}
        mock_auth_client.get_groups_with_users.return_value = (mock_groups_list, {"temp@example.com": "temp_pk"})
        mock_auth_client.get_all_user_email_to_pk_map.return_value = mock_email_pk_map_for_sync

        mock_lib_config.PERMISSIONS_MATRIX = {
            "PROJET": {"standard": {"authentik_group_name_pattern": "projet_{base_name}"}}
        }
        mock_sync_entity_permissions.return_value = [{"service": "AUTHENTIK_ONLY", "status": "SUCCESS"}]
        expected_detailed_results = [{"service": "AUTHENTIK_ONLY", "status": "SUCCESS"}]
        success, detailed_results = orchestrate_group_synchronization(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client_none,
            self.mock_brevo_client_instance,
            None,  # vaultwarden_client
            mock_team_id,
            perform_deletions=True,
            fetch_remote_members=True,  # Ensures the client methods are called
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, expected_detailed_results)

        expected_all_auth_groups_by_name = {g["name"]: g for g in mock_groups_list}
        mock_sync_entity_permissions.assert_called_once_with(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client_none,
            self.mock_brevo_client_instance,
            None,  # vaultwarden_client
            mock_team_id,
            "gamma",
            "PROJET",
            mock_lib_config.PERMISSIONS_MATRIX["PROJET"],
            expected_all_auth_groups_by_name,
            mock_email_pk_map_for_sync,
            True,
        )

    # Removed @patch for get_all_authentik_groups_and_user_map
    @patch("libraries.group_sync_services.config")
    def test_library_orchestrate_sync_no_groups_found(self, mock_lib_config):  # mock_get_groups_map removed
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_outline_client = MagicMock(spec=OutlineClient)
        mock_team_id = "team123"

        # Setup mock_auth_client calls
        mock_auth_client.get_groups_with_users.return_value = ([], {})
        mock_auth_client.get_all_user_email_to_pk_map.return_value = {}

        success, detailed_results = orchestrate_group_synchronization(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client,
            self.mock_brevo_client_instance,
            None,  # vaultwarden_client
            mock_team_id,
            perform_deletions=True,
            fetch_remote_members=True,  # Ensures client methods for group discovery are called
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, [])
        mock_auth_client.get_groups_with_users.assert_called_once_with(fetch_members=True)
        mock_auth_client.get_all_user_email_to_pk_map.assert_called_once_with()

    def test_library_orchestrate_sync_core_clients_missing(self):
        mock_outline_client = MagicMock(spec=OutlineClient)
        # Using self.mock_brevo_client_instance now that it's in setUp

        # Test with Authentik client missing
        success_auth, results_auth = orchestrate_group_synchronization(
            None,  # authentik_client
            MagicMock(spec=MattermostClient),
            mock_outline_client,
            self.mock_brevo_client_instance,
            None,  # vaultwarden_client
            "team_id",
            perform_deletions=True,
        )
        self.assertTrue(success_auth)
        self.assertEqual(results_auth, [])

        # Test with Mattermost client missing (critical)
        success_mm, results_mm = orchestrate_group_synchronization(
            MagicMock(spec=AuthentikClient),
            None,  # mattermost_client
            mock_outline_client,
            self.mock_brevo_client_instance,
            None,  # vaultwarden_client
            "team_id",
            perform_deletions=True,
        )
        self.assertFalse(success_mm)
        self.assertEqual(results_mm, [])

        # Test with Mattermost team_id missing (critical)
        success_team, results_team = orchestrate_group_synchronization(
            MagicMock(spec=AuthentikClient),
            MagicMock(spec=MattermostClient),
            mock_outline_client,
            self.mock_brevo_client_instance,
            None,  # vaultwarden_client
            None,  # mm_team_id is None
            perform_deletions=True,
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
        mock_script_config.BREVO_API_URL = None
        mock_script_config.BREVO_API_KEY = None
        mock_script_config.VAULTWARDEN_ORGANIZATION_ID = None # Ensure VW client is None for this test
        mock_auth_instance = MagicMock(spec=AuthentikClient)
        mock_mm_instance = MagicMock(spec=MattermostClient)
        # initialize_clients now returns 5 values
        mock_script_init_clients.return_value = (mock_auth_instance, mock_mm_instance, None, None, None)
        mock_orchestrate_lib.return_value = (True, [])
        script_module.main_sync_logic()
        mock_script_init_clients.assert_called_once()
        # orchestrate_group_synchronization expects 5 client args + team_id
        mock_orchestrate_lib.assert_called_once_with(
            mock_auth_instance, mock_mm_instance, None, None, None, "script_team_id"
        )

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_group_synchronization")
    def test_script_main_sync_logic_init_auth_fails(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = "script_team_id"
        mock_script_config.OUTLINE_URL = None  # Ensure Outline client is None
        mock_script_config.OUTLINE_TOKEN = None
        mock_script_config.BREVO_API_URL = None
        mock_script_config.BREVO_API_KEY = None
        mock_script_config.VAULTWARDEN_ORGANIZATION_ID = None
        # initialize_clients now returns 5 values
        mock_script_init_clients.return_value = (None, MagicMock(spec=MattermostClient), None, None, None)
        script_module.main_sync_logic()
        mock_orchestrate_lib.assert_not_called()

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_group_synchronization")
    def test_script_main_sync_logic_init_mm_fails(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = "script_team_id"
        mock_script_config.OUTLINE_URL = None  # Ensure Outline client is None
        mock_script_config.OUTLINE_TOKEN = None
        mock_script_config.BREVO_API_URL = None
        mock_script_config.BREVO_API_KEY = None
        mock_script_config.VAULTWARDEN_ORGANIZATION_ID = None
        # initialize_clients now returns 5 values
        mock_script_init_clients.return_value = (MagicMock(spec=AuthentikClient), None, None, None, None)
        script_module.main_sync_logic()
        mock_orchestrate_lib.assert_not_called()

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_group_synchronization")
    def test_script_main_sync_logic_no_team_id(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = None
        mock_script_config.OUTLINE_URL = None
        mock_script_config.OUTLINE_TOKEN = None
        mock_script_config.BREVO_API_URL = None
        mock_script_config.BREVO_API_KEY = None
        mock_script_config.VAULTWARDEN_ORGANIZATION_ID = None
        # initialize_clients now returns 5 values
        mock_script_init_clients.return_value = (
            MagicMock(spec=AuthentikClient),
            MagicMock(spec=MattermostClient),
            None, # Outline
            None, # Brevo
            None, # Vaultwarden
        )
        script_module.main_sync_logic()
        mock_orchestrate_lib.assert_not_called()


if __name__ == "__main__":
    unittest.main()
