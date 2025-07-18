import unittest
from unittest.mock import patch, MagicMock
import logging
import sys
import os
import json

# Adjust path to import from the project root directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Client classes for type hinting and MagicMock spec
from clients.authentik_client import AuthentikClient
from clients.mattermost_client import MattermostClient
from clients.outline_client import OutlineClient
from clients.brevo_client import BrevoClient
from clients.nocodb_client import NocoDBClient
from clients.vaultwarden_client import VaultwardenClient  # Added

import asyncio  # For async_test helper

# Functions/modules to be tested
import scripts.sync_mm_authentik_groups as script_module
from libraries.group_sync_services import (
    get_all_authentik_groups_and_user_map,
    orchestrate_group_synchronization,
    # sync_entity_permissions removed as it's not directly used by these tests after refactor
)


# Helper to run async test methods (copied from test_bot.py)
def async_test(f):
    def wrapper(*args, **kwargs):
        asyncio.run(f(*args, **kwargs))

    return wrapper


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
        # Mock OutlineClient and BrevoClient if they are part of initialize_clients
        with patch("scripts.sync_mm_authentik_groups.OutlineClient") as MockScriptOutlineClient, patch(
            "scripts.sync_mm_authentik_groups.BrevoClient"
        ) as MockScriptBrevoClient, patch(
            "scripts.sync_mm_authentik_groups.NocoDBClient"
        ) as MockScriptNocoDBClient:  # Added NocoDBClient
            mock_outline_instance = MockScriptOutlineClient.return_value
            mock_brevo_instance = MockScriptBrevoClient.return_value
            mock_nocodb_instance = MockScriptNocoDBClient.return_value
            mock_vaultwarden_instance = MagicMock()  # Placeholder for Vaultwarden

            # Patch VaultwardenClient inside this test's context
            with patch(
                "scripts.sync_mm_authentik_groups.VaultwardenClient", return_value=mock_vaultwarden_instance
            ) as MockScriptVWClient:
                auth_client, mm_client, outline_client, brevo_client, nocodb_client, vw_client = (
                    script_module.initialize_clients()
                )  # Unpack 6

            MockScriptAuthClient.assert_called_once_with("http://auth.example.com", "auth_token")
            MockScriptMMClient.assert_called_once_with("http://mm.example.com", "mm_bot_token", "mm_team_id")
            MockScriptOutlineClient.assert_called_once_with("http://outline.example.com", "outline_token")
            MockScriptBrevoClient.assert_called_once_with("http://brevo.example.com", "brevo_key")
            MockScriptNocoDBClient.assert_called_once_with(
                mock_script_config.NOCODB_URL, mock_script_config.NOCODB_TOKEN
            )  # Added

            self.assertEqual(auth_client, mock_auth_instance)
            self.assertEqual(mm_client, mock_mm_instance)
            self.assertEqual(outline_client, mock_outline_instance)
            self.assertEqual(brevo_client, mock_brevo_instance)
            self.assertEqual(nocodb_client, mock_nocodb_instance)
            self.assertEqual(vw_client, mock_vaultwarden_instance)  # Added Vaultwarden check
            MockScriptVWClient.assert_called_once()  # Ensure VW Client was called

    @patch("scripts.sync_mm_authentik_groups.AuthentikClient")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_script_initialize_clients_auth_missing_config(self, mock_script_config, MockScriptAuthClient):
        mock_script_config.AUTHENTIK_URL = None
        mock_script_config.AUTHENTIK_TOKEN = "token"
        # ... (rest of config vars)
        mock_script_config.NOCODB_URL = "http://nocodb.example.com"
        mock_script_config.NOCODB_TOKEN = "nocodb_token"
        mock_script_config.VAULTWARDEN_ORGANIZATION_ID = "vw_org"  # Ensure all config vars for other clients
        mock_script_config.VAULTWARDEN_SERVER_URL = "http://vw.com"
        mock_script_config.VAULTWARDEN_API_USERNAME = "user"
        mock_script_config.VAULTWARDEN_API_PASSWORD = "pass"

        auth_client, _, _, _, _, _ = script_module.initialize_clients()  # Unpack 6
        self.assertIsNone(auth_client)
        MockScriptAuthClient.assert_not_called()

    @patch("scripts.sync_mm_authentik_groups.MattermostClient")
    @patch("scripts.sync_mm_authentik_groups.config")
    def test_script_initialize_clients_mm_missing_config(self, mock_script_config, MockScriptMMClient):
        mock_script_config.MATTERMOST_URL = None
        mock_script_config.BOT_TOKEN = "token"
        # ... (rest of config vars)
        mock_script_config.NOCODB_URL = "http://nocodb.example.com"
        mock_script_config.NOCODB_TOKEN = "nocodb_token"
        mock_script_config.VAULTWARDEN_ORGANIZATION_ID = "vw_org"
        mock_script_config.VAULTWARDEN_SERVER_URL = "http://vw.com"
        mock_script_config.VAULTWARDEN_API_USERNAME = "user"
        mock_script_config.VAULTWARDEN_API_PASSWORD = "pass"
        _, mm_client, _, _, _, _ = script_module.initialize_clients()  # Unpack 6
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
    @async_test  # Added decorator
    async def test_library_orchestrate_sync_success_all_clients(
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
        mock_get_groups_map.return_value = (mock_groups_list, mock_email_pk_map)  # For the email map part
        # Also mock the direct call to authentik_client.get_groups_with_users for group discovery
        mock_auth_client.get_groups_with_users.return_value = (mock_groups_list, mock_email_pk_map)

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
        success, detailed_results = await orchestrate_group_synchronization(  # Added await
            authentik_client=mock_auth_client,
            mattermost_client=mock_mm_client,
            outline_client=mock_outline_client,
            brevo_client=self.mock_brevo_client_instance,
            nocodb_client=MagicMock(spec=NocoDBClient),
            vaultwarden_client=MagicMock(spec=VaultwardenClient),
            mm_team_id=mock_team_id,
            perform_deletions=True,
            sync_mode="FULL_SYNC",  # Assuming default test was for full sync (fetch_remote_members=True)
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, expected_detailed_results)
        mock_get_groups_map.assert_called_once_with(mock_auth_client)
        self.assertEqual(mock_sync_entity_permissions.call_count, 2)
        mock_sync_entity_permissions.assert_any_call(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client,
            self.mock_brevo_client_instance,
            unittest.mock.ANY,  # nocodb_client
            unittest.mock.ANY,  # vaultwarden_client
            mock_team_id,
            "alpha",
            "PROJET",
            mock_lib_config.PERMISSIONS_MATRIX["PROJET"],
            unittest.mock.ANY,
            mock_email_pk_map,
            True,
            skip_services=[],  # Added expected default
        )
        mock_sync_entity_permissions.assert_any_call(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client,
            self.mock_brevo_client_instance,
            unittest.mock.ANY,  # nocodb_client
            unittest.mock.ANY,  # vaultwarden_client
            mock_team_id,
            "beta",
            "ANTENNE",
            mock_lib_config.PERMISSIONS_MATRIX["ANTENNE"],
            unittest.mock.ANY,
            mock_email_pk_map,
            True,
            skip_services=[],  # Corrected: ensure only one skip_services
        )

    @patch("libraries.group_sync_services.sync_entity_permissions")
    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    @patch("libraries.group_sync_services.config")
    @async_test  # Added decorator
    async def test_library_orchestrate_sync_success_outline_client_none(
        self, mock_lib_config, mock_get_groups_map, mock_sync_entity_permissions
    ):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_team_id = "team123"
        mock_outline_client_none = None
        mock_groups_list = [{"name": "projet_gamma", "pk": "g_gamma", "users": [], "users_obj": []}]
        mock_email_pk_map = {"usergamma@example.com": "upk_gamma"}
        mock_get_groups_map.return_value = (mock_groups_list, mock_email_pk_map)  # For email map
        mock_auth_client.get_groups_with_users.return_value = (
            mock_groups_list,
            mock_email_pk_map,
        )  # For group discovery

        mock_lib_config.PERMISSIONS_MATRIX = {
            "PROJET": {"standard": {"authentik_group_name_pattern": "projet_{base_name}"}}
        }
        mock_sync_entity_permissions.return_value = [{"service": "AUTHENTIK_ONLY", "status": "SUCCESS"}]
        expected_detailed_results = [{"service": "AUTHENTIK_ONLY", "status": "SUCCESS"}]
        success, detailed_results = await orchestrate_group_synchronization(  # Added await
            authentik_client=mock_auth_client,
            mattermost_client=mock_mm_client,
            outline_client=mock_outline_client_none,
            brevo_client=self.mock_brevo_client_instance,
            nocodb_client=MagicMock(spec=NocoDBClient),
            vaultwarden_client=MagicMock(spec=VaultwardenClient),
            mm_team_id=mock_team_id,
            perform_deletions=True,
            sync_mode="FULL_SYNC",  # Assuming default test was for full sync
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, expected_detailed_results)
        mock_sync_entity_permissions.assert_called_once_with(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client_none,
            self.mock_brevo_client_instance,
            unittest.mock.ANY,  # nocodb_client
            unittest.mock.ANY,  # vaultwarden_client
            mock_team_id,
            "gamma",
            "PROJET",
            mock_lib_config.PERMISSIONS_MATRIX["PROJET"],
            unittest.mock.ANY,
            mock_email_pk_map,
            True,
            skip_services=[],  # Added expected default
        )

    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    @patch("libraries.group_sync_services.config")
    @async_test  # Added decorator
    async def test_library_orchestrate_sync_no_groups_found(self, mock_lib_config, mock_get_groups_map):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_outline_client = MagicMock(spec=OutlineClient)
        mock_team_id = "team123"
        mock_get_groups_map.return_value = ([], {})  # For email map part
        mock_auth_client.get_groups_with_users.return_value = ([], {})  # For group discovery part

        success, detailed_results = await orchestrate_group_synchronization(  # Added await
            authentik_client=mock_auth_client,
            mattermost_client=mock_mm_client,
            outline_client=mock_outline_client,
            brevo_client=self.mock_brevo_client_instance,
            nocodb_client=MagicMock(spec=NocoDBClient),
            vaultwarden_client=MagicMock(spec=VaultwardenClient),
            mm_team_id=mock_team_id,
            perform_deletions=True,
            sync_mode="FULL_SYNC",  # Assuming default test was for full sync
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, [])
        mock_get_groups_map.assert_called_once_with(mock_auth_client)

    # This test needs to be wrapped if it's to be run by unittest's default discovery with async methods
    # For pytest, @pytest.mark.asyncio would be used, or a helper like async_test from test_bot.py
    # Let's assume an async_test wrapper is available or this will be run with pytest-asyncio
    @async_test  # Added decorator
    async def test_library_orchestrate_sync_core_clients_missing(self):
        mock_outline_client = MagicMock(spec=OutlineClient)

        # Test with Authentik client missing
        success_auth, results_auth = await orchestrate_group_synchronization(
            authentik_client=None,
            mattermost_client=MagicMock(spec=MattermostClient),
            outline_client=mock_outline_client,
            brevo_client=self.mock_brevo_client_instance,
            nocodb_client=MagicMock(spec=NocoDBClient),
            vaultwarden_client=MagicMock(spec=VaultwardenClient),
            mm_team_id="team_id",
            perform_deletions=True,
            sync_mode="FULL_SYNC",
        )
        self.assertTrue(success_auth)
        self.assertEqual(results_auth, [])

        # Test with Mattermost client missing (critical)
        success_mm, results_mm = await orchestrate_group_synchronization(
            authentik_client=MagicMock(spec=AuthentikClient),
            mattermost_client=None,
            outline_client=mock_outline_client,
            brevo_client=self.mock_brevo_client_instance,
            nocodb_client=MagicMock(spec=NocoDBClient),
            vaultwarden_client=MagicMock(spec=VaultwardenClient),
            mm_team_id="team_id",
            perform_deletions=True,
            sync_mode="FULL_SYNC",
        )
        self.assertFalse(success_mm)
        self.assertEqual(results_mm, [])

        # Test with Mattermost team_id missing (critical)
        success_team, results_team = await orchestrate_group_synchronization(
            authentik_client=MagicMock(spec=AuthentikClient),
            mattermost_client=MagicMock(spec=MattermostClient),
            outline_client=mock_outline_client,
            brevo_client=self.mock_brevo_client_instance,
            nocodb_client=MagicMock(spec=NocoDBClient),
            vaultwarden_client=MagicMock(spec=VaultwardenClient),
            mm_team_id=None,
            perform_deletions=True,
            sync_mode="FULL_SYNC",
        )
        self.assertFalse(success_team)
        self.assertEqual(results_team, [])

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_group_synchronization", new_callable=unittest.mock.AsyncMock)
    @async_test
    async def test_script_main_sync_logic_orchestration(
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = "script_team_id"
        mock_script_config.OUTLINE_URL = None
        mock_script_config.OUTLINE_TOKEN = None
        mock_script_config.BREVO_API_URL = None
        mock_script_config.BREVO_API_KEY = None
        mock_script_config.NOCODB_URL = None
        mock_script_config.NOCODB_TOKEN = None
        mock_auth_instance = MagicMock(spec=AuthentikClient)
        mock_mm_instance = MagicMock(spec=MattermostClient)
        mock_script_init_clients.return_value = (
            mock_auth_instance,
            mock_mm_instance,
            None,
            None,
            None,
            None,
        )
        mock_orchestrate_lib.return_value = (True, [])

        await script_module.main_sync_logic()  # Added await

        mock_script_init_clients.assert_called_once()
        mock_orchestrate_lib.assert_called_once_with(
            authentik_client=mock_auth_instance,
            mattermost_client=mock_mm_instance,
            outline_client=None,
            brevo_client=None,
            nocodb_client=None,
            vaultwarden_client=None,
            mm_team_id="script_team_id",
            perform_deletions=True,  # Default from script
            sync_mode="FULL_SYNC",  # Default from script
            skip_services=None,  # Default from script
        )

    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_group_synchronization", new_callable=unittest.mock.AsyncMock)
    @async_test
    async def test_script_main_sync_logic_init_auth_fails(self, mock_orchestrate_lib, mock_script_init_clients):
        with patch("scripts.sync_mm_authentik_groups.config") as mock_script_config:
            mock_script_config.MATTERMOST_TEAM_ID = "script_team_id"
            mock_script_config.OUTLINE_URL = None
            mock_script_config.OUTLINE_TOKEN = None
        mock_script_config.BREVO_API_URL = None
        mock_script_config.BREVO_API_KEY = None
        mock_script_config.NOCODB_URL = None
        mock_script_config.NOCODB_TOKEN = None
        mock_script_init_clients.return_value = (
            MagicMock(spec=AuthentikClient),
            None,
            None,
            None,
            None,
            None,
        )
        await script_module.main_sync_logic()  # Added await
        mock_orchestrate_lib.assert_not_called()

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch("scripts.sync_mm_authentik_groups.orchestrate_group_synchronization", new_callable=unittest.mock.AsyncMock)
    @async_test  # Added decorator
    async def test_script_main_sync_logic_no_team_id(  # Corrected function name
        self, mock_orchestrate_lib, mock_script_init_clients, mock_script_config
    ):
        mock_script_config.MATTERMOST_TEAM_ID = None
        mock_script_config.OUTLINE_URL = None
        mock_script_config.OUTLINE_TOKEN = None
        mock_script_config.BREVO_API_URL = None
        mock_script_config.BREVO_API_KEY = None
        mock_script_config.NOCODB_URL = None
        mock_script_config.NOCODB_TOKEN = None
        mock_script_init_clients.return_value = (
            MagicMock(spec=AuthentikClient),
            MagicMock(spec=MattermostClient),
            None,
            None,
            None,
            None,
        )
        await script_module.main_sync_logic()  # Added await
        mock_orchestrate_lib.assert_not_called()


class TestVaultwardenSync(unittest.TestCase):
    @patch("clients.authentik_client.AuthentikClient")
    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    @patch("libraries.group_sync_services._get_mm_users_for_entity")
    @patch("libraries.group_sync_services._map_vaultwarden_collection_to_entity_and_base_name")
    def test_sync_vaultwarden_removes_user(self, mock_map_collection, mock_get_users, mock_get_auth_groups, mock_auth_client_class):
        # Arrange
        mock_auth_instance = mock_auth_client_class.return_value
        mock_auth_instance.get_groups_with_users.return_value = ([], {})
        mock_get_auth_groups.return_value = ([], {"user1@test.com": "user1-pk", "user2@test.com": "user2-pk"})
        mock_vw_client = MagicMock(spec=VaultwardenClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mm_team_id = "test-team-id"
        mock_vw_client.get_collections_details.return_value = [
            {
                "id": "coll1",
                "name": "projet-test",
                "users": [{"id": "user1-pk"}, {"id": "user2-pk"}],
            }
        ]
        mock_vw_client.get_collections.return_value = (0, json.dumps([{"id": "coll1", "name": "projet-test", "organizationId": "test-org-id"}]), "")
        mock_vw_client.get_members.return_value = (0, json.dumps([{"id": "user1-pk", "email": "user1@test.com"}, {"id": "user2-pk", "email": "user2@test.com"}]), "")
        mock_vw_client.get_name_from_collections.return_value = "projet-test"
        mock_vw_client.get_email_from_members.side_effect = ["user1@test.com", "user2@test.com"]
        mock_map_collection.return_value = ("PROJET", "test")
        mock_get_users.return_value = ({"user1@test.com": {}}, [], [])
        mock_vw_client.update_collection.return_value = True

        # Act
        success, results = asyncio.run(
            orchestrate_group_synchronization(
                authentik_client=mock_auth_instance,
                mattermost_client=mock_mm_client,
                outline_client=None,
                brevo_client=None,
                nocodb_client=None,
                vaultwarden_client=mock_vw_client,
                mm_team_id=mm_team_id,
                perform_deletions=True,
                sync_mode="TOOLS_TO_MM",
            )
        )

        # Assert
        mock_vw_client.update_collection.assert_called_once()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["action"], "USER_REMOVED_FROM_VAULTWARDEN_COLLECTION")


if __name__ == "__main__":
    unittest.main()
