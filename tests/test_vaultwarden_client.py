import json
import os
import unittest
from unittest.mock import MagicMock, call, patch

import requests
from clients.vaultwarden_client import VaultwardenClient


class TestVaultwardenClient(unittest.TestCase):
    def setUp(self):
        self.organization_id = "test-org-id"
        self.server_url = "https://test.vaultwarden.com"

        self.env_patcher_bw_password = patch.dict(os.environ, {"BW_PASSWORD": "testpassword"})
        self.env_patcher_bw_session = patch.dict(os.environ, {"BW_SESSION": ""})

        self.mock_bw_password_env = self.env_patcher_bw_password.start()
        self.mock_bw_session_env = self.env_patcher_bw_session.start()

        self.api_username = "test_api_user@example.com"
        self.api_password = "test_api_password"

        self.client = VaultwardenClient(
            organization_id=self.organization_id,
            server_url=self.server_url,
            api_username=self.api_username,
            api_password=self.api_password,
        )

    def tearDown(self):
        self.env_patcher_bw_password.stop()
        self.env_patcher_bw_session.stop()
        if "BW_SESSION" in os.environ:
            del os.environ["BW_SESSION"]

    def test_initialization_success(self):
        client = VaultwardenClient(
            organization_id=self.organization_id,
            server_url=self.server_url,
            api_username=self.api_username,
            api_password=self.api_password,
        )
        self.assertEqual(client.organization_id, self.organization_id)
        self.assertEqual(client.server_url, self.server_url)
        self.assertEqual(client.bw_session, "")

    def test_initialization_missing_org_id(self):
        with self.assertRaises(ValueError) as context:
            VaultwardenClient(organization_id="", server_url=self.server_url)
        self.assertIn("Vaultwarden organization_id must be provided", str(context.exception))


    @patch("clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_ensure_server_configuration_needs_set(self, mock_run_bw_command):
        mock_run_bw_command.side_effect = [
            (0, "https://otherserver.com", ""),
            (0, "", ""),
        ]
        client = self.client
        self.assertTrue(client._ensure_server_configuration())
        expected_calls = [
            call(["config", "server"], custom_env=unittest.mock.ANY),
            call(["config", "server", self.server_url], custom_env=unittest.mock.ANY),
        ]
        mock_run_bw_command.assert_has_calls(expected_calls)
        self.assertEqual(mock_run_bw_command.call_count, 2)


    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_cli_status_unlocked(self, mock_run_bw):
        mock_run_bw.return_value = (0, json.dumps({"status": "unlocked"}), "")
        status = self.client._get_cli_status()
        self.assertEqual(status, "unlocked")
        mock_run_bw.assert_called_once_with(["status", "--raw"], custom_env=unittest.mock.ANY)

    # ... (other CLI status tests remain the same) ...
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_cli_status_locked(self, mock_run_bw):
        mock_run_bw.return_value = (0, json.dumps({"status": "locked"}), "")
        status = self.client._get_cli_status()
        self.assertEqual(status, "locked")





    @patch.object(VaultwardenClient, "_get_cli_status")
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_session_status_locked_unlock_success(self, mock_run_bw, mock_get_cli_status):
        mock_get_cli_status.return_value = "locked"
        expected_session_key = "new_session_key_from_unlock"
        mock_run_bw.return_value = (0, f"{expected_session_key}\n", "")
        session = self.client._get_session()
        self.assertEqual(session, expected_session_key)


    @patch.object(VaultwardenClient, "_get_cli_status")
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_session_status_unlocked_existing_valid_session(self, mock_run_bw, mock_get_cli_status):
        mock_get_cli_status.return_value = "unlocked"
        self.client.bw_session = "valid_existing_session"
        mock_run_bw.return_value = (0, "", "")
        session = self.client._get_session()
        self.assertEqual(session, "valid_existing_session")


    # ... (other _get_session, _sync_vault, create_collection, get_collection_by_name tests remain largely the same) ...
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_sync_vault_success_with_session(self, mock_run_bw):
        self.client.bw_session = "fake_session_key"
        mock_run_bw.return_value = (0, "Synced!", "")
        self.assertTrue(self.client._sync_vault())



    @patch.object(VaultwardenClient, "_get_session")
    @patch.object(VaultwardenClient, "_sync_vault")
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_create_collection_success(self, mock_run_bw, mock_sync_vault, mock_get_session):
        mock_get_session.return_value = "fake_session_for_create"
        mock_sync_vault.return_value = True
        mock_run_bw.side_effect = [
            (0, "encoded", ""),
            (0, json.dumps({"id": "id"}), ""),
        ]
        self.assertIsNotNone(self.client.create_collection("New Coll"))



    @patch.object(VaultwardenClient, "_get_session", return_value="fake_session")
    @patch.object(VaultwardenClient, "_sync_vault", return_value=True)
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_create_collection_already_exists_finds_it(self, mock_run_bw, mock_sync, mock_get_session):
        mock_run_bw.side_effect = [
            (0, "encoded_payload", ""),
            (1, "", "already exists"),
            (
                0,
                json.dumps(
                    [
                        {
                            "id": "existing-uuid",
                            "name": "Existing",
                            "organizationId": self.organization_id,
                        }
                    ]
                ),
                "",
            ),
        ]
        self.assertEqual(self.client.create_collection("Existing"), "existing-uuid")

    @patch.object(VaultwardenClient, "_get_session", return_value="fake_session")
    @patch.object(VaultwardenClient, "_sync_vault", return_value=True)
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_collection_by_name_found(self, mock_run_bw, mock_sync_vault, mock_get_session):
        mock_run_bw.return_value = (
            0,
            json.dumps(
                [
                    {
                        "name": "Target",
                        "id": "target-uuid",
                        "organizationId": self.organization_id,
                    }
                ]
            ),
            "",
        )
        self.assertEqual(self.client.get_collection_by_name("Target"), "target-uuid")

    @patch.object(VaultwardenClient, "_get_session", return_value="fake_session")
    @patch.object(VaultwardenClient, "_run_bw_command")
    def test_get_collection_by_name_not_found(self, mock_run_bw, mock_get_session):
        with patch.object(self.client, "_sync_vault", return_value=True):
            mock_run_bw.return_value = (0, json.dumps([]), "")
            self.assertIsNone(self.client.get_collection_by_name("NonExistent"))

    # --- Tests for new API methods ---
    @patch("requests.post")
    def test_get_api_token_caching_and_expiry(self, mock_post):
        from datetime import datetime, timedelta

        # First call, should fetch token
        expected_token = "sample_access_token_1"
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": expected_token, "expires_in": 3600}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        token = self.client._get_api_token()
        self.assertEqual(token, expected_token)
        mock_post.assert_called_once()
        self.assertIsNotNone(self.client.api_token)
        self.assertIsNotNone(self.client.api_token_expires_at)

        # Second call, should use cache
        token2 = self.client._get_api_token()
        self.assertEqual(token2, expected_token)
        mock_post.assert_called_once()  # Should not be called again

        # Force expire the token
        self.client.api_token_expires_at = datetime.now() - timedelta(seconds=1)

        # Third call, should fetch a new token
        expected_token_2 = "sample_access_token_2"
        mock_response.json.return_value = {"access_token": expected_token_2, "expires_in": 3600}
        token3 = self.client._get_api_token()
        self.assertEqual(token3, expected_token_2)
        self.assertEqual(mock_post.call_count, 2)

    @patch("requests.post")
    def test_get_api_token_http_error(self, mock_post):
        mock_http_error = requests.exceptions.HTTPError("API error")
        mock_error_response = MagicMock()
        mock_error_response.text = "Detailed API error"
        mock_http_error.response = mock_error_response
        mock_response_obj = MagicMock()
        mock_response_obj.raise_for_status.side_effect = mock_http_error
        mock_post.return_value = mock_response_obj
        self.assertIsNone(self.client._get_api_token())




    @patch("clients.vaultwarden_client.VaultwardenClient._request_with_token_refresh")
    def test_invite_user_to_collection_success(self, mock_request):
        mock_request.return_value = MagicMock(status_code=200)
        self.assertTrue(self.client.invite_user_to_collection("u@e.com", "cid", self.organization_id))

    @patch("clients.vaultwarden_client.VaultwardenClient._request_with_token_refresh")
    def test_invite_user_to_collection_http_error(self, mock_request):
        mock_http_error = requests.exceptions.HTTPError("Invite error")
        mock_error_response = MagicMock()
        mock_error_response.text = "Detailed invite error"
        mock_error_response.status_code = 400
        mock_http_error.response = mock_error_response
        mock_request.side_effect = mock_http_error
        self.assertFalse(self.client.invite_user_to_collection("u@e.com", "cid", self.organization_id))


    @patch("clients.vaultwarden_client.VaultwardenClient._request_with_token_refresh")
    def test_invite_user_to_collection_already_member_is_success(self, mock_request):
        user_email = "already_member@example.com"
        collection_id = "coll_already_in"

        mock_http_error_model = requests.exceptions.HTTPError("Simulated 400 Error")
        mock_error_response_model = MagicMock()
        mock_error_response_model.status_code = 400
        mock_error_response_model.json.return_value = {
            "errorModel": {"message": f"{user_email} is already a member of this collection."}
        }
        mock_http_error_model.response = mock_error_response_model
        mock_request.side_effect = mock_http_error_model

        with self.assertLogs(level="WARNING") as log:
            success = self.client.invite_user_to_collection(user_email, collection_id, self.organization_id)
            self.assertTrue(success, "Should return True if user already a member (errorModel case)")
            self.assertTrue(any("already a member" in record.getMessage() for record in log.records))

    @patch("requests.request")
    @patch("clients.vaultwarden_client.VaultwardenClient._get_api_token")
    def test_request_with_token_refresh_handles_401(self, mock_get_token, mock_request):
        # First call fails with 401, second call succeeds
        mock_get_token.side_effect = ["token1", "token2"]
        mock_response_401 = MagicMock()
        mock_response_401.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=MagicMock(status_code=401)
        )
        mock_response_200 = MagicMock(status_code=200)
        mock_request.side_effect = [mock_response_401, mock_response_200]

        response = self.client._request_with_token_refresh("get", "http://test.com/api")
        self.assertEqual(response, mock_response_200)
        self.assertEqual(mock_get_token.call_count, 2)
        self.assertEqual(mock_request.call_count, 2)
        self.assertIsNone(self.client.api_token)  # Token should be invalidated
        self.assertIsNone(self.client.api_token_expires_at)



    @patch("clients.vaultwarden_client.VaultwardenClient._request_with_token_refresh")
    def test_list_users_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"id": "1", "name": "test"}]}
        mock_request.return_value = mock_response
        result = self.client.list_users()
        self.assertEqual(result, [{"id": "1", "name": "test"}])


    @patch("clients.vaultwarden_client.VaultwardenClient._request_with_token_refresh")
    def test_delete_user_success(self, mock_request):
        mock_request.return_value = MagicMock(status_code=200)
        result = self.client.delete_user("1")
        self.assertTrue(result)


    @patch("clients.vaultwarden_client.VaultwardenClient._request_with_token_refresh")
    def test_delete_user_http_error(self, mock_request):
        mock_request.side_effect = requests.exceptions.RequestException("API error")
        result = self.client.delete_user("1")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
