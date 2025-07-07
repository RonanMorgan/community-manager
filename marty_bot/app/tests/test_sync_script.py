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
from clients.brevo_client import BrevoClient
from clients.vaultwarden_client import VaultwardenClient
from clients.nocodb_client import NocoDBClient  # Added for completeness, though script doesn't init it yet

# Functions/modules to be tested
import scripts.sync_mm_authentik_groups as script_module
from libraries.group_sync_services import (
    get_all_authentik_groups_and_user_map,
    orchestrate_group_synchronization,
)


class TestSyncLogic(unittest.TestCase):

    def setUp(self):
        self.mock_auth_client_instance = MagicMock(spec=AuthentikClient)
        self.mock_mm_client_instance = MagicMock(spec=MattermostClient)
        self.mock_outline_client_instance = MagicMock(spec=OutlineClient)
        self.mock_brevo_client_instance = MagicMock(spec=BrevoClient)
        self.mock_vaultwarden_client_instance = MagicMock(spec=VaultwardenClient)
        self.mock_nocodb_client_instance = MagicMock(spec=NocoDBClient)
        self.test_mm_team_id = "test_team_id"
        self.test_nocodb_project_id = "p_test_nocodb_project"

        loggers_to_suppress = [
            "scripts.sync_mm_authentik_groups",
            "libraries.group_sync_services",
            "clients.authentik_client",
            "clients.mattermost_client",
        ]
        for logger_name in loggers_to_suppress:
            logging.getLogger(logger_name).setLevel(logging.CRITICAL + 1)

    @patch("scripts.sync_mm_authentik_groups.NocoDBClient")  # Mock NocoDBClient in script's scope
    @patch("scripts.sync_mm_authentik_groups.VaultwardenClient")
    @patch("scripts.sync_mm_authentik_groups.BrevoClient")
    @patch("scripts.sync_mm_authentik_groups.OutlineClient")
    @patch("scripts.sync_mm_authentik_groups.MattermostClient")
    @patch("scripts.sync_mm_authentik_groups.AuthentikClient")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_script_initialize_clients_success(
        self,
        mock_script_config,
        MockScriptAuthClient,
        MockScriptMMClient,
        MockScriptOutlineClient,
        MockScriptBrevoClient,
        MockScriptVWClient,
        MockScriptNocoDBClient,
    ):
        mock_script_config.AUTHENTIK_URL = "http://auth.example.com"
        mock_script_config.AUTHENTIK_TOKEN = "auth_token"
        mock_script_config.MATTERMOST_URL = "http://mm.example.com"
        mock_script_config.BOT_TOKEN = "mm_bot_token"
        mock_script_config.MATTERMOST_TEAM_ID = "mm_team_id"
        mock_script_config.OUTLINE_URL = "http://outline.example.com"
        mock_script_config.OUTLINE_TOKEN = "outline_token"
        mock_script_config.BREVO_API_URL = "http://brevo.example.com"
        mock_script_config.BREVO_API_KEY = "brevo_key"
        mock_script_config.VAULTWARDEN_ORGANIZATION_ID = "vw_org_id"
        mock_script_config.VAULTWARDEN_SERVER_URL = "http://vw.com"
        # Script's initialize_clients doesn't handle NocoDB yet, so these won't make it initialize NocoDBClient
        mock_script_config.NOCODB_URL = None
        mock_script_config.NOCODB_TOKEN = None
        mock_script_config.NOCODB_PROJECT_ID = None

        mock_auth_instance = MockScriptAuthClient.return_value
        mock_mm_instance = MockScriptMMClient.return_value
        mock_outline_instance = MockScriptOutlineClient.return_value
        mock_brevo_instance = MockScriptBrevoClient.return_value
        mock_vw_instance = MockScriptVWClient.return_value

        # Script's initialize_clients currently returns 5 clients (Auth, MM, Outline, Brevo, VW)
        auth_client, mm_client, outline_client, brevo_client, vw_client = script_module.initialize_clients()

        MockScriptAuthClient.assert_called_once_with("http://auth.example.com", "auth_token")
        MockScriptMMClient.assert_called_once_with("http://mm.example.com", "mm_bot_token", "mm_team_id")
        MockScriptOutlineClient.assert_called_once_with("http://outline.example.com", "outline_token")
        MockScriptBrevoClient.assert_called_once_with("http://brevo.example.com", "brevo_key")
        MockScriptVWClient.assert_called_once_with(organization_id="vw_org_id", server_url="http://vw.com")
        MockScriptNocoDBClient.assert_not_called()  # Script does not initialize NocoDBClient yet

        self.assertEqual(auth_client, mock_auth_instance)
        self.assertEqual(mm_client, mock_mm_instance)
        self.assertEqual(outline_client, mock_outline_instance)
        self.assertEqual(brevo_client, mock_brevo_instance)
        self.assertEqual(vw_client, mock_vw_instance)

    @patch("scripts.sync_mm_authentik_groups.config")
    def test_script_initialize_clients_auth_missing_config(self, mock_script_config):
        mock_script_config.AUTHENTIK_URL = None
        mock_script_config.AUTHENTIK_TOKEN = "token"
        # ... (other configs set) ...
        auth_client, _, _, _, _ = script_module.initialize_clients()  # Unpack 5
        self.assertIsNone(auth_client)

    @patch("scripts.sync_mm_authentik_groups.config")
    def test_script_initialize_clients_mm_missing_config(self, mock_script_config):
        mock_script_config.MATTERMOST_URL = None
        mock_script_config.BOT_TOKEN = "token"
        # ...
        _, mm_client, _, _, _ = script_module.initialize_clients()  # Unpack 5
        self.assertIsNone(mm_client)

    def test_library_get_all_authentik_groups_and_user_map(self):
        # ... (this test remains unchanged)
        mock_groups_data = [{"name": "group1"}]
        mock_email_map_data = {"email@example.com": "pk1"}
        self.mock_auth_client_instance.get_groups_with_users.return_value = (mock_groups_data, mock_email_map_data)
        groups, email_map = get_all_authentik_groups_and_user_map(self.mock_auth_client_instance)
        self.mock_auth_client_instance.get_groups_with_users.assert_called_once()
        self.assertEqual(groups, mock_groups_data)
        self.assertEqual(email_map, mock_email_map_data)

    @patch("libraries.group_sync_services.sync_entity_permissions")
    @patch("libraries.group_sync_services.config")
    def test_library_orchestrate_sync_success_all_clients(self, mock_lib_config, mock_sync_entity_permissions):
        # ... (setup mocks for auth, mm, outline, brevo, vw, nocodb clients)
        mock_auth_client = self.mock_auth_client_instance
        mock_mm_client = self.mock_mm_client_instance
        mock_outline_client = self.mock_outline_client_instance
        mock_brevo_client = self.mock_brevo_client_instance
        mock_vw_client = self.mock_vaultwarden_client_instance
        mock_nocodb_client = self.mock_nocodb_client_instance
        mock_nocodb_project_id = self.test_nocodb_project_id
        mock_lib_config.NOCODB_PROJECT_ID = mock_nocodb_project_id  # Ensure config has it

        # ... (rest of the test setup for groups, email map, PERMISSIONS_MATRIX)
        mock_groups_list = [{"name": "projet_alpha", "pk": "g1_std"}, {"name": "antenne_beta", "pk": "g2_std"}]
        mock_email_pk_map_for_sync = {"user1@example.com": "upk1"}
        mock_auth_client.get_groups_with_users.return_value = (mock_groups_list, {})
        mock_auth_client.get_all_user_email_to_pk_map.return_value = mock_email_pk_map_for_sync
        mock_lib_config.PERMISSIONS_MATRIX = {
            "PROJET": {"standard": {"authentik_group_name_pattern": "projet_{base_name}"}},
            "ANTENNE": {"standard": {"authentik_group_name_pattern": "antenne_{base_name}"}},
        }
        mock_sync_entity_permissions.return_value = [{"status": "SUCCESS"}]

        success, _ = orchestrate_group_synchronization(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client,
            mock_brevo_client,
            mock_vw_client,
            mock_nocodb_client,
            mock_nocodb_project_id,  # Pass NocoDB args
            self.test_mm_team_id,
            fetch_remote_members=True,
        )
        self.assertTrue(success)

        expected_all_auth_groups_by_name = {g["name"]: g for g in mock_groups_list}
        projet_cfg = mock_lib_config.PERMISSIONS_MATRIX["PROJET"]
        antenne_cfg = mock_lib_config.PERMISSIONS_MATRIX["ANTENNE"]

        mock_sync_entity_permissions.assert_any_call(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client,
            mock_brevo_client,
            mock_vw_client,
            mock_nocodb_client,
            mock_nocodb_project_id,
            self.test_mm_team_id,
            "alpha",
            "PROJET",
            projet_cfg,
            expected_all_auth_groups_by_name,
            mock_email_pk_map_for_sync,
            True,
        )
        mock_sync_entity_permissions.assert_any_call(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client,
            mock_brevo_client,
            mock_vw_client,
            mock_nocodb_client,
            mock_nocodb_project_id,
            self.test_mm_team_id,
            "beta",
            "ANTENNE",
            antenne_cfg,
            expected_all_auth_groups_by_name,
            mock_email_pk_map_for_sync,
            True,
        )

    # ... (other orchestrate tests need similar updates to pass nocodb_client and nocodb_project_id)

    @patch("libraries.group_sync_services.config")
    def test_library_orchestrate_sync_core_clients_missing(self, mock_lib_config):
        mock_lib_config.NOCODB_PROJECT_ID = self.test_nocodb_project_id
        # Test with Authentik client missing
        success_auth, _ = orchestrate_group_synchronization(
            None,
            MagicMock(spec=MattermostClient),
            self.mock_outline_client_instance,
            self.mock_brevo_client_instance,
            self.mock_vaultwarden_client_instance,
            self.mock_nocodb_client_instance,
            mock_lib_config.NOCODB_PROJECT_ID,
            "team_id",
            perform_deletions=True,
        )
        self.assertTrue(success_auth)
        # ... (other missing client scenarios updated similarly) ...

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_group_synchronization")
    def test_script_main_sync_logic_orchestration(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = "script_team_id"
        # Ensure script's config doesn't set IDs for optional clients being tested as None
        mock_script_config.OUTLINE_URL = None
        mock_script_config.OUTLINE_TOKEN = None
        mock_script_config.BREVO_API_URL = None
        mock_script_config.BREVO_API_KEY = None
        mock_script_config.VAULTWARDEN_ORGANIZATION_ID = None
        mock_script_config.NOCODB_URL = None  # Script does not init NocoDB client
        mock_script_config.NOCODB_TOKEN = None
        mock_script_config.NOCODB_PROJECT_ID = None  # Script does not pass this directly from its own config

        mock_auth_instance = MagicMock(spec=AuthentikClient)
        mock_mm_instance = MagicMock(spec=MattermostClient)

        # initialize_clients in script returns 5 clients (Auth, MM, Outline, Brevo, VW)
        mock_script_init_clients.return_value = (mock_auth_instance, mock_mm_instance, None, None, None)

        mock_orchestrate_lib.return_value = (True, [])
        script_module.main_sync_logic()  # This calls the real initialize_clients from script

        mock_script_init_clients.assert_called_once()

        # orchestrate_group_synchronization expects 7 args: 5 clients + nocodb_project_id + mm_team_id
        # The script's main_sync_logic passes what initialize_clients returns, plus team_id.
        # NocoDB client and project_id will be None because script's initialize_clients doesn't create/return them.
        mock_orchestrate_lib.assert_called_once_with(
            mock_auth_instance,
            mock_mm_instance,
            None,  # outline_client from script init
            None,  # brevo_client from script init
            None,  # vaultwarden_client from script init
            None,  # nocodb_client (this will be None as script's init doesn't make it)
            None,  # nocodb_project_id (this will be None as script's init doesn't pass it)
            "script_team_id",
        )

    # ... (other tests in TestSyncLogic updated similarly if they call initialize_clients or orchestrate_group_synchronization)


if __name__ == "__main__":
    unittest.main()
