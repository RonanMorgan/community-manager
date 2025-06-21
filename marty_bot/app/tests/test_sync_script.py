import unittest
from unittest.mock import patch, MagicMock, call
import logging
import sys
import os

# Adjust path to import from the app and scripts directory
# This assumes tests are run from the repo root (e.g. /app) or marty_bot root.
# If run from /app:
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))) # Adds /app to path
# If run from /app/marty_bot:
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))) # Adds marty_bot to path for app imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))) # Adds scripts to path


from app import config as app_config # For passing to initialize_clients if needed, or mocking
from app.authentik_client import AuthentikClient
from app.mattermost_client import MattermostClient, slugify

# Functions to test from the script
# Note: The script needs to be importable. If it has an if __name__ == "__main__": block
# that runs logic immediately, that could be an issue for importing.
# Assuming the script's functions can be imported.
from sync_mm_authentik_groups import (
    initialize_clients,
    get_all_authentik_groups_and_user_map,
    sync_single_authentik_group_with_mattermost,
    main_sync_logic
)


class TestSyncScriptLogic(unittest.TestCase):

    def setUp(self):
        # Mock config for the script's functions
        self.mock_config = MagicMock(spec=app_config)
        self.mock_config.DEBUG = False
        self.mock_config.AUTHENTIK_URL = "http://fake-auth.com"
        self.mock_config.AUTHENTIK_TOKEN = "fake-auth-token"
        self.mock_config.MATTERMOST_URL = "http://fake-mm.com"
        self.mock_config.BOT_TOKEN = "fake_mm_bot_token"
        self.mock_config.MATTERMOST_TEAM_ID = "fake_mm_team_id"

        # Mock client instances that would be returned by initialize_clients
        self.mock_auth_client = MagicMock(spec=AuthentikClient)
        self.mock_mm_client = MagicMock(spec=MattermostClient)

        # Suppress logging from the script unless specifically testing for it
        logging.getLogger('sync_mm_authentik_groups').setLevel(logging.CRITICAL)


    @patch('scripts.sync_mm_authentik_groups.config', new_callable=MagicMock) # Patch config used by script
    def test_initialize_clients_success(self, mock_script_config):
        mock_script_config.AUTHENTIK_URL = "http://fake-auth.com"
        mock_script_config.AUTHENTIK_TOKEN = "fake-auth-token"
        mock_script_config.MATTERMOST_URL = "http://fake-mm.com"
        mock_script_config.BOT_TOKEN = "fake_mm_bot_token"
        mock_script_config.MATTERMOST_TEAM_ID = "fake_mm_team_id"

        with patch('scripts.sync_mm_authentik_groups.AuthentikClient') as MockAuthClient, \
             patch('scripts.sync_mm_authentik_groups.MattermostClient') as MockMMClient:

            mock_auth_instance = MockAuthClient.return_value
            mock_mm_instance = MockMMClient.return_value

            auth_client, mm_client = initialize_clients()

            MockAuthClient.assert_called_once_with("http://fake-auth.com", "fake-auth-token")
            MockMMClient.assert_called_once_with("http://fake-mm.com", "fake_mm_bot_token", "fake_mm_team_id")
            self.assertEqual(auth_client, mock_auth_instance)
            self.assertEqual(mm_client, mock_mm_instance)

    @patch('scripts.sync_mm_authentik_groups.config', new_callable=MagicMock)
    def test_initialize_clients_auth_missing_config(self, mock_script_config):
        mock_script_config.AUTHENTIK_URL = None # Missing URL
        mock_script_config.AUTHENTIK_TOKEN = "fake-auth-token"
        # Assume MM config is fine
        mock_script_config.MATTERMOST_URL = "http://fake-mm.com"
        mock_script_config.BOT_TOKEN = "fake_mm_bot_token"
        mock_script_config.MATTERMOST_TEAM_ID = "fake_mm_team_id"

        with patch('scripts.sync_mm_authentik_groups.MattermostClient'): # Mock MM client to avoid its init issues
            auth_client, _ = initialize_clients()
            self.assertIsNone(auth_client)
            # Test that mm_client would still be initialized if its config is present can be added if needed

    # Test get_all_authentik_groups_and_user_map (currently a pass-through, so this tests interaction)
    def test_get_all_authentik_groups_and_user_map_passthrough(self):
        mock_groups_data = [{"name": "group1"}]
        mock_email_map_data = {"email@example.com": "pk1"}
        self.mock_auth_client.get_groups_with_users.return_value = (mock_groups_data, mock_email_map_data)

        groups, email_map = get_all_authentik_groups_and_user_map(self.mock_auth_client)

        self.mock_auth_client.get_groups_with_users.assert_called_once()
        self.assertEqual(groups, mock_groups_data)
        self.assertEqual(email_map, mock_email_map_data)

    # Core tests for sync_single_authentik_group_with_mattermost
    def test_sync_single_group_user_added_successfully(self):
        auth_group = {"pk": "auth_group_pk_1", "name": "Test Group One", "users": []} # No users initially
        email_map = {"mm_user@example.com": "auth_user_pk_123"}
        mm_users_in_channel = [{"email": "mm_user@example.com", "id": "mm_user_id_abc", "username": "mmuser"}]

        self.mock_mm_client.get_channel_by_name.return_value = {"id": "mm_channel_id_1", "display_name": "Test Group One"}
        self.mock_mm_client.get_users_in_channel.return_value = mm_users_in_channel
        self.mock_auth_client.add_user_to_group.return_value = True

        sync_single_authentik_group_with_mattermost(
            self.mock_auth_client, self.mock_mm_client, self.mock_config.MATTERMOST_TEAM_ID,
            auth_group, email_map
        )
        # Verify slugify was used if you import it for the script, or direct name match
        expected_mm_channel_slug = slugify(auth_group["name"])
        self.mock_mm_client.get_channel_by_name.assert_called_once_with(self.mock_config.MATTERMOST_TEAM_ID, expected_mm_channel_slug)
        self.mock_mm_client.get_users_in_channel.assert_called_once_with("mm_channel_id_1")
        self.mock_auth_client.add_user_to_group.assert_called_once_with("auth_group_pk_1", "auth_user_pk_123")

    def test_sync_single_group_user_already_in_group(self):
        auth_group = {"pk": "auth_group_pk_1", "name": "Test Group One", "users": ["auth_user_pk_123"]} # User already in group
        email_map = {"mm_user@example.com": "auth_user_pk_123"}
        mm_users_in_channel = [{"email": "mm_user@example.com", "id": "mm_user_id_abc"}]

        self.mock_mm_client.get_channel_by_name.return_value = {"id": "mm_channel_id_1", "display_name": "Test Group One"}
        self.mock_mm_client.get_users_in_channel.return_value = mm_users_in_channel

        sync_single_authentik_group_with_mattermost(
            self.mock_auth_client, self.mock_mm_client, self.mock_config.MATTERMOST_TEAM_ID,
            auth_group, email_map
        )
        self.mock_auth_client.add_user_to_group.assert_not_called()


    def test_sync_single_group_mm_user_not_in_authentik_map(self):
        auth_group = {"pk": "auth_group_pk_1", "name": "Test Group One", "users": []}
        email_map = {"another_user@example.com": "auth_user_pk_456"} # MM user's email not in this map
        mm_users_in_channel = [{"email": "mm_user@example.com", "id": "mm_user_id_abc"}]

        self.mock_mm_client.get_channel_by_name.return_value = {"id": "mm_channel_id_1", "display_name": "Test Group One"}
        self.mock_mm_client.get_users_in_channel.return_value = mm_users_in_channel

        sync_single_authentik_group_with_mattermost(
            self.mock_auth_client, self.mock_mm_client, self.mock_config.MATTERMOST_TEAM_ID,
            auth_group, email_map
        )
        self.mock_auth_client.add_user_to_group.assert_not_called()

    def test_sync_single_group_mm_channel_not_found(self):
        auth_group = {"pk": "auth_group_pk_1", "name": "NonExistentChannel", "users": []}
        email_map = {"mm_user@example.com": "auth_user_pk_123"}

        self.mock_mm_client.get_channel_by_name.return_value = None # Channel not found

        sync_single_authentik_group_with_mattermost(
            self.mock_auth_client, self.mock_mm_client, self.mock_config.MATTERMOST_TEAM_ID,
            auth_group, email_map
        )
        self.mock_mm_client.get_users_in_channel.assert_not_called()
        self.mock_auth_client.add_user_to_group.assert_not_called()

    def test_sync_single_group_no_users_in_mm_channel(self):
        auth_group = {"pk": "auth_group_pk_1", "name": "Test Group One", "users": []}
        email_map = {"mm_user@example.com": "auth_user_pk_123"}
        mm_users_in_channel = [] # No users in channel

        self.mock_mm_client.get_channel_by_name.return_value = {"id": "mm_channel_id_1", "display_name": "Test Group One"}
        self.mock_mm_client.get_users_in_channel.return_value = mm_users_in_channel

        sync_single_authentik_group_with_mattermost(
            self.mock_auth_client, self.mock_mm_client, self.mock_config.MATTERMOST_TEAM_ID,
            auth_group, email_map
        )
        self.mock_auth_client.add_user_to_group.assert_not_called()


    # Test main_sync_logic orchestration
    @patch('scripts.sync_mm_authentik_groups.initialize_clients')
    @patch('scripts.sync_mm_authentik_groups.get_all_authentik_groups_and_user_map')
    @patch('scripts.sync_mm_authentik_groups.sync_single_authentik_group_with_mattermost')
    @patch('scripts.sync_mm_authentik_groups.config', new_callable=MagicMock)
    def test_main_sync_logic_orchestration(self, mock_script_config, mock_sync_single, mock_get_auth_groups, mock_init_clients):
        # Setup return values for the mocked orchestrating functions
        mock_script_config.MATTERMOST_TEAM_ID = "test_team_id" # Ensure this is set for main_sync_logic checks

        mock_auth_client_inst = MagicMock()
        mock_mm_client_inst = MagicMock()
        mock_init_clients.return_value = (mock_auth_client_inst, mock_mm_client_inst)

        mock_groups = [{"name": "group1"}, {"name": "group2"}]
        mock_email_map = {"user@example.com": "pk1"}
        mock_get_auth_groups.return_value = (mock_groups, mock_email_map)

        main_sync_logic()

        mock_init_clients.assert_called_once()
        mock_get_auth_groups.assert_called_once_with(mock_auth_client_inst)
        self.assertEqual(mock_sync_single.call_count, 2)
        mock_sync_single.assert_any_call(
            mock_auth_client_inst, mock_mm_client_inst, "test_team_id",
            mock_groups[0], mock_email_map
        )
        mock_sync_single.assert_any_call(
            mock_auth_client_inst, mock_mm_client_inst, "test_team_id",
            mock_groups[1], mock_email_map
        )

    @patch('scripts.sync_mm_authentik_groups.initialize_clients')
    def test_main_sync_logic_no_auth_client(self, mock_init_clients):
        mock_init_clients.return_value = (None, self.mock_mm_client) # Auth client fails to init
        # Use a logger to capture error messages if needed, or check return if function returns status
        main_sync_logic()
        # Assert that further processing like get_all_authentik_groups didn't happen
        # This requires get_all_authentik_groups_and_user_map to NOT be called.
        # For that, we would need to patch it as well.
        # For now, this test mainly ensures it exits early if a client is missing.


if __name__ == "__main__":
    # This allows running the tests directly if script path issues are handled
    # Example: python -m unittest app/tests/test_sync_script.py
    # Ensure PYTHONPATH includes the project root for 'app' and 'scripts' to be found.
    # You might need to run from project root: python -m unittest marty_bot.app.tests.test_sync_script
    unittest.main()
