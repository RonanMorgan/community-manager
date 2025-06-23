import unittest
from unittest.mock import patch, MagicMock, mock_open

from libraries.group_sync_services import sync_single_group_to_services, orchestrate_group_synchronization
# Assuming your config is accessible and can be patched, or you can patch its usage directly
# For example, if group_sync_services imports 'from app import config'
# you can patch 'libraries.group_sync_services.config'
from app import config as app_config # Import the actual config to potentially reload/reset it
import dotenv # Required for wraps=dotenv.main.load_dotenv

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
            "users": [], # Initially empty
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
            "name": "test-group-channel" # slug
        }
        self.mm_users_fixture = [
            {"username": "user1", "email": "user1@example.com", "id": "mm_user_id_1"},
            {"username": "user2", "email": "user2@example.com", "id": "mm_user_id_2"},
            {"username": "excluded_user", "email": "excludeduser@example.com", "id": "mm_user_id_excluded"},
            {"username": "marty", "email": "marty@example.com", "id": "mm_user_id_marty"},
        ]

    @patch('libraries.group_sync_services.config')
    def test_sync_single_group_user_exclusion(self, mock_config):
        # Setup: Define an excluded user in the mocked config
        mock_config.EXCLUDED_USERS = {"excluded_user", "marty"}

        # Mock client responses
        self.mock_mattermost_client.get_channel_by_name.return_value = self.mm_channel_fixture
        self.mock_mattermost_client.get_users_in_channel.return_value = self.mm_users_fixture
        self.mock_authentik_client.add_user_to_group.return_value = True # Assume success for non-excluded

        # Mock Outline client methods to avoid None errors if called
        self.mock_outline_client.get_user_by_email.return_value = {"id": "outline_user_id_1"}
        self.mock_outline_client.get_collection_by_name.return_value = {"id": "outline_collection_id_1"}
        self.mock_outline_client.add_user_to_collection.return_value = True


        results = sync_single_group_to_services(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client, # Pass mock Outline client
            mm_team_id=self.mm_team_id,
            authentik_group=self.authentik_group_fixture,
            email_to_authentik_user_pk_map=self.email_to_authentik_user_pk_map_fixture,
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


    @patch('libraries.group_sync_services.config')
    @patch('libraries.group_sync_services.get_all_authentik_groups_and_user_map')
    @patch('libraries.group_sync_services.sync_single_group_to_services') # Mock the single group sync
    def test_orchestrate_group_synchronization_respects_exclusion_via_single_sync(
        self, mock_sync_single, mock_get_groups, mock_config
    ):
        # This test ensures that orchestrate_group_synchronization calls sync_single_group_to_services,
        # which is where the exclusion is handled. We don't need to re-test the exclusion logic itself here,
        # just that the flow is correct and config is theoretically passed down (by being in the same module).

        # Setup excluded users in the *actual* config module that sync_single_group_to_services will read
        # This is because we are mocking sync_single_group_to_services itself, so its internal
        # reference to 'config.EXCLUDED_USERS' needs to be set.
        original_excluded_users = app_config.EXCLUDED_USERS
        app_config.EXCLUDED_USERS = {"marty"}


        mock_get_groups.return_value = ([self.authentik_group_fixture], self.email_to_authentik_user_pk_map_fixture)

        # Define a side effect for sync_single_group_to_services to simulate its behavior
        # including returning results that would indicate an exclusion happened.
        def sync_single_side_effect(*args, **kwargs):
            # Simulate that 'marty' would be completely skipped by sync_single_group_to_services
            # and thus generate no result entry.
            mm_users_for_this_group = self.mm_users_fixture # Contains marty, user1, user2, excluded_user
            results_for_group = []
            for user in mm_users_for_this_group:
                if user["username"] in app_config.EXCLUDED_USERS: # In this test, EXCLUDED_USERS is {"marty"}
                    continue # Silently skip, add no result
                else:
                    # Simulate successful sync for non-excluded users for both services
                    results_for_group.append({
                        "mm_username": user["username"], "action": "USER_ADDED_TO_AUTHENTIK_GROUP", "service": "AUTHENTIK", "status": "SUCCESS"
                    })
                    results_for_group.append({
                        "mm_username": user["username"], "action": "USER_MEMBERSHIP_ENSURED_IN_OUTLINE_COLLECTION", "service": "OUTLINE", "status": "SUCCESS"
                    })
            return results_for_group

        mock_sync_single.side_effect = sync_single_side_effect

        success, detailed_results = orchestrate_group_synchronization(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
        )

        self.assertTrue(success)
        mock_sync_single.assert_called_once() # Ensure it was called for the one group

        # Check that no results for "marty" are present in the detailed_results
        found_marty_in_results = any(
            r.get("mm_username") == "marty" for r in detailed_results
        )
        self.assertFalse(found_marty_in_results, "Marty should not have any entry in the detailed_results.")

        # Verify that other users (user1, user2, excluded_user - who is not excluded in *this specific test's* config) are present
        # self.mm_users_fixture has 4 users. 'marty' is excluded by app_config.EXCLUDED_USERS = {"marty"}
        # So, 3 users (user1, user2, excluded_user) should be processed by the mock_sync_single.
        # Each processed user generates 2 results (Authentik + Outline). So 3 * 2 = 6 results expected.
        self.assertEqual(len(detailed_results), 6)

        # Restore original config
        app_config.EXCLUDED_USERS = original_excluded_users

    @patch('app.config.EXCLUDED_USERS_FILE_PATH', "dummy_path/non_existent_file.txt")
    @patch('os.path.exists', return_value=False)
    @patch('dotenv.main.find_dotenv', return_value=None) # Prevent find_dotenv erroring during reload
    def test_config_loading_file_not_found(self, mock_find_dotenv, mock_exists):
        # Test that if the file doesn't exist, EXCLUDED_USERS is empty
        # Need to reload config for it to re-evaluate the file path logic
        reload_config_module()
        self.assertEqual(app_config.EXCLUDED_USERS, set())

    @patch('app.config.EXCLUDED_USERS_FILE_PATH', "dummy_path/existent_empty_file.txt")
    @patch('os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data="")
    @patch('dotenv.main.find_dotenv', return_value=None) # Prevent find_dotenv erroring
    def test_config_loading_empty_file(self, mock_find_dotenv, mock_file_open, mock_exists):
        # Test that if the file is empty, EXCLUDED_USERS is empty
        reload_config_module()
        self.assertEqual(app_config.EXCLUDED_USERS, set())

    @patch('app.config.EXCLUDED_USERS_FILE_PATH', "dummy_path/existent_file.txt")
    @patch('os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data="userA\nuserB\n\nuserC  \n")
    @patch('dotenv.main.find_dotenv', return_value=None) # Prevent find_dotenv erroring
    def test_config_loading_success(self, mock_find_dotenv, mock_file_open, mock_exists):
        # Test successful loading and parsing of the file
        reload_config_module()
        self.assertEqual(app_config.EXCLUDED_USERS, {"userA", "userB", "userC"})


if __name__ == "__main__":
    unittest.main()
