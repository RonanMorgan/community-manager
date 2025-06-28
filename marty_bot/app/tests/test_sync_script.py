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
from libraries.group_sync_services import (  # noqa: E501
    get_all_authentik_groups_and_user_map,
    sync_entity_permissions, # Renamed
    orchestrate_group_synchronization,
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

    # def test_library_sync_single_group_user_added_successfully_all_services(self):
    #     auth_group = {"pk": "auth_g_pk1", "name": "Dev Team Sync", "users": []}
    #     user_email = "dev1@example.com"
    #     auth_user_pk = "auth_user_pk1"
    #     outline_user_id = "outline_user_id_1"
    #     outline_collection_id = "outline_coll_id_1"
    #
    #     email_map = {user_email: auth_user_pk}
    #     mm_users = [{"email": user_email, "id": "mm_id_1", "username": "dev1"}]

        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id1",
            "display_name": "Dev Team Sync",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = mm_users
        self.mock_auth_client_instance.add_user_to_group.return_value = True
        self.mock_outline_client_instance.get_user_by_email.return_value = {"id": outline_user_id, "email": user_email}
        self.mock_outline_client_instance.get_collection_by_name.return_value = {
            "id": outline_collection_id,
            "name": "Dev Team Sync",
        }
        self.mock_outline_client_instance.get_collection_members.return_value = []
        self.mock_outline_client_instance.add_user_to_collection.return_value = True
        self.mock_outline_client_instance.get_collection_details.return_value = {
            "id": outline_collection_id,
            "name": "Dev Team Sync Official Name",
        }
        self.mock_mm_client_instance.send_dm.return_value = True

        with patch("libraries.group_sync_services.config") as mock_lib_config:
            mock_lib_config.OUTLINE_URL = "http://test-outline.com"
            results = sync_single_group_to_services(
                self.mock_auth_client_instance,
                self.mock_mm_client_instance,
                self.mock_outline_client_instance,
                self.test_mm_team_id,
                auth_group,
                email_map,
            )

        self.assertEqual(len(results), 2)
        auth_result = next(r for r in results if r["service"] == "AUTHENTIK")
        self.assertEqual(auth_result["status"], "SUCCESS")
        self.assertEqual(auth_result["action"], "USER_ADDED_TO_AUTHENTIK_GROUP")
        self.assertEqual(auth_result["mm_username"], "dev1")
        self.mock_auth_client_instance.add_user_to_group.assert_called_once_with(auth_group["pk"], auth_user_pk)

        outline_result = next(r for r in results if r["service"] == "OUTLINE")
        self.assertEqual(outline_result["status"], "SUCCESS")
        self.assertEqual(outline_result["action"], "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_ACCESS_AND_DM_SENT")
        self.assertEqual(outline_result["mm_username"], "dev1")

        # get_user_by_email is called once for the main processing loop,
        # and potentially again inside the Outline removal logic if that user was already in the collection.
        # In this specific test, the user is new, so get_collection_members returns [],
        # meaning the removal logic won't iterate and call get_user_by_email again for this user.
        # However, the new structure for Outline removal (iterating MM users to build temp_outline_id_to_mm_username)
        # means it will be called again.
        self.assertEqual(self.mock_outline_client_instance.get_user_by_email.call_count, 2)
        self.mock_outline_client_instance.get_user_by_email.assert_any_call(user_email)

        self.assertEqual(
            self.mock_outline_client_instance.get_collection_by_name.call_count, 2
        )  # Called in main loop and for removal part
        self.mock_outline_client_instance.get_collection_by_name.assert_any_call(auth_group["name"])
        self.assertEqual(
            self.mock_outline_client_instance.get_collection_members.call_count, 2
        )  # Called in main loop and for removal part
        self.mock_outline_client_instance.get_collection_members.assert_any_call(outline_collection_id)
        self.mock_outline_client_instance.add_user_to_collection.assert_called_once_with(
            outline_collection_id, outline_user_id, permission="read"  # Added permission
        )
        self.mock_outline_client_instance.get_collection_details.assert_called_once_with(outline_collection_id)
        self.mock_mm_client_instance.send_dm.assert_called_once()
        dm_call_args = self.mock_mm_client_instance.send_dm.call_args[0]
        self.assertEqual(dm_call_args[0], "mm_id_1")
        self.assertIn("Dev Team Sync Official Name", dm_call_args[1])
        self.assertIn(
            f"http://test-outline.com/collection/dev-team-sync-official-name-{outline_collection_id}", dm_call_args[1]
        )

        self.mock_mm_client_instance.get_channel_by_name.assert_called_once()
        self.mock_mm_client_instance.get_users_in_channel.assert_called_once_with("mm_chan_id1")

    def test_library_sync_single_group_user_added_successfully_outline_skipped(self):
        auth_group = {"pk": "auth_g_pk1", "name": "Dev Team Sync", "users": []}
        email_map = {"dev1@example.com": "auth_user_pk1"}
        mm_users = [{"email": "dev1@example.com", "id": "mm_id_1", "username": "dev1"}]
        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id1",
            "display_name": "Dev Team Sync",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = mm_users
        self.mock_auth_client_instance.add_user_to_group.return_value = True

        results = sync_single_group_to_services(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            None,
            self.test_mm_team_id,
            auth_group,
            email_map,
        )
        self.assertEqual(len(results), 1)
        auth_result = results[0]
        self.assertEqual(auth_result["service"], "AUTHENTIK")
        self.assertEqual(auth_result["status"], "SUCCESS")
        self.assertEqual(auth_result["action"], "USER_ADDED_TO_AUTHENTIK_GROUP")
        self.mock_auth_client_instance.add_user_to_group.assert_called_once_with("auth_g_pk1", "auth_user_pk1")
        self.mock_outline_client_instance.get_user_by_email.assert_not_called()

    def test_library_sync_single_group_mm_channel_not_found(self):
        auth_group = {"pk": "auth_g_pk1", "name": "NoChannelHere", "users": []}
        self.mock_mm_client_instance.get_channel_by_name.return_value = None
        results = sync_single_group_to_services(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            self.mock_outline_client_instance,
            self.test_mm_team_id,
            auth_group,
            {},
        )
        self.assertEqual(results, [])
        self.mock_mm_client_instance.get_users_in_channel.assert_not_called()

    def test_library_sync_single_group_no_users_added(self):
        auth_group = {"pk": "auth_g_pk1", "name": "Dev Team Sync", "users": ["auth_user_pk1"]}
        email_map = {"dev1@example.com": "auth_user_pk1"}
        mm_users = [{"email": "dev1@example.com", "id": "mm_id_1"}]
        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id1",
            "display_name": "Dev Team Sync",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = mm_users
        self.mock_outline_client_instance.get_user_by_email.return_value = {
            "id": "outline_user_id_1",
            "email": "dev1@example.com",
        }
        self.mock_outline_client_instance.get_collection_by_name.return_value = {
            "id": "outline_coll_id_1",
            "name": "Dev Team Sync",
        }
        outline_user_id_for_test = "outline_user_id_1"
        self.mock_outline_client_instance.get_collection_members.return_value = [outline_user_id_for_test]

        results = sync_single_group_to_services(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            self.mock_outline_client_instance,
            self.test_mm_team_id,
            auth_group,
            email_map,
        )
        self.assertEqual(len(results), 2)
        auth_res = next(r for r in results if r["service"] == "AUTHENTIK")
        self.assertEqual(auth_res["status"], "SUCCESS")
        self.assertEqual(auth_res["action"], "USER_ALREADY_IN_AUTHENTIK_GROUP")
        outline_res = next(r for r in results if r["service"] == "OUTLINE")
        self.assertEqual(outline_res["status"], "SUCCESS")
        self.assertEqual(outline_res["action"], "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED")  # Action
        self.mock_auth_client_instance.add_user_to_group.assert_not_called()
        self.assertEqual(
            self.mock_outline_client_instance.get_collection_members.call_count, 2
        )  # Called in main loop and for removal part
        # add_user_to_collection IS called to ensure permission
        self.mock_outline_client_instance.add_user_to_collection.assert_called_once_with(
            "outline_coll_id_1", "outline_user_id_1", permission="read"  # Assuming default permission
        )
        self.mock_mm_client_instance.send_dm.assert_not_called()

        self.mock_auth_client_instance.reset_mock()
        self.mock_mm_client_instance.reset_mock()
        self.mock_outline_client_instance.reset_mock()

        results_no_outline = sync_single_group_to_services(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            None,
            self.test_mm_team_id,
            auth_group,
            email_map,
        )
        self.assertEqual(len(results_no_outline), 1)
        self.assertEqual(results_no_outline[0]["service"], "AUTHENTIK")
        self.assertEqual(results_no_outline[0]["action"], "USER_ALREADY_IN_AUTHENTIK_GROUP")

    def test_library_sync_single_group_outline_user_not_found(self):
        auth_group = {"pk": "auth_g_pk1", "name": "Dev Team Sync", "users": []}
        user_email = "dev1@example.com"
        email_map = {user_email: "auth_user_pk1"}
        mm_users = [{"email": user_email, "id": "mm_id_1", "username": "dev1"}]
        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id1",
            "display_name": "Dev Team Sync",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = mm_users
        self.mock_auth_client_instance.add_user_to_group.return_value = True
        self.mock_outline_client_instance.get_user_by_email.return_value = None

        results = sync_single_group_to_services(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            self.mock_outline_client_instance,
            self.test_mm_team_id,
            auth_group,
            email_map,
        )
        self.assertEqual(len(results), 2)
        outline_res = next(r for r in results if r["service"] == "OUTLINE")
        self.assertEqual(outline_res["status"], "SKIPPED")
        self.assertEqual(outline_res["action"], "SKIPPED_USER_NOT_IN_OUTLINE")
        # get_collection_by_name IS called once at the group level if outline_client is present
        self.mock_outline_client_instance.get_collection_by_name.assert_called_once_with(auth_group["name"])
        self.mock_outline_client_instance.add_user_to_collection.assert_not_called()

    def test_library_sync_single_group_outline_collection_not_found(self):
        auth_group = {"pk": "auth_g_pk1", "name": "Dev Team Sync", "users": []}
        user_email = "dev1@example.com"
        email_map = {user_email: "auth_user_pk1"}
        mm_users = [{"email": user_email, "id": "mm_id_1", "username": "dev1"}]
        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id1",
            "display_name": "Dev Team Sync",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = mm_users
        self.mock_auth_client_instance.add_user_to_group.return_value = True
        self.mock_outline_client_instance.get_user_by_email.return_value = {"id": "outline_user_id_1"}
        self.mock_outline_client_instance.get_collection_by_name.return_value = None

        results = sync_single_group_to_services(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            self.mock_outline_client_instance,
            self.test_mm_team_id,
            auth_group,
            email_map,
        )
        self.assertEqual(len(results), 2)
        outline_res = next(r for r in results if r["service"] == "OUTLINE")
        self.assertEqual(outline_res["status"], "SKIPPED")
        self.assertEqual(outline_res["action"], "SKIPPED_OUTLINE_COLLECTION_NOT_FOUND")
        self.mock_outline_client_instance.add_user_to_collection.assert_not_called()

    def test_library_sync_single_group_outline_add_user_fails(self):
        auth_group = {"pk": "auth_g_pk1", "name": "Dev Team Sync", "users": []}
        user_email = "dev1@example.com"
        email_map = {user_email: "auth_user_pk1"}
        mm_users = [{"email": user_email, "id": "mm_id_1", "username": "dev1"}]
        self.mock_mm_client_instance.get_channel_by_name.return_value = {
            "id": "mm_chan_id1",
            "display_name": "Dev Team Sync",
        }
        self.mock_mm_client_instance.get_users_in_channel.return_value = mm_users
        self.mock_auth_client_instance.add_user_to_group.return_value = True
        self.mock_outline_client_instance.get_user_by_email.return_value = {"id": "outline_user_id_1"}
        self.mock_outline_client_instance.get_collection_by_name.return_value = {"id": "outline_coll_id_1"}
        self.mock_outline_client_instance.add_user_to_collection.return_value = False

        results = sync_single_group_to_services(
            self.mock_auth_client_instance,
            self.mock_mm_client_instance,
            self.mock_outline_client_instance,
            self.test_mm_team_id,
            auth_group,
            email_map,
        )
        self.assertEqual(len(results), 2)
        outline_res = next(r for r in results if r["service"] == "OUTLINE")
        self.assertEqual(outline_res["status"], "FAILURE")
        self.assertEqual(outline_res["action"], "FAILED_TO_ADD_TO_OUTLINE_COLLECTION")

    def test_library_sync_single_group_client_missing(self):
        results_no_auth = sync_single_group_to_services(
            None, self.mock_mm_client_instance, self.mock_outline_client_instance, self.test_mm_team_id, {}, {}
        )
        self.assertEqual(results_no_auth, [])
        results_no_mm = sync_single_group_to_services(
            self.mock_auth_client_instance, None, self.mock_outline_client_instance, self.test_mm_team_id, {}, {}
        )
        self.assertEqual(results_no_mm, [])

    @patch("libraries.group_sync_services.sync_single_group_to_services")
    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    def test_library_orchestrate_sync_success_all_clients(self, mock_get_groups_map, mock_sync_single_group):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_outline_client = MagicMock(spec=OutlineClient)
        mock_team_id = "team123"
        mock_groups_list = [{"name": "group1", "pk": "g1"}, {"name": "group2", "pk": "g2"}]
        mock_email_pk_map = {"user1@example.com": "upk1"}
        mock_get_groups_map.return_value = (mock_groups_list, mock_email_pk_map)
        mock_sync_single_group.side_effect = [
            [
                {"service": "AUTHENTIK", "action": "USER_ADDED_TO_AUTHENTIK_GROUP", "status": "SUCCESS"},
                {"service": "OUTLINE", "action": "USER_MEMBERSHIP_ENSURED_IN_OUTLINE_COLLECTION", "status": "SUCCESS"},
            ],
            [
                {"service": "AUTHENTIK", "action": "USER_ALREADY_IN_AUTHENTIK_GROUP", "status": "SUCCESS"},
                {"service": "OUTLINE", "action": "USER_MEMBERSHIP_ENSURED_IN_OUTLINE_COLLECTION", "status": "SUCCESS"},
            ],
        ]
        expected_detailed_results = [
            {"service": "AUTHENTIK", "action": "USER_ADDED_TO_AUTHENTIK_GROUP", "status": "SUCCESS"},
            {"service": "OUTLINE", "action": "USER_MEMBERSHIP_ENSURED_IN_OUTLINE_COLLECTION", "status": "SUCCESS"},
            {"service": "AUTHENTIK", "action": "USER_ALREADY_IN_AUTHENTIK_GROUP", "status": "SUCCESS"},
            {"service": "OUTLINE", "action": "USER_MEMBERSHIP_ENSURED_IN_OUTLINE_COLLECTION", "status": "SUCCESS"},
        ]
        success, detailed_results = orchestrate_group_synchronization(
            mock_auth_client, mock_mm_client, mock_outline_client, mock_team_id
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, expected_detailed_results)
        mock_get_groups_map.assert_called_once_with(mock_auth_client)
        self.assertEqual(mock_sync_single_group.call_count, 2)
        mock_sync_single_group.assert_any_call(
            mock_auth_client, mock_mm_client, mock_outline_client, mock_team_id, mock_groups_list[0], mock_email_pk_map
        )  # noqa: E501
        mock_sync_single_group.assert_any_call(
            mock_auth_client, mock_mm_client, mock_outline_client, mock_team_id, mock_groups_list[1], mock_email_pk_map
        )  # noqa: E501

    @patch("libraries.group_sync_services.sync_single_group_to_services")
    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    def test_library_orchestrate_sync_success_outline_client_none(self, mock_get_groups_map, mock_sync_single_group):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_team_id = "team123"
        mock_outline_client_none = None
        mock_groups_list = [{"name": "group1", "pk": "g1"}]
        mock_email_pk_map = {"user1@example.com": "upk1"}
        mock_get_groups_map.return_value = (mock_groups_list, mock_email_pk_map)
        mock_sync_single_group.return_value = [
            {"service": "AUTHENTIK", "action": "USER_ADDED_TO_AUTHENTIK_GROUP", "status": "SUCCESS"}
        ]
        expected_detailed_results = [
            {"service": "AUTHENTIK", "action": "USER_ADDED_TO_AUTHENTIK_GROUP", "status": "SUCCESS"}
        ]
        success, detailed_results = orchestrate_group_synchronization(
            mock_auth_client, mock_mm_client, mock_outline_client_none, mock_team_id
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, expected_detailed_results)
        mock_sync_single_group.assert_called_once_with(
            mock_auth_client,
            mock_mm_client,
            mock_outline_client_none,
            mock_team_id,
            mock_groups_list[0],
            mock_email_pk_map,
        )

    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    def test_library_orchestrate_sync_no_groups_found(self, mock_get_groups_map):
        mock_auth_client = MagicMock(spec=AuthentikClient)
        mock_mm_client = MagicMock(spec=MattermostClient)
        mock_outline_client = MagicMock(spec=OutlineClient)
        mock_team_id = "team123"
        mock_get_groups_map.return_value = ([], {})
        success, detailed_results = orchestrate_group_synchronization(
            mock_auth_client, mock_mm_client, mock_outline_client, mock_team_id
        )
        self.assertTrue(success)
        self.assertEqual(detailed_results, [])
        mock_get_groups_map.assert_called_once_with(mock_auth_client)

    def test_library_orchestrate_sync_core_clients_missing(self):
        mock_outline_client = MagicMock(spec=OutlineClient)
        success_auth, results_auth = orchestrate_group_synchronization(
            None, MagicMock(spec=MattermostClient), mock_outline_client, "team_id"
        )
        self.assertFalse(success_auth)
        self.assertEqual(results_auth, [])
        success_mm, results_mm = orchestrate_group_synchronization(
            MagicMock(spec=AuthentikClient), None, mock_outline_client, "team_id"
        )
        self.assertFalse(success_mm)
        self.assertEqual(results_mm, [])
        success_team, results_team = orchestrate_group_synchronization(
            MagicMock(spec=AuthentikClient), MagicMock(spec=MattermostClient), mock_outline_client, None
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
