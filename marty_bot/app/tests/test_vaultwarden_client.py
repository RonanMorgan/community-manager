import unittest
from unittest.mock import patch, MagicMock, mock_open, call
import subprocess
import json
import os

# Adjust path to import client from the project root directory
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from clients.vaultwarden_client import VaultwardenClient
import logging

# Suppress logging for tests unless specifically testing log output
logging.disable(logging.CRITICAL)


class TestVaultwardenClient(unittest.TestCase):

    def setUp(self):
        self.organization_id = "test-org-id"
        self.server_url = "https://test.vaultwarden.com"
        self.mock_env_vars = {
            "BW_SESSION": "",
            "BW_PASSWORD": "",
            "BW_SERVER_URL": self.server_url, # Ensure default is overridden for some tests
            "BW_ORGANIZATION_ID": self.organization_id # Though client takes it as arg
        }
        self.env_patcher = patch.dict(os.environ, self.mock_env_vars)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_init_success(self):
        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        self.assertEqual(client.organization_id, self.organization_id)
        self.assertEqual(client.server_url, self.server_url)

    def test_init_no_organization_id(self):
        with self.assertRaises(ValueError):
            VaultwardenClient(organization_id="", server_url=self.server_url)

    @patch("subprocess.run")
    def test_configure_server_already_correct(self, mock_subprocess_run):
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["bw", "status"], returncode=0, stdout=json.dumps({"serverUrl": self.server_url, "status": "unlocked"}), stderr=""
        )
        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        mock_subprocess_run.assert_called_once_with(
            ["bw", "status"], input=None, capture_output=True, text=True, check=False, env=unittest.mock.ANY
        )
        # No further calls to logout or config server should be made
        self.assertEqual(mock_subprocess_run.call_count, 1)


    @patch("subprocess.run")
    def test_configure_server_needs_update(self, mock_subprocess_run):
        # Order of returns: 1. status (wrong server), 2. logout, 3. config server
        mock_subprocess_run.side_effect = [
            subprocess.CompletedProcess(args=["bw", "status"], returncode=0, stdout=json.dumps({"serverUrl": "https://old.server.com", "status": "unlocked"}), stderr=""),
            subprocess.CompletedProcess(args=["bw", "logout"], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=["bw", "config", "server", self.server_url], returncode=0, stdout="", stderr=""),
        ]
        VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)

        expected_calls = [
            call(["bw", "status"], input=None, capture_output=True, text=True, check=False, env=unittest.mock.ANY),
            call(["bw", "logout"], input=None, capture_output=False, text=True, check=False, env=unittest.mock.ANY),
            call(["bw", "config", "server", self.server_url], input=None, capture_output=True, text=True, check=False, env=unittest.mock.ANY),
        ]
        mock_subprocess_run.assert_has_calls(expected_calls)
        self.assertEqual(mock_subprocess_run.call_count, 3)

    @patch("subprocess.run")
    def test_get_session_valid_existing_session(self, mock_subprocess_run):
        # Order of returns: 1. status (for _configure_server), 2. unlock --check (success), 3. sync (success)
        mock_subprocess_run.side_effect = [
            subprocess.CompletedProcess(args=["bw", "status"], returncode=0, stdout=json.dumps({"serverUrl": self.server_url, "status": "unlocked"}), stderr=""),
            subprocess.CompletedProcess(args=["bw", "unlock", "--check", "--session", "EXISTING_SESSION_TOKEN"], returncode=0, stdout="Success", stderr=""),
            subprocess.CompletedProcess(args=["bw", "sync", "--session", "EXISTING_SESSION_TOKEN"], returncode=0, stdout="Synced", stderr=""),
        ]
        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url, session_token="EXISTING_SESSION_TOKEN")
        session = client._get_session()
        self.assertEqual(session, "EXISTING_SESSION_TOKEN")
        self.assertEqual(mock_subprocess_run.call_count, 3)


    @patch("tempfile.NamedTemporaryFile")
    @patch("subprocess.run")
    def test_get_session_unlock_with_password(self, mock_subprocess_run, mock_temp_file):
        # Mock the temporary file context manager
        mock_file_obj = MagicMock()
        mock_file_obj.name = "temp_password_file_path"
        mock_temp_file.return_value.__enter__.return_value = mock_file_obj

        os.environ["BW_PASSWORD"] = "testpassword" # Set password for this test

        # Order of returns for subprocess.run calls:
        # 1. _configure_server -> _run_bw_command(["status"])
        # 2. _get_session (direct call) -> subprocess.run(["bw", "unlock", "--raw"])
        # 3. _get_session -> _run_bw_command(["sync"])
        mock_subprocess_run.side_effect = [
            subprocess.CompletedProcess(args=["bw", "status"], returncode=0, stdout=json.dumps({"serverUrl": self.server_url, "status": "locked"}), stderr=""),
            subprocess.CompletedProcess(args=["bw", "unlock", "--raw"], returncode=0, stdout="NEWSESSIONTOKEN", stderr=""), # No newline
            subprocess.CompletedProcess(args=["bw", "sync", "--session", "NEWSESSIONTOKEN"], returncode=0, stdout="Synced", stderr=""),
        ]

        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url, session_token=None)
        session = client._get_session()

        self.assertEqual(session, "NEWSESSIONTOKEN") # Corrected expected token
        mock_temp_file.assert_called_once_with(mode="w", delete=True)
        mock_file_obj.write.assert_called_once_with("testpassword")
        mock_file_obj.flush.assert_called_once()

        # Check subprocess calls: status, unlock --check (implicitly as session is None), unlock --raw, sync
        self.assertGreaterEqual(mock_subprocess_run.call_count, 3) # status, unlock, sync
        # More specific check for unlock --raw call
        unlock_raw_call_found = False
        for c in mock_subprocess_run.call_args_list:
            if c.args[0] == ["bw", "unlock", "--raw"]:
                unlock_raw_call_found = True
                self.assertEqual(c.kwargs['env']['BW_PASSWORD_FILE'], "temp_password_file_path")
        self.assertTrue(unlock_raw_call_found)

        del os.environ["BW_PASSWORD"] # Clean up env var

    @patch("subprocess.run")
    def test_get_session_locked_no_password_raises_error(self, mock_subprocess_run):
        # Order: 1. status (for _configure_server), 2. status (for _get_session, shows locked)
        mock_subprocess_run.side_effect = [
             subprocess.CompletedProcess(args=["bw", "status"], returncode=0, stdout=json.dumps({"serverUrl": self.server_url, "status": "locked"}), stderr=""),
             subprocess.CompletedProcess(args=["bw", "status"], returncode=0, stdout=json.dumps({"serverUrl": self.server_url, "status": "locked"}), stderr=""),
        ]
        if "BW_PASSWORD" in os.environ: del os.environ["BW_PASSWORD"] # Ensure no password

        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        with self.assertRaisesRegex(RuntimeError, "Vaultwarden is locked and automatic unlock failed"):
            client._get_session()

    @patch.object(VaultwardenClient, "_get_session", return_value="VALID_SESSION")
    @patch("subprocess.run")
    def test_create_collection_success(self, mock_subprocess_run, mock_get_session):
        mock_configure_server_status_call = subprocess.CompletedProcess(
            args=["bw", "status"], returncode=0, stdout=json.dumps({"serverUrl": self.server_url, "status": "unlocked"}), stderr=""
        )
        mock_encode_call = subprocess.CompletedProcess(args=["bw", "encode"], returncode=0, stdout="ENCODED_DATA", stderr="")
        created_coll_id = "coll-id-123"
        mock_create_call = subprocess.CompletedProcess(
            args=["bw", "create", "org-collection"], returncode=0,
            stdout=json.dumps({"id": created_coll_id, "name": "Test Collection", "organizationId": self.organization_id}),
            stderr=""
        )
        mock_subprocess_run.side_effect = [mock_configure_server_status_call, mock_encode_call, mock_create_call]

        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        collection_name = "Test Collection"
        result = client.create_collection(collection_name)

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], created_coll_id)
        self.assertEqual(result["name"], collection_name)
        mock_get_session.assert_called_once()

        expected_collection_data = {
            "organizationId": self.organization_id,
            "name": collection_name,
            "externalId": None,
            "groups": [],
            "users": []
        }
        # Check encode call
        encode_call_args = mock_subprocess_run.call_args_list[1] # 0 is status, 1 is encode
        self.assertEqual(encode_call_args.args[0][:2], ["bw", "encode"])
        self.assertEqual(json.loads(encode_call_args.kwargs['input']), expected_collection_data)

        # Check create call
        create_call_args = mock_subprocess_run.call_args_list[2] # 2 is create
        self.assertEqual(create_call_args.args[0][:3], ["bw", "create", "org-collection"])
        self.assertEqual(create_call_args.kwargs['input'], b"ENCODED_DATA") # Should be bytes
        self.assertIn("--organizationid", create_call_args.args[0])
        self.assertIn(self.organization_id, create_call_args.args[0])


    @patch.object(VaultwardenClient, "_get_session", return_value=None)
    def test_create_collection_no_session(self, mock_get_session):
        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        result = client.create_collection("Test Collection")
        self.assertIsNone(result)
        mock_get_session.assert_called_once()

    @patch.object(VaultwardenClient, "_get_session", return_value="VALID_SESSION")
    @patch("subprocess.run")
    def test_create_collection_encode_fails(self, mock_subprocess_run, mock_get_session):
        # side_effect for subprocess.run: 0: _configure_server status, 1: encode (fails)
        mock_subprocess_run.side_effect = [
            subprocess.CompletedProcess(args=["bw", "status"], returncode=0, stdout=json.dumps({"serverUrl": self.server_url, "status": "unlocked"}), stderr=""),
            subprocess.CompletedProcess(args=["bw", "encode"], returncode=1, stdout="", stderr="Encode error"),
        ]
        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        result = client.create_collection("Test Collection")
        self.assertIsNone(result)

    @patch.object(VaultwardenClient, "_get_session", return_value="VALID_SESSION")
    @patch("subprocess.run")
    def test_create_collection_cli_create_fails(self, mock_subprocess_run, mock_get_session):
        # side_effect for subprocess.run: 0: _configure_server status, 1: encode (ok), 2: create (fails)
        mock_subprocess_run.side_effect = [
            subprocess.CompletedProcess(args=["bw", "status"], returncode=0, stdout=json.dumps({"serverUrl": self.server_url, "status": "unlocked"}), stderr=""),
            subprocess.CompletedProcess(args=["bw", "encode"], returncode=0, stdout="ENCODED_DATA", stderr=""),
            subprocess.CompletedProcess(args=["bw", "create", "org-collection"], returncode=1, stdout="", stderr="Create error"),
        ]
        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        result = client.create_collection("Test Collection")
        self.assertIsNone(result)

    @patch.object(VaultwardenClient, "_get_session", return_value="VALID_SESSION")
    @patch("subprocess.run")
    def test_create_collection_non_json_output(self, mock_subprocess_run, mock_get_session):
        raw_output_str = "Collection created successfully but this is not JSON."
        # side_effect for subprocess.run: 0: _configure_server status, 1: encode (ok), 2: create (ok, but non-JSON stdout)
        mock_subprocess_run.side_effect = [
            subprocess.CompletedProcess(args=["bw", "status"], returncode=0, stdout=json.dumps({"serverUrl": self.server_url, "status": "unlocked"}), stderr=""),
            subprocess.CompletedProcess(args=["bw", "encode"], returncode=0, stdout="ENCODED_DATA", stderr=""),
            subprocess.CompletedProcess(args=["bw", "create", "org-collection"], returncode=0, stdout=raw_output_str, stderr=""),
        ]
        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        result = client.create_collection("Test Collection")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("raw_output"), raw_output_str)
        self.assertIn("Collection likely created", result.get("message"))


if __name__ == "__main__":
    # Re-enable logging for direct script execution if needed for debugging
    # logging.disable(logging.NOTSET)
    # logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s")
    unittest.main()
