import unittest
from unittest.mock import patch, MagicMock, call
import os
import json
import requests

from marty_bot.clients.vaultwarden_client import VaultwardenClient


class TestVaultwardenClient(unittest.TestCase):

    def setUp(self):
        self.organization_id = "test-org-id"
        self.server_url = "https://test.vaultwarden.com"

        self.env_patcher_bw_password = patch.dict(os.environ, {"BW_PASSWORD": "testpassword"})
        # BW_SESSION is patched to be "" so os.getenv("BW_SESSION") returns ""
        self.env_patcher_bw_session = patch.dict(os.environ, {"BW_SESSION": ""})

        self.mock_bw_password_env = self.env_patcher_bw_password.start()
        self.mock_bw_session_env = self.env_patcher_bw_session.start()

        # If a test needs BW_SESSION to be initially unset (so os.getenv returns None),
        # it should use another patch.dict within the test method.
        # For default setUp, os.getenv("BW_SESSION") will be "".

        self.ensure_server_config_patcher = patch(
            "marty_bot.clients.vaultwarden_client.VaultwardenClient._ensure_server_configuration",
            MagicMock(return_value=True),
        )
        self.mock_ensure_server_config = self.ensure_server_config_patcher.start()

        self.client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)

    def tearDown(self):
        self.ensure_server_config_patcher.stop()
        self.env_patcher_bw_password.stop()
        self.env_patcher_bw_session.stop()
        # Clean up BW_SESSION from os.environ if it was set by tests directly or by client logic
        if "BW_SESSION" in os.environ:
            del os.environ["BW_SESSION"]

    def test_initialization_success(self):
        self.mock_ensure_server_config.assert_called_once()
        self.assertEqual(self.client.organization_id, self.organization_id)
        self.assertEqual(self.client.server_url, self.server_url)
        # Because setUp patches os.environ to have BW_SESSION="", client.bw_session will be "".
        self.assertEqual(self.client.bw_session, "")

    def test_initialization_missing_org_id(self):
        self.ensure_server_config_patcher.stop()  # Stop patch to test constructor path
        with self.assertRaises(ValueError) as context:
            VaultwardenClient(organization_id="", server_url=self.server_url)
        self.assertIn("Vaultwarden organization_id must be provided", str(context.exception))
        self.ensure_server_config_patcher.start()  # Restart patch

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_ensure_server_configuration_already_set(self, mock_run_bw_for_client_methods):
        self.ensure_server_config_patcher.stop()

        mock_run_bw_for_client_methods.return_value = (0, self.server_url, "")

        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        self.assertIsNotNone(client)

        mock_run_bw_for_client_methods.assert_called_once_with(["config", "server"], custom_env=unittest.mock.ANY)

        mock_run_bw_for_client_methods.reset_mock()
        mock_run_bw_for_client_methods.return_value = (0, self.server_url, "")
        self.assertTrue(client._ensure_server_configuration())
        mock_run_bw_for_client_methods.assert_called_once_with(["config", "server"], custom_env=unittest.mock.ANY)

        self.ensure_server_config_patcher.start()

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_ensure_server_configuration_needs_set(self, mock_run_bw_for_client_methods):
        self.ensure_server_config_patcher.stop()
        mock_run_bw_for_client_methods.side_effect = [(0, "https://otherserver.com", ""), (0, "", "")]
        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        self.assertIsNotNone(client)

        expected_calls = [
            call(["config", "server"], custom_env=unittest.mock.ANY),
            call(["config", "server", self.server_url], custom_env=unittest.mock.ANY),
        ]
        mock_run_bw_for_client_methods.assert_has_calls(expected_calls)
        self.assertEqual(mock_run_bw_for_client_methods.call_count, 2)

        self.ensure_server_config_patcher.start()

    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_cli_status_unlocked(self, mock_run_bw):
        # self.client is from setUp, its _ensure_server_configuration is already mocked by self.ensure_server_config_patcher
        mock_run_bw.return_value = (0, json.dumps({"status": "unlocked"}), "")
        status = self.client._get_cli_status()
        self.assertEqual(status, "unlocked")
        mock_run_bw.assert_called_once_with(["status", "--raw"], custom_env=unittest.mock.ANY)

    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_cli_status_locked(self, mock_run_bw):
        mock_run_bw.return_value = (0, json.dumps({"status": "locked"}), "")
        status = self.client._get_cli_status()
        self.assertEqual(status, "locked")

    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_cli_status_unauthenticated(self, mock_run_bw):
        mock_run_bw.return_value = (0, json.dumps({"status": "unauthenticated"}), "")
        status = self.client._get_cli_status()
        self.assertEqual(status, "unauthenticated")

    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_cli_status_error_rc(self, mock_run_bw):
        mock_run_bw.return_value = (1, "", "Some CLI error")
        status = self.client._get_cli_status()
        self.assertEqual(status, "error")

    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_cli_status_error_json(self, mock_run_bw):
        mock_run_bw.return_value = (0, "Invalid JSON", "")
        status = self.client._get_cli_status()
        self.assertEqual(status, "error")

    @patch.object(VaultwardenClient, "_get_cli_status")
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_session_status_unauthenticated(self, mock_run_bw, mock_get_cli_status):
        mock_get_cli_status.return_value = "unauthenticated"
        session = self.client._get_session()
        self.assertIsNone(session)
        mock_run_bw.assert_not_called()

    @patch.object(VaultwardenClient, "_get_cli_status")
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_session_status_locked_unlock_success(self, mock_run_bw, mock_get_cli_status):
        mock_get_cli_status.return_value = "locked"
        expected_session_key = "new_session_key_from_unlock"
        mock_run_bw.return_value = (0, f"{expected_session_key}\n", "")

        session = self.client._get_session()
        self.assertEqual(session, expected_session_key)
        self.assertEqual(self.client.bw_session, expected_session_key)
        self.assertEqual(os.environ.get("BW_SESSION"), expected_session_key)

        args, kwargs = mock_run_bw.call_args
        self.assertEqual(args[0], ["unlock", "--passwordenv", "BW_PASSWORD", "--raw"])
        self.assertIn("custom_env", kwargs)
        actual_custom_env = kwargs["custom_env"]
        self.assertEqual(actual_custom_env.get("BW_PASSWORD"), "testpassword")
        self.assertIn("PATH", actual_custom_env)

    @patch.object(VaultwardenClient, "_get_cli_status")
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_session_status_locked_unlock_fail_no_password(self, mock_run_bw, mock_get_cli_status):
        mock_get_cli_status.return_value = "locked"
        with patch.dict(os.environ, {"BW_PASSWORD": ""}):
            session = self.client._get_session()
            self.assertIsNone(session)
            mock_run_bw.assert_not_called()

    @patch.object(VaultwardenClient, "_get_cli_status")
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_session_status_unlocked_existing_valid_session(self, mock_run_bw, mock_get_cli_status):
        mock_get_cli_status.return_value = "unlocked"
        self.client.bw_session = "valid_existing_session"
        mock_run_bw.return_value = (0, "", "")

        session = self.client._get_session()
        self.assertEqual(session, "valid_existing_session")
        mock_run_bw.assert_called_once_with(["unlock", "--check"])

    @patch.object(VaultwardenClient, "_get_cli_status")
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_session_status_unlocked_existing_invalid_session_then_unlock(self, mock_run_bw, mock_get_cli_status):
        mock_get_cli_status.return_value = "unlocked"
        self.client.bw_session = "invalid_session"

        expected_new_key = "freshly_unlocked_key"
        mock_run_bw.side_effect = [(1, "", "session invalid error"), (0, f"{expected_new_key}\n", "")]

        session = self.client._get_session()
        self.assertEqual(session, expected_new_key)
        self.assertEqual(self.client.bw_session, expected_new_key)

        calls = mock_run_bw.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], (["unlock", "--check"],))
        self.assertEqual(calls[1][0], (["unlock", "--passwordenv", "BW_PASSWORD", "--raw"],))
        self.assertEqual(calls[1][1]["custom_env"].get("BW_PASSWORD"), "testpassword")

    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_sync_vault_success_with_session(self, mock_run_bw):
        self.client.bw_session = "fake_session_key"
        mock_run_bw.return_value = (0, "Synced!", "")
        self.assertTrue(self.client._sync_vault())
        mock_run_bw.assert_called_once_with(["sync"])

    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_sync_vault_fail_no_session(self, mock_run_bw):
        self.client.bw_session = None
        self.assertFalse(self.client._sync_vault())
        mock_run_bw.assert_not_called()

    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_sync_vault_fail_cli_error_clears_session(self, mock_run_bw):
        self.client.bw_session = "fake_session_key"
        os.environ["BW_SESSION"] = "fake_session_key"
        mock_run_bw.return_value = (1, "", "invalid session token")

        self.assertFalse(self.client._sync_vault())
        self.assertIsNone(self.client.bw_session)
        self.assertNotIn("BW_SESSION", os.environ)

    @patch.object(VaultwardenClient, "_get_session")
    @patch.object(VaultwardenClient, "_sync_vault")
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_create_collection_success(self, mock_run_bw, mock_sync_vault, mock_get_session):
        mock_get_session.return_value = "fake_session_for_create"
        self.client.bw_session = "fake_session_for_create"
        mock_sync_vault.return_value = True
        collection_name = "My New Collection"
        expected_collection_id = "new-coll-uuid"

        mock_run_bw.side_effect = [
            (0, "encoded_payload_data", ""),
            (0, json.dumps({"id": expected_collection_id, "name": collection_name}), ""),
        ]

        created_id = self.client.create_collection(collection_name)
        self.assertEqual(created_id, expected_collection_id)
        mock_get_session.assert_called_once()
        mock_sync_vault.assert_called_once()

        calls = mock_run_bw.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], (["encode"],))
        expected_input_for_encode = {
            "organizationId": self.organization_id,
            "name": collection_name,
            "externalId": None,
            "groups": [],
        }
        self.assertEqual(json.loads(calls[0][1]["input_data"]), expected_input_for_encode)

        self.assertEqual(calls[1][0], (["create", "org-collection", "--organizationid", self.organization_id],))
        self.assertEqual(calls[1][1]["input_data"], "encoded_payload_data")

    @patch.object(VaultwardenClient, "_get_session", return_value=None)
    def test_create_collection_fail_no_session(self, mock_get_session):
        self.assertIsNone(self.client.create_collection("No Session Collection"))
        mock_get_session.assert_called_once()

    @patch.object(VaultwardenClient, "_get_session", return_value="fake_session")
    @patch.object(VaultwardenClient, "_sync_vault", return_value=False)
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_create_collection_sync_fail_still_attempts(self, mock_run_bw, mock_sync_vault, mock_get_session):
        self.client.bw_session = "fake_session"
        mock_run_bw.side_effect = [(0, "encoded", ""), (0, json.dumps({"id": "id", "name": "name"}), "")]
        coll_id = self.client.create_collection("Sync Fail Collection")
        self.assertIsNotNone(coll_id)
        mock_get_session.assert_called_once()
        mock_sync_vault.assert_called_once()

    @patch.object(VaultwardenClient, "_get_session", return_value="fake_session")
    @patch.object(VaultwardenClient, "_sync_vault", return_value=True)
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_create_collection_already_exists_finds_it(self, mock_run_bw, mock_sync, mock_get_session):
        self.client.bw_session = "fake_session"
        collection_name = "Existing Collection"
        existing_id = "existing-uuid"

        mock_run_bw.side_effect = [
            (0, "encoded_payload", ""),  # encode
            (1, "", "ERROR: Collection with this name already exists."),  # create org-collection
            # list collections (this is the one that needs organizationId)
            (0, json.dumps([{"id": existing_id, "name": collection_name, "organizationId": self.organization_id}]), ""),
        ]

        found_id = self.client.create_collection(collection_name)
        self.assertEqual(found_id, existing_id)
        self.assertEqual(mock_run_bw.call_count, 3)
        self.assertEqual(
            mock_run_bw.call_args_list[2][0], (["list", "org-collections", "--organizationid", self.organization_id],)
        )

    @patch.object(VaultwardenClient, "_get_session", return_value="fake_session")
    @patch.object(VaultwardenClient, "_sync_vault", return_value=True) # Added missing mock for _sync_vault
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_collection_by_name_found(self, mock_run_bw, mock_sync_vault, mock_get_session): # Added mock_sync_vault
        self.client.bw_session = "fake_session"
        collection_name = "Target Collection"
        expected_id = "target-uuid"
        mock_run_bw.return_value = (
            0,
            # Ensure mocked data includes organizationId for filtering
            json.dumps([
                {"name": "Other", "id": "other-id", "organizationId": self.organization_id},
                {"name": collection_name, "id": expected_id, "organizationId": self.organization_id}
            ]),
            "",
        )
        found_id = self.client.get_collection_by_name(collection_name)
        self.assertEqual(found_id, expected_id)
        # Verify it's called with 'list collections' and that sync and session were checked
        mock_run_bw.assert_called_once_with(["list", "collections"])
        mock_sync_vault.assert_called_once()
        mock_get_session.assert_called_once()

    @patch.object(VaultwardenClient, "_get_session", return_value="fake_session")
    @patch.object(VaultwardenClient, "_sync_vault", return_value=True) # Mock sync as it's called by get_collection_by_name
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_collection_by_name_not_found(self, mock_run_bw, mock_sync_vault, mock_get_session):
        self.client.bw_session = "fake_session"
        # Simulate output from `bw list collections`
        mock_run_bw.return_value = (
            0,
            json.dumps([
                {"name": "Other Collection", "id": "other-id-123", "organizationId": self.organization_id},
                {"name": "Another unrelated", "id": "other-id-456", "organizationId": "another-org-id"}
            ]),
            ""
        )
        # Ensure it's using the correct command now `list collections`
        self.assertIsNone(self.client.get_collection_by_name("NonExistentCollection"))
        mock_run_bw.assert_called_once_with(["list", "collections"])
        mock_get_session.assert_called_once()
        mock_sync_vault.assert_called_once()

    @patch.object(VaultwardenClient, "_get_session", return_value="fake_session")
    @patch.object(VaultwardenClient, "_sync_vault", return_value=True)
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_collection_id_by_name_via_cli_found_filters_by_org(self, mock_run_bw, mock_sync_vault, mock_get_session):
        self.client.bw_session = "fake_session"
        collection_name = "Target Collection"
        expected_id = "target-uuid-for-org"

        mock_run_bw.return_value = (
            0,
            json.dumps([
                {"name": "Other", "id": "other-id", "organizationId": self.organization_id},
                {"name": collection_name, "id": "some-other-org-id", "organizationId": "some-other-org"}, # Same name, diff org
                {"name": collection_name, "id": expected_id, "organizationId": self.organization_id}, # Correct one
                {"name": "Yet Another", "id": "yet-another-id", "organizationId": self.organization_id}
            ]),
            "",
        )
        # Using the alias directly as per plan
        found_id = self.client.get_collection_id_by_name_via_api_or_cli(collection_name)
        self.assertEqual(found_id, expected_id)
        mock_run_bw.assert_called_once_with(["list", "collections"]) # Verifies it uses the correct bw command
        mock_get_session.assert_called_once()
        mock_sync_vault.assert_called_once()

    def test_run_bw_command_file_not_found_during_init(self):
        self.ensure_server_config_patcher.stop() # Stop the auto-mock for _ensure_server_configuration
        with patch("subprocess.run", side_effect=FileNotFoundError("bw not found simulation")):
            # Temporarily patch os.getenv for VAULTWARDEN_SERVER_URL if VaultwardenClient relies on it for _ensure_server_configuration
            with patch.dict(os.environ, {"VAULTWARDEN_SERVER_URL": self.server_url}):
                 with self.assertRaises(FileNotFoundError):
                    # Creating a new client instance here to test its __init__ path
                    VaultwardenClient(organization_id="org", server_url=self.server_url)
        self.ensure_server_config_patcher.start() # Restart the auto-mock

    # --- Tests for new API methods ---

    @patch('marty_bot.clients.vaultwarden_client.requests.post')
    def test_get_api_access_token_success(self, mock_post):
        expected_token = "this_is_a_fake_access_token"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": expected_token, "token_type": "Bearer"}
        mock_post.return_value = mock_response

        # Ensure API credentials are set for the client instance for this test
        self.client.api_username = "test_api_user@example.com"
        self.client.api_password = "test_api_password"

        token = self.client.get_api_access_token()
        self.assertEqual(token, expected_token)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertTrue(args[0].endswith("/identity/connect/token"))
        self.assertEqual(kwargs["data"]["grant_type"], "password")
        self.assertEqual(kwargs["data"]["username"], "test_api_user%40example.com") # Check URL encoding
        self.assertEqual(kwargs["data"]["password"], "test_api_password")

    @patch('marty_bot.clients.vaultwarden_client.requests.post')
    def test_get_api_access_token_http_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.reason = "Unauthorized"
        mock_response.text = '{"error": "invalid_credentials"}'
        mock_post.side_effect = requests.exceptions.HTTPError(response=mock_response)

        self.client.api_username = "test_api_user@example.com"
        self.client.api_password = "wrong_password"

        token = self.client.get_api_access_token()
        self.assertIsNone(token)

    @patch('marty_bot.clients.vaultwarden_client.requests.post')
    def test_get_api_access_token_request_exception(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("Failed to connect")
        self.client.api_username = "user"
        self.client.api_password = "pass"
        token = self.client.get_api_access_token()
        self.assertIsNone(token)

    def test_get_api_access_token_missing_credentials(self):
        # Test with client not having api_username or api_password
        self.client.api_username = None
        self.assertIsNone(self.client.get_api_access_token())
        self.client.api_username = "user"
        self.client.api_password = None
        self.assertIsNone(self.client.get_api_access_token())

    def test_get_api_access_token_missing_server_url(self):
        client_no_url = VaultwardenClient(organization_id=self.organization_id, server_url=None)
        client_no_url.api_username = "user"
        client_no_url.api_password = "pass"
        # Need to ensure CONFIG_SERVER_URL is also None for this specific test case if client relies on it
        with patch('marty_bot.clients.vaultwarden_client.CONFIG_SERVER_URL', None):
            self.assertIsNone(client_no_url.get_api_access_token())


    @patch('marty_bot.clients.vaultwarden_client.requests.post')
    def test_invite_user_to_collection_api_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200 # Or 201, 204 depending on API
        mock_response.json.return_value = {"object": "org-member", "id": "new-member-id"} # Example response
        mock_post.return_value = mock_response

        access_token = "fake_api_token"
        user_email = "new.user@example.com"
        collection_id = "coll-uuid-123"

        result = self.client.invite_user_to_collection_api(access_token, user_email, collection_id)
        self.assertTrue(result)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertTrue(args[0].endswith(f"/api/organizations/{self.organization_id}/users/invite"))
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {access_token}")
        self.assertEqual(kwargs["json"]["emails"], [user_email])
        self.assertEqual(kwargs["json"]["collections"][0]["id"], collection_id)
        self.assertTrue(kwargs["json"]["collections"][0]["readOnly"]) # Default

    @patch('marty_bot.clients.vaultwarden_client.requests.post')
    def test_invite_user_to_collection_api_failure_http_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"error": "User already invited or collection not found"}'
        mock_post.return_value = mock_response # Direct return, not raising HTTPError for this test path

        result = self.client.invite_user_to_collection_api("token", "email", "coll_id")
        self.assertFalse(result)

    @patch('marty_bot.clients.vaultwarden_client.requests.post')
    def test_invite_user_to_collection_api_request_exception(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("Request timed out")
        result = self.client.invite_user_to_collection_api("token", "email", "coll_id")
        self.assertFalse(result)

    def test_invite_user_to_collection_api_missing_params(self):
        self.assertFalse(self.client.invite_user_to_collection_api("", "email", "coll_id"))
        self.assertFalse(self.client.invite_user_to_collection_api("token", "", "coll_id"))
        self.assertFalse(self.client.invite_user_to_collection_api("token", "email", ""))


if __name__ == "__main__":
    unittest.main()
