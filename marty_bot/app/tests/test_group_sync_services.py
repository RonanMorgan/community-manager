import unittest
import os # <-- ADDED IMPORT
from unittest.mock import patch, MagicMock, mock_open

from libraries.group_sync_services import sync_entity_permissions, orchestrate_group_synchronization, _sync_single_authentik_group, _sync_single_outline_collection # Added helpers for focused testing

# Assuming your config is accessible and can be patched, or you can patch its usage directly
# For example, if group_sync_services imports 'from app import config'
# you can patch 'libraries.group_sync_services.config'
from app import config as app_config  # Import the actual config to potentially reload/reset it

# Removed: import dotenv
from clients.mattermost_client import slugify  # For test URL construction


# Helper to reset parts of the config if necessary between tests,
# especially if it's loaded at import time.
def reload_config_module():
    import importlib

    importlib.reload(app_config)


class TestGroupSyncServices(unittest.TestCase):

    def setUp(self):
        # Reset EXCLUDED_USERS before each test to avoid interference
        app_config.EXCLUDED_USERS = set()

        self.mock_authentik_client = MagicMock()
        self.mock_mattermost_client = MagicMock()
        self.mock_outline_client = MagicMock()

        self.mm_team_id = "test_team_id"
        self.auth_group_name = "Test Group"
        self.auth_group_pk = "auth_group_pk_123"
        self.authentik_group_fixture = {
            "name": self.auth_group_name,
            "pk": self.auth_group_pk,
            "users": [],  # Initially empty
        }
        self.email_to_authentik_user_pk_map_fixture = {
            "user1@example.com": "auth_user_pk_1",
            "user2@example.com": "auth_user_pk_2",
            "excludeduser@example.com": "auth_user_pk_excluded",
            "marty@example.com": "auth_user_pk_marty",
        }
        self.mm_channel_fixture = {
            "id": "mm_channel_id_123",
            "display_name": "Test Group Channel",
            "name": "test-group-channel",  # slug
        }
        self.mm_users_fixture = [
            {"username": "user1", "email": "user1@example.com", "id": "mm_user_id_1"},
            {"username": "user2", "email": "user2@example.com", "id": "mm_user_id_2"},
            {"username": "excluded_user", "email": "excludeduser@example.com", "id": "mm_user_id_excluded"},
            {"username": "marty", "email": "marty@example.com", "id": "mm_user_id_marty"},
        ]

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_user_exclusion(self, mock_config):
        # Setup: Define an excluded user in the mocked config
        mock_config.EXCLUDED_USERS = {"excluded_user", "marty"}

        # Mock client responses
        self.mock_mattermost_client.get_channel_by_name.return_value = self.mm_channel_fixture
        self.mock_mattermost_client.get_users_in_channel.return_value = self.mm_users_fixture
        self.mock_authentik_client.add_user_to_group.return_value = True  # Assume success for non-excluded

        # Mock Outline client methods to avoid None errors if called
        self.mock_outline_client.get_user_by_email.return_value = {"id": "outline_user_id_1"}
        self.mock_outline_client.get_collection_by_name.return_value = {"id": "outline_collection_id_1"}
        self.mock_outline_client.add_user_to_collection.return_value = True

        # TODO: This test needs complete refactoring for sync_entity_permissions
        # Old call:
        # results = sync_single_group_to_services(
        #     authentik_client=self.mock_authentik_client,
        #     mattermost_client=self.mock_mattermost_client,
        #     outline_client=self.mock_outline_client,  # Pass mock Outline client
        #     mm_team_id=self.mm_team_id,
        #     authentik_group=self.authentik_group_fixture,
        #     email_to_authentik_user_pk_map=self.email_to_authentik_user_pk_map_fixture,
        # )
        # For now, let's call it with placeholder new args to avoid NameError, will fail on logic
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
            entity_key="PROJET", # Placeholder
            base_name="TestGroup", # Placeholder
            # entity_config would come from app_config.PERMISSIONS_MATRIX[entity_key]
            # For this test, we'd need to mock app_config.PERMISSIONS_MATRIX or pass a suitable dict
            entity_config=app_config.PERMISSIONS_MATRIX.get("PROJET", {}), # Basic placeholder
            all_authentik_users_by_email=self.email_to_authentik_user_pk_map_fixture, # This is actually email to PK map, not user objects
            dry_run=False
        )


        # Assertions
        # 2 users processed (user1, user2) x 2 services (Authentik, Outline) = 4 results
        # 2 users skipped (excluded_user, marty) generate 0 results each.
        # Total = 4
        self.assertEqual(len(results), 4)

        # Detailed check for results
        processed_usernames_authentik = set()
        processed_usernames_outline = set()

        for r in results:
            # Ensure no results for excluded users are present
            self.assertNotIn(r.get("mm_username"), {"excluded_user", "marty"})
            self.assertNotEqual(r.get("action"), "SKIPPED_USER_EXCLUDED")

            if r.get("service") == "AUTHENTIK" and r.get("status") == "SUCCESS":
                processed_usernames_authentik.add(r["mm_username"])
            elif r.get("service") == "OUTLINE" and r.get("status") == "SUCCESS":
                processed_usernames_outline.add(r["mm_username"])

        self.assertNotIn("excluded_user", processed_usernames_authentik)
        self.assertNotIn("marty", processed_usernames_authentik)
        self.assertNotIn("excluded_user", processed_usernames_outline)
        self.assertNotIn("marty", processed_usernames_outline)

        self.assertIn("user1", processed_usernames_authentik)
        self.assertIn("user2", processed_usernames_authentik)
        self.assertIn("user1", processed_usernames_outline)
        self.assertIn("user2", processed_usernames_outline)

        # Verify Authentik add_user_to_group calls
        # Called for user1 and user2, but not for excluded_user or marty
        self.assertEqual(self.mock_authentik_client.add_user_to_group.call_count, 2)
        # Example check for one of the calls (more specific checks can be added)
        self.mock_authentik_client.add_user_to_group.assert_any_call(
            self.auth_group_pk, self.email_to_authentik_user_pk_map_fixture["user1@example.com"]
        )
        self.mock_authentik_client.add_user_to_group.assert_any_call(
            self.auth_group_pk, self.email_to_authentik_user_pk_map_fixture["user2@example.com"]
        )

        # Verify Outline add_user_to_collection calls
        self.assertEqual(self.mock_outline_client.add_user_to_collection.call_count, 2)

    # @patch("libraries.group_sync_services.config")
    # @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    # @patch("libraries.group_sync_services.sync_entity_permissions") # TODO: Update this test for new orchestrator logic
    # def test_orchestrate_group_synchronization_respects_exclusion_via_single_sync(
    #     self, mock_sync_entity, mock_get_groups, mock_config
    # ):
    #     # This test needs significant rework due to the change from group-based to entity-based sync
    #     # and the direct call to sync_entity_permissions.
    #     # For now, commenting out the core logic.
    #     pass

    # Most tests below this line were calling the old sync_single_group_to_services
    # and need to be refactored or removed. Commenting them out for now.

    # @patch("libraries.group_sync_services.config")
    # def test_sync_single_group_user_exclusion(self, mock_config):
    #     pass # Needs rewrite for sync_entity_permissions or helpers

    # @patch("libraries.group_sync_services.config")  # To mock config.OUTLINE_URL
    # def test_sync_single_group_outline_dm_on_new_add(self, mock_config):
    #     pass # Needs rewrite

    # @patch("libraries.group_sync_services.config")
    # def test_sync_single_group_outline_dm_fails(self, mock_config):
    #     pass # Needs rewrite

    # @patch("libraries.group_sync_services.config")
    # def test_sync_single_group_outline_user_already_member_no_dm(self, mock_config):
    #     pass # Needs rewrite

    # @patch("libraries.group_sync_services.config")
    # def test_sync_single_group_authentik_user_removed_if_not_in_mm(self, mock_config_module):
    #     pass # Needs rewrite for _sync_single_authentik_group or sync_entity_permissions

    # @patch("libraries.group_sync_services.config")
    # def test_sync_single_group_authentik_excluded_user_not_removed_if_not_in_mm(self, mock_config_module):
    #     pass # Needs rewrite for _sync_single_authentik_group or sync_entity_permissions

    # @patch("libraries.group_sync_services.config")
    # def test_sync_single_group_outline_user_removed_if_not_in_mm(self, mock_config_module):
    #     pass # Needs rewrite for _sync_single_outline_collection or sync_entity_permissions

    # @patch("libraries.group_sync_services.config")
    # def test_sync_single_group_outline_excluded_user_not_removed(self, mock_config_module):
    #     pass # Needs rewrite

    # @patch("libraries.group_sync_services.config")  # To mock config.PERMISSIONS_MATRIX
    # def test_sync_single_group_outline_permissions(self, mock_config_module):
    #     pass # Needs rewrite

    @patch("dotenv.main.find_dotenv", return_value=None)
    @patch("os.getenv")
    @patch("builtins.open")
    @patch("os.path.exists")
    def test_config_loading_file_not_found(self, mock_exists, mock_open_file, mock_getenv, mock_find_dotenv):
        # Mock getenv to return dummy paths for config files
        def getenv_side_effect(key, default=None):
            if key == "EXCLUDED_USERS_FILE_PATH":
                return "dummy_path/non_existent_excluded.txt"
            if key == "PERMISSIONS_MATRIX_FILE_PATH":
                return "dummy_path/non_existent_matrix.yml"
            return os.environ.get(key, default) # Fallback for other env vars
        mock_getenv.side_effect = getenv_side_effect

        # Mock os.path.exists to return False for these dummy paths
        mock_exists.return_value = False

        app_config.EXCLUDED_USERS = {"dummy"}
        app_config.PERMISSIONS_MATRIX = {"dummy": "data"}
        reload_config_module()

        self.assertEqual(app_config.EXCLUDED_USERS, set())
        self.assertEqual(app_config.PERMISSIONS_MATRIX, {})
        mock_open_file.assert_not_called() # open should not be called if files don't exist

    @patch("dotenv.main.find_dotenv", return_value=None)
    @patch("os.getenv")
    @patch("builtins.open")
    @patch("os.path.exists")
    def test_config_loading_empty_file(self, mock_exists, mock_open_file, mock_getenv, mock_find_dotenv):
        dummy_excluded_path = "dummy_path/existent_empty_excluded.txt"
        dummy_matrix_path = "dummy_path/existent_empty_matrix.yml"

        def getenv_side_effect(key, default=None):
            if key == "EXCLUDED_USERS_FILE_PATH":
                return dummy_excluded_path
            if key == "PERMISSIONS_MATRIX_FILE_PATH":
                return dummy_matrix_path
            return os.environ.get(key, default)
        mock_getenv.side_effect = getenv_side_effect

        # Mock os.path.exists to return True for these dummy paths
        mock_exists.return_value = True

        # Mock open to return an empty file-like object
        mock_open_file.return_value = mock_open(read_data="")()

        app_config.EXCLUDED_USERS = {"dummy"}
        app_config.PERMISSIONS_MATRIX = {"dummy": "data"}
        reload_config_module()

        self.assertEqual(app_config.EXCLUDED_USERS, set())
        # An empty YAML file typically parses to None. The config loader handles this and sets PERMISSIONS_MATRIX to {}
        self.assertEqual(app_config.PERMISSIONS_MATRIX, {})

        mock_open_file.assert_any_call(dummy_excluded_path, "r")
        mock_open_file.assert_any_call(dummy_matrix_path, "r")

    @patch("dotenv.main.find_dotenv", return_value=None)
    @patch("os.getenv")
    @patch("builtins.open")
    @patch("os.path.exists")
    def test_config_loading_excluded_users_success(self, mock_exists, mock_open_file, mock_getenv, mock_find_dotenv):
        excluded_users_content = "userA\nuserB\n\nuserC  \n"
        dummy_excluded_path = "dummy_path/existent_excluded.txt"
        dummy_matrix_path = "dummy_path/non_existent_matrix.yml" # Matrix file won't exist for this test

        def getenv_side_effect(key, default=None):
            if key == "EXCLUDED_USERS_FILE_PATH":
                return dummy_excluded_path
            if key == "PERMISSIONS_MATRIX_FILE_PATH":
                return dummy_matrix_path
            return os.environ.get(key, default)
        mock_getenv.side_effect = getenv_side_effect

        # Mock os.path.exists: excluded file exists, matrix file does not
        mock_exists.side_effect = lambda path: path == dummy_excluded_path

        # Mock open to provide content only for the excluded users file
        mock_open_file.return_value = mock_open(read_data=excluded_users_content)()

        app_config.EXCLUDED_USERS = set()
        app_config.PERMISSIONS_MATRIX = {"dummy": "data"}

        reload_config_module()

        self.assertEqual(app_config.EXCLUDED_USERS, {"userA", "userB", "userC"})
        self.assertEqual(app_config.PERMISSIONS_MATRIX, {})

        mock_open_file.assert_called_once_with(dummy_excluded_path, "r")

    @patch("dotenv.main.find_dotenv", return_value=None)
    @patch("os.getenv")
    @patch("builtins.open")
    @patch("os.path.exists")
    def test_config_loading_permissions_matrix_success(self, mock_exists, mock_open_file, mock_getenv, mock_find_dotenv):
        permissions_yaml_content = """
permissions:
  PROJET:
    standard:
      mattermost_channel_name_pattern: "projet_{base_name}"
      authentik_group_name_pattern: "projet_{base_name}"
    outline:
      collection_name_pattern: "projet_{base_name}"
      default_access: "read"
      admin_access: "read_write"
"""
        dummy_matrix_path = "dummy_permissions_matrix.yml"
        dummy_excluded_path = "dummy_excluded_users.txt" # Excluded users file won't exist for this test

        def getenv_side_effect(key, default=None):
            if key == "PERMISSIONS_MATRIX_FILE_PATH":
                return dummy_matrix_path
            if key == "EXCLUDED_USERS_FILE_PATH":
                return dummy_excluded_path
            return os.environ.get(key, default)
        mock_getenv.side_effect = getenv_side_effect

        # Mock os.path.exists: matrix file exists, excluded users file does not
        mock_exists.side_effect = lambda path: path == dummy_matrix_path

        # Mock open to provide content only for the permissions matrix file
        mock_open_file.return_value = mock_open(read_data=permissions_yaml_content)()

        app_config.PERMISSIONS_MATRIX = {}
        app_config.EXCLUDED_USERS = {"dummy"}

        reload_config_module()

        mock_open_file.assert_called_once_with(dummy_matrix_path, "r")

        self.assertIn("PROJET", app_config.PERMISSIONS_MATRIX)
        if "PROJET" in app_config.PERMISSIONS_MATRIX:
            self.assertEqual(app_config.PERMISSIONS_MATRIX["PROJET"]["outline"]["default_access"], "read")
        self.assertEqual(app_config.EXCLUDED_USERS, set())

    @patch("libraries.group_sync_services.config")  # To mock config.OUTLINE_URL
    def test_sync_single_group_outline_dm_on_new_add(self, mock_config):
        mock_config.EXCLUDED_USERS = set()  # No exclusions for this test
        mock_config.OUTLINE_URL = "http://fake-outline.com"

        mm_user_for_dm = {"username": "dm_user", "email": "dmuser@example.com", "id": "mm_user_id_dm"}
        auth_group_for_dm = {**self.authentik_group_fixture, "name": "DM Test Group"}
        email_map_for_dm = {"dmuser@example.com": "auth_user_pk_dm"}

        outline_user_data = {"id": "outline_user_id_dm", "email": "dmuser@example.com"}
        outline_collection_data = {"id": "outline_coll_id_dm", "name": "DM Test Group"}

        self.mock_mattermost_client.get_channel_by_name.return_value = self.mm_channel_fixture
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_for_dm]
        self.mock_authentik_client.add_user_to_group.return_value = True  # Authentik part is not focus here

        self.mock_outline_client.get_user_by_email.return_value = outline_user_data
        self.mock_outline_client.get_collection_by_name.return_value = outline_collection_data
        self.mock_outline_client.get_collection_members.return_value = []  # User is NOT already a member
        self.mock_outline_client.add_user_to_collection.return_value = True  # Adding is successful
        self.mock_outline_client.get_collection_details.return_value = outline_collection_data
        self.mock_mattermost_client.send_dm.return_value = True  # DM sending is successful

        # TODO: Refactor test for sync_entity_permissions
        # Old call:
        # results = sync_single_group_to_services(
        #     authentik_client=self.mock_authentik_client,
        #     mattermost_client=self.mock_mattermost_client,
        #     outline_client=self.mock_outline_client,
        #     mm_team_id=self.mm_team_id,
        #     authentik_group=auth_group_for_dm,
        #     email_to_authentik_user_pk_map=email_map_for_dm,
        # )
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
            entity_key="PROJET", # Placeholder, derive from auth_group_for_dm.name?
            base_name="DMTestGroup", # Placeholder, from auth_group_for_dm.name
             # Placeholder, needs proper mocking or derivation
            entity_config=mock_config.PERMISSIONS_MATRIX.get("PROJET", {}), # Using mock_config from test params
            all_authentik_users_by_email=email_map_for_dm,
            dry_run=False
        )

        self.assertEqual(len(results), 2)  # 1 for Authentik, 1 for Outline
        outline_result = next(r for r in results if r["service"] == "OUTLINE")
        # "DM Test Group" will default to "read" permission
        self.assertEqual(outline_result["action"], "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_ACCESS_AND_DM_SENT")
        self.mock_mattermost_client.send_dm.assert_called_once()
        call_args = self.mock_mattermost_client.send_dm.call_args[0]
        self.assertEqual(call_args[0], mm_user_for_dm["id"])  # mm_user_id
        collection_slug = slugify(outline_collection_data["name"])
        collection_id = outline_collection_data["id"]
        expected_url = f"{mock_config.OUTLINE_URL}/collection/{collection_slug}-{collection_id}"  # noqa: E501
        self.assertIn(expected_url, call_args[1])  # message content
        self.assertIn(outline_collection_data["name"], call_args[1])

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_outline_dm_fails(self, mock_config):
        mock_config.EXCLUDED_USERS = set()
        mock_config.OUTLINE_URL = "http://fake-outline.com"
        mm_user_for_dm = {"username": "dm_user_fail", "email": "dmuserfail@example.com", "id": "mm_user_id_dm_fail"}
        # ... similar setup as above ...
        self.mock_mattermost_client.get_channel_by_name.return_value = self.mm_channel_fixture
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_for_dm]
        self.mock_authentik_client.add_user_to_group.return_value = True
        outline_user_data = {"id": "outline_user_id_dm_fail", "email": "dmuserfail@example.com"}
        outline_collection_data = {"id": "outline_coll_id_dm_fail", "name": "DM Fail Group"}
        self.mock_outline_client.get_user_by_email.return_value = outline_user_data
        self.mock_outline_client.get_collection_by_name.return_value = outline_collection_data
        self.mock_outline_client.get_collection_members.return_value = []
        self.mock_outline_client.add_user_to_collection.return_value = True
        self.mock_outline_client.get_collection_details.return_value = outline_collection_data
        self.mock_mattermost_client.send_dm.return_value = False  # DM sending FAILS

        # TODO: Refactor test for sync_entity_permissions
        # Old call:
        # results = sync_single_group_to_services(
        #     authentik_client=self.mock_authentik_client,
        #     mattermost_client=self.mock_mattermost_client,
        #     outline_client=self.mock_outline_client,
        #     mm_team_id=self.mm_team_id,
        #     authentik_group={"name": "DM Fail Group", "pk": "auth_pk_dm_fail"},
        #     email_to_authentik_user_pk_map={"dmuserfail@example.com": "auth_user_pk_dm_fail"},
        # )
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
            entity_key="PROJET", # Placeholder
            base_name="DMFailGroup", # Placeholder
            entity_config=mock_config.PERMISSIONS_MATRIX.get("PROJET", {}), # Using mock_config from test params
            all_authentik_users_by_email={"dmuserfail@example.com": "auth_user_pk_dm_fail"},
            dry_run=False
        )
        outline_result = next(r for r in results if r["service"] == "OUTLINE")
        # "DM Fail Group" will default to "read" permission
        self.assertEqual(outline_result["action"], "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_ACCESS_DM_FAILED")
        self.mock_mattermost_client.send_dm.assert_called_once()

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_outline_user_already_member_no_dm(self, mock_config):
        mock_config.EXCLUDED_USERS = set()
        mm_user_already_member = {
            "username": "already_member",
            "email": "already@example.com",
            "id": "mm_user_id_already",
        }
        outline_user_data = {"id": "outline_user_id_already", "email": "already@example.com"}
        outline_collection_data = {"id": "outline_coll_id_already", "name": "Already Member Group"}

        self.mock_mattermost_client.get_channel_by_name.return_value = self.mm_channel_fixture
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_already_member]
        self.mock_authentik_client.add_user_to_group.return_value = True
        self.mock_outline_client.get_user_by_email.return_value = outline_user_data
        self.mock_outline_client.get_collection_by_name.return_value = outline_collection_data
        self.mock_outline_client.get_collection_members.return_value = [
            outline_user_data["id"]
        ]  # User IS already a member

        # TODO: Refactor test for sync_entity_permissions
        # Old call:
        # results = sync_single_group_to_services(
        #     authentik_client=self.mock_authentik_client,
        #     mattermost_client=self.mock_mattermost_client,
        #     outline_client=self.mock_outline_client,
        #     mm_team_id=self.mm_team_id,
        #     authentik_group={"name": "Already Member Group", "pk": "auth_pk_already"},
        #     email_to_authentik_user_pk_map={"already@example.com": "auth_user_pk_already"},
        # )
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
            entity_key="PROJET", # Placeholder
            base_name="AlreadyMemberGroup", # Placeholder
            entity_config=mock_config.PERMISSIONS_MATRIX.get("PROJET", {}), # Using mock_config from test params
            all_authentik_users_by_email={"already@example.com": "auth_user_pk_already"},
            dry_run=False
        )
        outline_result = next(r for r in results if r["service"] == "OUTLINE")
        self.assertEqual(outline_result["action"], "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED")
        # add_user_to_collection IS called to ensure permission
        self.mock_outline_client.add_user_to_collection.assert_called_once_with(
            outline_collection_data["id"], outline_user_data["id"], permission="read"  # Default permission
        )
        self.mock_mattermost_client.send_dm.assert_not_called()

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_authentik_user_removed_if_not_in_mm(self, mock_config_module):
        mock_config_module.EXCLUDED_USERS = set()  # No exclusions

        # user_to_remove is in Authentik group initially, but not in Mattermost channel
        auth_user_pk_to_remove = "auth_pk_to_remove"
        auth_user_obj_to_remove = {
            "pk": auth_user_pk_to_remove,
            "email": "removeme@example.com",
            "username": "removeme_user",
        }

        # user_to_keep is in Authentik group and in Mattermost channel
        auth_user_pk_to_keep = "auth_pk_to_keep"
        auth_user_obj_to_keep = {"pk": auth_user_pk_to_keep, "email": "keepme@example.com", "username": "keepme_user"}
        mm_user_to_keep = {"username": "keepme_user", "email": "keepme@example.com", "id": "mm_id_keep"}

        authentik_group_with_users = {
            "name": self.auth_group_name,
            "pk": self.auth_group_pk,
            "users": [auth_user_pk_to_remove, auth_user_pk_to_keep],  # PKs list
            "users_obj": [auth_user_obj_to_remove, auth_user_obj_to_keep],  # User objects
        }
        email_to_pk_map = {"removeme@example.com": auth_user_pk_to_remove, "keepme@example.com": auth_user_pk_to_keep}

        self.mock_mattermost_client.get_channel_by_name.return_value = self.mm_channel_fixture
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_to_keep]  # Only keepme_user is in MM

        self.mock_authentik_client.remove_user_from_group.return_value = True
        self.mock_authentik_client.add_user_to_group.return_value = True  # For keepme_user if it were new

        # TODO: Refactor test for sync_entity_permissions or _sync_single_authentik_group
        # Old call:
        # results = sync_single_group_to_services(
        #     authentik_client=self.mock_authentik_client,
        #     mattermost_client=self.mock_mattermost_client,
        #     outline_client=None,  # Outline not tested here
        #     mm_team_id=self.mm_team_id,
        #     authentik_group=authentik_group_with_users,
        #     email_to_authentik_user_pk_map=email_to_pk_map,
        # )
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=None,
            mm_team_id=self.mm_team_id,
            entity_key="PROJET", # Placeholder
            base_name=authentik_group_with_users["name"], # Placeholder
            entity_config=mock_config_module.PERMISSIONS_MATRIX.get("PROJET", {}), # Using mock_config from test params
            all_authentik_users_by_email=email_to_pk_map, # Placeholder
            dry_run=False
        )
        # The following assertions are for the OLD logic. Will need complete rewrite.
        self.mock_authentik_client.remove_user_from_group.assert_called_once_with(
            self.auth_group_pk, auth_user_pk_to_remove
        )
        self.mock_authentik_client.add_user_to_group.assert_not_called()  # keepme_user was already in current_auth_user_pks_in_group

        # Check results for removal
        removal_action_found = any(
            r["service"] == "AUTHENTIK"
            and r["action"] == "USER_REMOVED_FROM_AUTHENTIK_GROUP"
            and r["mm_username"] == "removeme_user"
            for r in results
        )
        self.assertTrue(removal_action_found, "USER_REMOVED_FROM_AUTHENTIK_GROUP action not found for removeme_user")

        # Check results for kept user
        kept_action_found = any(
            r["service"] == "AUTHENTIK"
            and r["action"] == "USER_ALREADY_IN_AUTHENTIK_GROUP"
            and r["mm_username"] == "keepme_user"
            for r in results
        )
        self.assertTrue(kept_action_found, "USER_ALREADY_IN_AUTHENTIK_GROUP action not found for keepme_user")

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_authentik_excluded_user_not_removed_if_not_in_mm(self, mock_config_module):
        # User is in Authentik, NOT in Mattermost, BUT IS EXCLUDED. Should NOT be removed.
        excluded_auth_username = "excluded_from_removal"
        mock_config_module.EXCLUDED_USERS = {excluded_auth_username}

        auth_user_pk_excluded = "auth_pk_excluded_removal"
        auth_user_obj_excluded = {
            "pk": auth_user_pk_excluded,
            "email": "excluded@example.com",
            "username": excluded_auth_username,
        }

        authentik_group_with_excluded_user = {
            "name": self.auth_group_name,
            "pk": self.auth_group_pk,
            "users": [auth_user_pk_excluded],
            "users_obj": [auth_user_obj_excluded],
        }
        email_to_pk_map = {"excluded@example.com": auth_user_pk_excluded}

        self.mock_mattermost_client.get_channel_by_name.return_value = self.mm_channel_fixture
        self.mock_mattermost_client.get_users_in_channel.return_value = []  # No users in MM channel

        # TODO: Refactor test for sync_entity_permissions or _sync_single_authentik_group
        # Old call:
        # results = sync_single_group_to_services(
        #     authentik_client=self.mock_authentik_client,
        #     mattermost_client=self.mock_mattermost_client,
        #     outline_client=None,
        #     mm_team_id=self.mm_team_id,
        #     authentik_group=authentik_group_with_excluded_user,
        #     email_to_authentik_user_pk_map=email_to_pk_map,
        # )
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=None,
            mm_team_id=self.mm_team_id,
            entity_key="PROJET", # Placeholder
            base_name=authentik_group_with_excluded_user["name"], # Placeholder
            entity_config=mock_config_module.PERMISSIONS_MATRIX.get("PROJET", {}), # Using mock_config from test params
            all_authentik_users_by_email=email_to_pk_map, # Placeholder
            dry_run=False
        )
        # The following assertions are for the OLD logic. Will need complete rewrite.
        self.mock_authentik_client.remove_user_from_group.assert_not_called()
        # The user is not in MM, so add_user_to_group should not be called either.
        self.mock_authentik_client.add_user_to_group.assert_not_called()

        # Check that no removal action was logged for this user.
        # An "USER_ALREADY_IN_AUTHENTIK_GROUP" might be logged if the logic considers them processed.
        # Or no specific log if the exclusion means they are skipped before action determination.
        # The current logic for removals iterates Authentik users; if excluded, they are added to target_auth_pks_for_group.
        # Then, if their PK is in target_auth_pks_for_group, they are not removed.
        # No specific "kept due to exclusion" log is generated by the main loop for Authentik.
        # The logging for exclusion happens earlier.
        action_for_excluded_user_found = any(r["mm_username"] == excluded_auth_username for r in results)
        self.assertFalse(
            action_for_excluded_user_found,
            "No action should be logged for excluded user not in MM channel during removal phase.",
        )

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_outline_user_removed_if_not_in_mm(self, mock_config_module):
        mock_config_module.EXCLUDED_USERS = set()
        mock_config_module.OUTLINE_URL = "http://fake-outline.com"  # For DM link construction if user was added

        # user_to_remove_outline is in Outline collection initially, but not in Mattermost channel
        outline_user_id_to_remove = "outline_id_remove"
        # This user won't be in mm_users_in_channel

        # user_to_keep_outline is in Outline collection and in Mattermost channel
        outline_user_id_to_keep = "outline_id_keep"
        mm_user_to_keep_outline = {
            "username": "keepme_outline",
            "email": "keepme.outline@example.com",
            "id": "mm_id_keep_outline",
        }

        # Setup: Authentik part (can be minimal as we focus on Outline)
        # Authentik group has corresponding users by email, but it's the MM channel that dictates Outline membership
        auth_group = {
            "name": self.auth_group_name,
            "pk": self.auth_group_pk,
            "users": [],
            "users_obj": [],
        }  # Minimal Authentik setup

        email_to_pk_map = {  # Mapping for Authentik if needed by MM user loop
            mm_user_to_keep_outline["email"]: "auth_pk_keep_outline"
        }

        self.mock_mattermost_client.get_channel_by_name.return_value = self.mm_channel_fixture
        # Only 'keepme_outline' is in the Mattermost channel
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_to_keep_outline]

        # Outline client mocks
        self.mock_outline_client.get_collection_by_name.return_value = {
            "id": "outline_coll_1",
            "name": self.auth_group_name,
        }
        # Initially, both users are members of the Outline collection
        self.mock_outline_client.get_collection_members.return_value = [
            outline_user_id_to_remove,
            outline_user_id_to_keep,
        ]

        # Mock get_user_by_email for users found in MM channel
        def mock_get_user_by_email_side_effect(email):
            if email == mm_user_to_keep_outline["email"]:
                return {"id": outline_user_id_to_keep, "email": email}
            # For removeme.outline@example.com, this won't be called as they are not in MM channel list
            return None

        self.mock_outline_client.get_user_by_email.side_effect = mock_get_user_by_email_side_effect

        self.mock_outline_client.remove_user_from_collection.return_value = True
        # add_user_to_collection is used for ensuring permission for existing user or adding new
        self.mock_outline_client.add_user_to_collection.return_value = True

        # TODO: Refactor test for sync_entity_permissions or _sync_single_outline_collection
        # Old call:
        # results = sync_single_group_to_services(
        #     authentik_client=self.mock_authentik_client,
        #     mattermost_client=self.mock_mattermost_client,
        #     outline_client=self.mock_outline_client,
        #     mm_team_id=self.mm_team_id,
        #     authentik_group=auth_group,  # Pass the minimal Authentik group
        #     email_to_authentik_user_pk_map=email_to_pk_map,
        # )
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
            entity_key="PROJET", # Placeholder
            base_name=auth_group["name"], # Placeholder
            entity_config=mock_config_module.PERMISSIONS_MATRIX.get("PROJET", {}), # Using mock_config from test params
            all_authentik_users_by_email=email_to_pk_map, # Placeholder
            dry_run=False
        )
        # The following assertions are for the OLD logic. Will need complete rewrite.
        # Assert remove_user_from_collection was called for the user not in MM
        self.mock_outline_client.remove_user_from_collection.assert_called_once_with(
            "outline_coll_1", outline_user_id_to_remove
        )

        # Assert add_user_to_collection was called for the user in MM (to ensure permission)
        self.mock_outline_client.add_user_to_collection.assert_called_once_with(
            "outline_coll_1",
            outline_user_id_to_keep,
            permission="read",  # Default permission from _determine_outline_permission
        )

        # Check results for removal
        removal_action = next((r for r in results if r.get("action") == "USER_REMOVED_FROM_OUTLINE_COLLECTION"), None)
        self.assertIsNotNone(removal_action)
        self.assertEqual(
            removal_action["mm_username"], f"OutlineUser_{outline_user_id_to_remove}"
        )  # Username might be unknown

        # Check results for kept user (permission ensured)
        kept_action = next(
            (r for r in results if r.get("action") == "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED"), None
        )
        self.assertIsNotNone(kept_action)
        self.assertEqual(kept_action["mm_username"], "keepme_outline")

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_outline_excluded_user_not_removed(self, mock_config_module):
        excluded_mm_username = "excluded_outline_user"
        mock_config_module.EXCLUDED_USERS = {excluded_mm_username}
        mock_config_module.OUTLINE_URL = "http://fake-outline.com"

        outline_id_excluded = "outline_id_excl"
        mm_email_excluded = "excluded.outline@example.com"

        # This excluded user IS in the Outline collection initially, but NOT in the Mattermost channel list for this sync.
        # It should remain in the Outline collection.

        self.mock_mattermost_client.get_channel_by_name.return_value = self.mm_channel_fixture
        self.mock_mattermost_client.get_users_in_channel.return_value = []  # No users in MM channel for this test case

        self.mock_outline_client.get_collection_by_name.return_value = {
            "id": "outline_coll_excl",
            "name": self.auth_group_name,
        }
        self.mock_outline_client.get_collection_members.return_value = [
            outline_id_excluded
        ]  # Excluded user is a member

        # Mock get_user_by_email: it won't be called for the excluded user if they are not in MM channel list.
        # However, the removal logic needs to map outline_id_excluded back to a username to check exclusion.
        # This test highlights a potential difficulty if an Outline member isn't in the current MM channel list
        # to provide their username via get_user_by_email.
        # The current logic iterates MM users to build `temp_outline_id_to_mm_username`.
        # If the excluded user is not in MM channel, `temp_outline_id_to_mm_username` won't have them.
        # The `effective_target_outline_ids` also relies on iterating MM users.
        # Let's adjust the test: the excluded user *is* in MM channel, but EXCLUDED.

        mm_user_excluded_in_channel = {
            "username": excluded_mm_username,
            "email": mm_email_excluded,
            "id": "mm_id_excl",
        }
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_excluded_in_channel]

        # Mock get_user_by_email for the excluded user in the MM channel
        self.mock_outline_client.get_user_by_email.return_value = {
            "id": outline_id_excluded,
            "email": mm_email_excluded,
        }

        # Authentik part (minimal)
        auth_group = {"name": self.auth_group_name, "pk": self.auth_group_pk, "users": [], "users_obj": []}
        email_to_pk_map = {mm_email_excluded: "auth_pk_excl"}

        # TODO: Refactor test for sync_entity_permissions or _sync_single_outline_collection
        # Old call:
        # results = sync_single_group_to_services(
        #     authentik_client=self.mock_authentik_client,
        #     mattermost_client=self.mock_mattermost_client,
        #     outline_client=self.mock_outline_client,
        #     mm_team_id=self.mm_team_id,
        #     authentik_group=auth_group,
        #     email_to_authentik_user_pk_map=email_to_pk_map,
        # )
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
            entity_key="PROJET", # Placeholder
            base_name=auth_group["name"], # Placeholder
            entity_config=mock_config_module.PERMISSIONS_MATRIX.get("PROJET", {}), # Using mock_config from test params
            all_authentik_users_by_email=email_to_pk_map, # Placeholder
            dry_run=False
        )
        # The following assertions are for the OLD logic. Will need complete rewrite.
        self.mock_outline_client.remove_user_from_collection.assert_not_called()
        # add_user_to_collection should also not be called for an excluded user for permission update
        self.mock_outline_client.add_user_to_collection.assert_not_called()

        # No action should be logged for this user in results regarding Outline
        outline_actions_for_excluded = [
            r for r in results if r.get("service") == "OUTLINE" and r.get("mm_username") == excluded_mm_username
        ]
        self.assertEqual(
            len(outline_actions_for_excluded),
            0,
            "No Outline action should be logged for an excluded user in MM channel.",
        )

    @patch("libraries.group_sync_services.config")  # To mock config.PERMISSIONS_MATRIX
    def test_sync_single_group_outline_permissions(self, mock_config_module):
        # 1. Setup mock_config_module.PERMISSIONS_MATRIX
        mock_config_module.PERMISSIONS_MATRIX = {
            "PROJET": {"outline": {"access": "read"}, "mattermost": {"channel_type": "O"}},
            "PROJET_ADMIN": {"outline": {"access": "rw"}, "mattermost": {"channel_type": "P"}},
            "ANTENNE": {"outline": {"access": "read"}, "mattermost": {"channel_type": "O"}},
            "ANTENNE_ADMIN": {"outline": {"access": "rw"}, "mattermost": {"channel_type": "P"}},
            "POLES": {"outline": {"access": "read"}, "mattermost": {"channel_type": "O"}},
            "POLES_ADMIN": {"outline": {"access": "rw"}, "mattermost": {"channel_type": "P"}},
            # For testing defaults with problematic matrix entries
            "PROJET_NO_OUTLINE_KEY": {"mattermost": {"channel_type": "O"}},
            "PROJET_NO_ACCESS_KEY": {"outline": {}, "mattermost": {"channel_type": "O"}},
            "PROJET_INVALID_ACCESS_VAL": {"outline": {"access": "super"}, "mattermost": {"channel_type": "O"}},
        }
        mock_config_module.EXCLUDED_USERS = set()  # No exclusions
        mock_config_module.OUTLINE_URL = "http://fake-outline.com"

        # (auth_group_name, mm_channel_type, expected_permission_value, expected_action_string_suffix_part)
        # expected_action_string_suffix_part will be like "READ_ACCESS_AND_DM_SENT"
        test_cases = [
            # Standard cases where DM is expected to be sent
            ("projet_test_public", "O", "read", "READ_ACCESS_AND_DM_SENT"),
            ("projet_test_private", "P", "read_write", "READ_WRITE_ACCESS_AND_DM_SENT"),
            ("antenne_test_public", "O", "read", "READ_ACCESS_AND_DM_SENT"),
            ("antenne_test_private", "P", "read_write", "READ_WRITE_ACCESS_AND_DM_SENT"),
            ("pole_test_public", "O", "read", "READ_ACCESS_AND_DM_SENT"),
            ("pôle_test_public_accent", "O", "read", "READ_ACCESS_AND_DM_SENT"),  # Test with accent
            ("pole_test_private", "P", "read_write", "READ_WRITE_ACCESS_AND_DM_SENT"),
            ("pôle_test_private_accent", "P", "read_write", "READ_WRITE_ACCESS_AND_DM_SENT"),
            ("unknownprefix_test", "O", "read", "READ_ACCESS_AND_DM_SENT"),  # Default for unknown prefix
            (
                "projet_no_outline_setup",
                "O",
                "read",
                "READ_ACCESS_AND_DM_SENT",
            ),  # Default for category with no outline.access
            ("projet_no_access_val", "O", "read", "READ_ACCESS_AND_DM_SENT"),  # Default for invalid outline.access
            (
                "projet_invalid_access_val",
                "O",
                "read",
                "READ_ACCESS_AND_DM_SENT",
            ),  # Default for invalid outline.access
            (
                "nonexistentcatprefix_test",
                "O",
                "read",
                "READ_ACCESS_AND_DM_SENT",
            ),  # Default for category not in matrix
        ]

        mm_user_fixture = {"username": "perm_user", "email": "permuser@example.com", "id": "mm_user_id_perm"}
        outline_user_data = {"id": "outline_user_id_perm"}
        email_to_pk_map = {mm_user_fixture["email"]: "auth_user_pk_perm"}

        original_matrix = mock_config_module.PERMISSIONS_MATRIX.copy()  # Store original mock

        for (
            auth_group_name,
            mm_channel_type,
            expected_permission_value,
            expected_action_string_suffix_part,
        ) in test_cases:
            with self.subTest(auth_group_name=auth_group_name, mm_channel_type=mm_channel_type):
                self.mock_authentik_client.reset_mock()
                self.mock_mattermost_client.reset_mock()
                self.mock_outline_client.reset_mock()

                # Restore and then manipulate matrix for specific test cases if needed
                mock_config_module.PERMISSIONS_MATRIX = original_matrix.copy()
                # This part of the test setup was for manipulating the matrix for specific sub-tests,
                # but the _determine_outline_permission function handles these defaults internally now.
                # So, direct manipulation of mock_config_module.PERMISSIONS_MATRIX for these specific default cases
                # is not strictly needed here if _determine_outline_permission's logging and defaults are trusted.
                # However, keeping the structure if more granular matrix tests are needed later.
                # For now, the test cases rely on _determine_outline_permission correctly interpreting
                # the pre-defined mock_config_module.PERMISSIONS_MATRIX and its defaults.

                current_auth_group = {"name": auth_group_name, "pk": "auth_pk_perm", "users": []}
                current_mm_channel = {
                    "id": "mm_channel_id_perm",
                    "display_name": auth_group_name,  # display_name often matches group name
                    "name": slugify(auth_group_name),  # Actual channel name/slug
                    "type": mm_channel_type,
                }

                self.mock_mattermost_client.get_channel_by_name.return_value = current_mm_channel
                self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_fixture]
                self.mock_authentik_client.add_user_to_group.return_value = True
                self.mock_outline_client.get_user_by_email.return_value = outline_user_data
                self.mock_outline_client.get_collection_by_name.return_value = {
                    "id": "outline_coll_id_perm",
                    "name": auth_group_name,
                }
                self.mock_outline_client.get_collection_members.return_value = []
                self.mock_outline_client.add_user_to_collection.return_value = True
                self.mock_outline_client.get_collection_details.return_value = {
                    "id": "outline_coll_id_perm",
                    "name": auth_group_name,
                }  # For DM

                # TODO: Refactor test for sync_entity_permissions
                # Old call:
                # results = sync_single_group_to_services(
                #     authentik_client=self.mock_authentik_client,
                #     mattermost_client=self.mock_mattermost_client,
                #     outline_client=self.mock_outline_client,
                #     mm_team_id=self.mm_team_id,
                #     authentik_group=current_auth_group,
                #     email_to_authentik_user_pk_map=email_to_pk_map,
                # )
                results = sync_entity_permissions(
                    authentik_client=self.mock_authentik_client,
                    mattermost_client=self.mock_mattermost_client,
                    outline_client=self.mock_outline_client,
                    mm_team_id=self.mm_team_id,
                    entity_key="PROJET", # Placeholder, needs to be derived from auth_group_name / matrix
                    base_name=auth_group_name, # Placeholder
                    entity_config=mock_config_module.PERMISSIONS_MATRIX.get("PROJET", {}), # Placeholder, needs to be specific to entity
                    all_authentik_users_by_email=email_to_pk_map,
                    dry_run=False
                )
                # The following assertions are for the OLD logic. Will need complete rewrite.
                # Ensure add_user_to_collection was called (it should be, as user is not a member)
                self.mock_outline_client.add_user_to_collection.assert_called_once()

                # Get the actual call arguments
                call_args = self.mock_outline_client.add_user_to_collection.call_args
                # Permission is passed as a keyword argument in the actual call
                called_with_permission = call_args.kwargs.get("permission")

                self.assertEqual(called_with_permission, expected_permission_value)

                # Check the action string in results
                outline_result = next((r for r in results if r["service"] == "OUTLINE"), None)
                self.assertIsNotNone(outline_result)
                if outline_result:  # Should always be true given the assertIsNotNone
                    # expected_action_string_suffix_part now includes _AND_DM_SENT
                    # (or other variations if DMs fail/not attempted)
                    expected_action_val = f"USER_ADDED_TO_OUTLINE_COLLECTION_WITH_{expected_action_string_suffix_part}"
                    self.assertEqual(outline_result.get("action"), expected_action_val)


if __name__ == "__main__":
    unittest.main()
