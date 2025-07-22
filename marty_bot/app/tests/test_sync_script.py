import json
import logging
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from libraries.services.vaultwarden import VaultwardenService

import asyncio  # For async_test helper

# Functions/modules to be tested
import scripts.sync_mm_authentik_groups as script_module

# Client classes for type hinting and MagicMock spec
from clients.authentik_client import AuthentikClient
from clients.brevo_client import BrevoClient
from clients.mattermost_client import MattermostClient
from clients.nocodb_client import NocoDBClient
from clients.outline_client import OutlineClient
from clients.vaultwarden_client import VaultwardenClient  # Added
from libraries.group_sync_services import (  # sync_entity_permissions removed as it's not directly used by these tests after refactor
    orchestrate_group_synchronization,
)

# Adjust path to import from the project root directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


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
        with (
            patch("scripts.sync_mm_authentik_groups.OutlineClient") as MockScriptOutlineClient,
            patch("scripts.sync_mm_authentik_groups.BrevoClient") as MockScriptBrevoClient,
            patch("scripts.sync_mm_authentik_groups.NocoDBClient") as MockScriptNocoDBClient,
        ):  # Added NocoDBClient
            mock_outline_instance = MockScriptOutlineClient.return_value
            mock_brevo_instance = MockScriptBrevoClient.return_value
            mock_nocodb_instance = MockScriptNocoDBClient.return_value
            mock_vaultwarden_instance = MagicMock()  # Placeholder for Vaultwarden

            # Patch VaultwardenClient inside this test's context
            with patch(
                "scripts.sync_mm_authentik_groups.VaultwardenClient",
                return_value=mock_vaultwarden_instance,
            ) as MockScriptVWClient:
                (
                    auth_client,
                    mm_client,
                    outline_client,
                    brevo_client,
                    nocodb_client,
                    vw_client,
                ) = script_module.initialize_clients()  # Unpack 6

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

    @patch("libraries.group_sync_services.config")
    @async_test  # Added decorator
    async def test_library_orchestrate_sync_no_groups_found(self, mock_lib_config):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_outline_client = MagicMock(spec=OutlineClient)
        mock_team_id = "team123"
        mock_auth_client.get_groups_with_users.return_value = (
            [],
            {},
        )  # For group discovery part

        clients = {
            "authentik": mock_auth_client,
            "mattermost": mock_mm_client,
            "outline": mock_outline_client,
            "brevo": self.mock_brevo_client_instance,
            "nocodb": MagicMock(spec=NocoDBClient),
            "vaultwarden": MagicMock(spec=VaultwardenClient),
        }
        success, detailed_results = await orchestrate_group_synchronization(
            clients=clients,
            mm_team_id=mock_team_id,
            sync_mode="WITH_AUTHENTIK",
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, [])

    # This test needs to be wrapped if it's to be run by unittest's default discovery with async methods
    # For pytest, @pytest.mark.asyncio would be used, or a helper like async_test from test_bot.py
    # Let's assume an async_test wrapper is available or this will be run with pytest-asyncio
    @async_test  # Added decorator
    async def test_library_orchestrate_sync_core_clients_missing(self):
        mock_outline_client = MagicMock(spec=OutlineClient)

        # Test with Authentik client missing
        clients = {
            "authentik": None,
            "mattermost": MagicMock(spec=MattermostClient),
            "outline": mock_outline_client,
            "brevo": self.mock_brevo_client_instance,
            "nocodb": MagicMock(spec=NocoDBClient),
            "vaultwarden": MagicMock(spec=VaultwardenClient),
        }
        success_auth, results_auth = await orchestrate_group_synchronization(
            clients=clients,
            mm_team_id="team_id",
            sync_mode="WITH_AUTHENTIK",
        )
        self.assertTrue(success_auth)
        self.assertEqual(results_auth, [])

        # Test with Mattermost client missing (critical)
        clients_mm = {
            "authentik": MagicMock(spec=AuthentikClient),
            "mattermost": None,
            "outline": mock_outline_client,
            "brevo": self.mock_brevo_client_instance,
            "nocodb": MagicMock(spec=NocoDBClient),
            "vaultwarden": MagicMock(spec=VaultwardenClient),
        }
        success_mm, results_mm = await orchestrate_group_synchronization(
            clients=clients_mm,
            mm_team_id="team_id",
            sync_mode="WITH_AUTHENTIK",
        )
        self.assertFalse(success_mm)
        self.assertEqual(results_mm, [])

        # Test with Mattermost team_id missing (critical)
        clients_team = {
            "authentik": MagicMock(spec=AuthentikClient),
            "mattermost": MagicMock(spec=MattermostClient),
            "outline": mock_outline_client,
            "brevo": self.mock_brevo_client_instance,
            "nocodb": MagicMock(spec=NocoDBClient),
            "vaultwarden": MagicMock(spec=VaultwardenClient),
        }
        success_team, results_team = await orchestrate_group_synchronization(
            clients=clients_team,
            mm_team_id=None,
            sync_mode="WITH_AUTHENTIK",
        )
        self.assertFalse(success_team)
        self.assertEqual(results_team, [])

    @patch("scripts.sync_mm_authentik_groups.config")
    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch(
        "scripts.sync_mm_authentik_groups.orchestrate_group_synchronization",
        new_callable=unittest.mock.AsyncMock,
    )
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
        clients = {
            "authentik": mock_auth_instance,
            "mattermost": mock_mm_instance,
            "outline": None,
            "brevo": None,
            "nocodb": None,
            "vaultwarden": None,
        }
        clients = {
            "authentik": mock_auth_instance,
            "mattermost": mock_mm_instance,
            "outline": None,
            "brevo": None,
            "nocodb": None,
            "vaultwarden": None,
        }
        mock_orchestrate_lib.assert_called_once_with(
            clients=clients,
            mm_team_id="script_team_id",
            sync_mode="WITH_AUTHENTIK",
            skip_services=None,
        )

    @patch("scripts.sync_mm_authentik_groups.initialize_clients")
    @patch(
        "scripts.sync_mm_authentik_groups.orchestrate_group_synchronization",
        new_callable=unittest.mock.AsyncMock,
    )
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
    @patch(
        "scripts.sync_mm_authentik_groups.orchestrate_group_synchronization",
        new_callable=unittest.mock.AsyncMock,
    )
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


class TestVaultwardenDifferentialSync(unittest.TestCase):
    @async_test
    async def test_differential_sync_removes_user(self):
        # Arrange

        mock_vw_client = MagicMock(spec=VaultwardenClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mm_team_id = "test-team-id"
        permissions_matrix = {"PROJET": {"vaultwarden": {"collection_name_pattern": "projet-{base_name}"}}}

        # Mock Vaultwarden client methods
        mock_vw_client.get_collections_details.return_value = [
            {
                "id": "coll1",
                "name": "projet-test",
                "users": [{"id": "user-to-keep-id"}, {"id": "user-to-remove-id"}],
                "groups": [],
                "externalId": None,
            }
        ]
        mock_vw_client.get_collections.return_value = (0, json.dumps([{"id": "coll1", "name": "projet-test"}]), "")
        mock_vw_client.get_members.return_value = (
            0,
            json.dumps(
                [
                    {"id": "user-to-keep-id", "email": "keep@test.com"},
                    {"id": "user-to-remove-id", "email": "remove@test.com"},
                ]
            ),
            "",
        )
        mock_vw_client.get_name_from_collections.return_value = "projet-test"
        mock_vw_client.get_email_from_members.side_effect = ["keep@test.com", "remove@test.com"]
        mock_vw_client.update_collection.return_value = True

        # Mock Mattermost client to return only the user to keep
        mm_channel_members_data = {"some_channel_id": [{"email": "keep@test.com"}]}

        # Instantiate the service with mocked clients
        vaultwarden_service = VaultwardenService(
            client=mock_vw_client,
            mattermost_client=mock_mm_client,
            permissions_matrix=permissions_matrix,
            mm_team_id=mm_team_id,
        )

        # Mock the get_mm_users_for_entity method on the service instance
        vaultwarden_service.get_mm_users_for_entity = MagicMock(
            return_value=({"keep@test.com": {}}, [{"email": "keep@test.com"}], [])
        )

        # Act
        results = await vaultwarden_service.differential_sync(mm_channel_members_data)

        # Assert
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["action"], "USER_REMOVED_FROM_VAULTWARDEN_COLLECTION")

        # Verify that update_collection was called with the correct payload
        mock_vw_client.update_collection.assert_called_once()
        call_args = mock_vw_client.update_collection.call_args[0]
        collection_id_arg = call_args[0]
        payload_arg = call_args[1]

        self.assertEqual(collection_id_arg, "coll1")
        self.assertEqual(payload_arg["name"], "projet-test")
        self.assertEqual(len(payload_arg["users"]), 1)
        self.assertEqual(payload_arg["users"][0]["id"], "user-to-keep-id")


if __name__ == "__main__":
    unittest.main()
