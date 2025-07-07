import unittest
from unittest.mock import patch, MagicMock, call
import os
import json

# import subprocess # F401 - subprocess is used by the client, not directly by tests after refactor

# Assuming vaultwarden_client.py is in marty_bot/clients/
from marty_bot.clients.vaultwarden_client import VaultwardenClient


class TestVaultwardenClient(unittest.TestCase):

    def setUp(self):
        self.organization_id = "test-org-id"
        self.server_url = "https://test.vaultwarden.com"
        # Patch os.getenv for BW_PASSWORD and BW_SESSION for controlled testing
        self.env_patcher_bw_password = patch.dict(os.environ, {"BW_PASSWORD": "testpassword"})
        self.env_patcher_bw_session = patch.dict(os.environ, {"BW_SESSION": ""})  # Start with no session

        self.mock_bw_password = self.env_patcher_bw_password.start()
        self.mock_bw_session_env = self.env_patcher_bw_session.start()

        # Ensure BW_SESSION is cleared from os.environ if it was set by a previous test
        if "BW_SESSION" in os.environ:
            del os.environ["BW_SESSION"]

        # Patch _ensure_server_configuration to do nothing for most tests
        # Individual tests can unpatch or provide a specific mock if they want to test this method
        self.ensure_server_config_patcher = patch(
            "marty_bot.clients.vaultwarden_client.VaultwardenClient._ensure_server_configuration",
            MagicMock(return_value=True),
        )
        self.mock_ensure_server_config = self.ensure_server_config_patcher.start()

    def tearDown(self):
        self.ensure_server_config_patcher.stop()
        self.env_patcher_bw_password.stop()
        self.env_patcher_bw_session.stop()
        # Clean up BW_SESSION from actual os.environ if set by tests
        if "BW_SESSION" in os.environ:
            del os.environ["BW_SESSION"]

    def test_initialization(self):
        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        self.assertEqual(client.organization_id, self.organization_id)
        self.assertEqual(client.server_url, self.server_url)
        self.assertIsNone(client.bw_session)  # Initially None, fetched on demand

    def test_initialization_missing_org_id(self):
        # _ensure_server_configuration is mocked in setUp, so __init__ will not call real subprocess
        with self.assertRaises(ValueError) as context:
            VaultwardenClient(organization_id="", server_url=self.server_url)
        self.assertIn("Vaultwarden organization_id must be provided", str(context.exception))

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_ensure_server_configuration_already_set(self, mock_subprocess_run_specific):
        # Stop the global patch from setUp for this specific test
        self.ensure_server_config_patcher.stop()
        try:
            # Mock 'bw config server' to show current server is already correct
            mock_subprocess_run_specific.return_value = MagicMock(returncode=0, stdout=self.server_url, stderr="")
            # Client instantiation will now call the real _ensure_server_configuration
            VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)  # noqa: F841

            mock_subprocess_run_specific.assert_called_once_with(
                ["bw", "config", "server"],
                capture_output=True,
                text=True,
                check=False,
                input=None,
                env=unittest.mock.ANY,
            )
        finally:
            # Restart the global patch for other tests
            self.ensure_server_config_patcher.start()

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_ensure_server_configuration_needs_set(self, mock_subprocess_run_specific):
        self.ensure_server_config_patcher.stop()
        try:
            # First call for 'bw config server' (check current)
            mock_check = MagicMock(returncode=0, stdout="https://otherserver.com", stderr="")
            # Second call for 'bw config server <url>' (set new)
            mock_set = MagicMock(returncode=0, stdout="", stderr="")
            mock_subprocess_run_specific.side_effect = [mock_check, mock_set]

            VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)  # noqa: F841

            expected_calls = [
                call(
                    ["bw", "config", "server"],
                    capture_output=True,
                    text=True,
                    check=False,
                    input=None,
                    env=unittest.mock.ANY,
                ),
                call(
                    ["bw", "config", "server", self.server_url],
                    capture_output=True,
                    text=True,
                    check=False,
                    input=None,
                    env=unittest.mock.ANY,
                ),
            ]
            mock_subprocess_run_specific.assert_has_calls(expected_calls)
        finally:
            self.ensure_server_config_patcher.start()

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_get_session_unlock_successful(self, mock_run_bw_command_method):
        client = VaultwardenClient(organization_id=self.organization_id)
        client.bw_session = None

        # Définir les retours pour les appels successifs à _run_bw_command
        # Appel 1: unlock --check (échoue)
        # Appel 2: unlock --passwordenv (réussit)
        mock_run_bw_command_method.side_effect = [
            (1, "stdout_check", "stderr_check_not_unlocked"),  # (returncode, stdout, stderr) for unlock --check
            (0, "session_key_from_unlock\n", "stderr_unlock_empty"),  # for unlock --passwordenv
        ]

        # BW_PASSWORD est "testpassword" due to setUp patch.dict
        session = client._get_session()

        self.assertEqual(session, "session_key_from_unlock")  # stdout a été strippé par le client
        self.assertEqual(client.bw_session, "session_key_from_unlock")
        self.assertEqual(os.environ.get("BW_SESSION"), "session_key_from_unlock")

        # Vérifier les appels à la méthode mockée _run_bw_command
        calls = mock_run_bw_command_method.call_args_list
        self.assertEqual(len(calls), 2)

        # Appel 1: unlock --check
        self.assertEqual(calls[0][0][0], ["unlock", "--check"])  # Args de _run_bw_command

        # Appel 2: unlock --passwordenv
        self.assertEqual(calls[1][0][0], ["unlock", "--passwordenv", "BW_PASSWORD", "--raw"])
        # Vérifier custom_env passé au second appel de _run_bw_command
        custom_env_arg = calls[1][1]["custom_env"]
        self.assertEqual(custom_env_arg.get("BW_PASSWORD"), "testpassword")
        self.assertNotIn("BW_SESSION", custom_env_arg)

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_get_session_unlock_fails_no_password_env(self, mock_subprocess_run):
        with patch.dict(os.environ, {"BW_PASSWORD": ""}):  # Simulate BW_PASSWORD not set
            client = VaultwardenClient(organization_id=self.organization_id)
            client.bw_session = None  # Start with no session in client

            # Mock for 'bw unlock --check' (fails, because self.bw_session is None, so it's called)
            mock_subprocess_run.return_value = MagicMock(returncode=1, stdout="", stderr="not unlocked")

            session = client._get_session()
            self.assertIsNone(session)  # Should fail as BW_PASSWORD is not set for unlock attempt

            # If self.bw_session is None and BW_PASSWORD is "", _get_session returns None without calling subprocess.run
            # because it checks self.bw_session (None), then checks BW_PASSWORD (""), then returns None.
            # NO, this is wrong. If self.bw_session is None, it WILL call "unlock --check".
            # If that unlock --check fails (as per mock_subprocess_run.return_value),
            # it THEN checks BW_PASSWORD. Since BW_PASSWORD is "", it returns None.
            # So unlock --check IS called.
            # NO, if bw_session is None and BW_PASSWORD is "", no subprocess call is made by _get_session.
            mock_subprocess_run.assert_not_called()

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_get_session_already_valid(self, mock_subprocess_run):
        client = VaultwardenClient(organization_id=self.organization_id)
        client.bw_session = "existing_valid_session"  # Pre-set a session on the client
        # Note: os.environ["BW_SESSION"] is not directly set here,
        # client._run_bw_command will use client.bw_session to populate the env for subprocess.

        # Mock for 'bw unlock --check' (succeeds)
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        session = client._get_session()  # This will call "unlock --check"
        self.assertEqual(session, "existing_valid_session")

        # Check that the env passed to subprocess.run contained the session from client.bw_session
        passed_env_for_check = mock_subprocess_run.call_args_list[0][1]["env"]
        self.assertEqual(passed_env_for_check.get("BW_SESSION"), "existing_valid_session")

        mock_subprocess_run.assert_called_once_with(
            ["bw", "unlock", "--check"],
            capture_output=True,
            text=True,
            check=False,
            input=None,
            env=unittest.mock.ANY,
        )  # noqa: E501

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_sync_vault_successful(self, mock_subprocess_run):
        client = VaultwardenClient(organization_id=self.organization_id)
        client.bw_session = "test_session_key"  # Assume valid session

        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="Synced!", stderr="")

        self.assertTrue(client._sync_vault())
        mock_subprocess_run.assert_called_once_with(
            ["bw", "sync"], capture_output=True, text=True, check=False, input=None, env=unittest.mock.ANY
        )
        # Check that the env passed to subprocess.run contained the session
        passed_env_for_sync = mock_subprocess_run.call_args_list[0][1]["env"]
        self.assertEqual(passed_env_for_sync.get("BW_SESSION"), "test_session_key")

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_sync_vault_fails_due_to_session(self, mock_subprocess_run):
        client = VaultwardenClient(organization_id=self.organization_id)
        initial_session = "old_test_session_key"
        client.bw_session = initial_session
        os.environ["BW_SESSION"] = initial_session  # Simulate it was set in outer env

        mock_subprocess_run.return_value = MagicMock(returncode=1, stdout="", stderr="invalid session token")

        self.assertFalse(client._sync_vault())
        self.assertIsNone(client.bw_session)  # Session should be cleared from client
        self.assertNotIn("BW_SESSION", os.environ)  # Session should be cleared from os.environ by client logic

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_create_collection_successful(self, mock_run_bw_command_method):
        collection_name = "New Test Collection"
        collection_id = "new-coll-id"
        session_key_for_test = "session_for_create_test"

        # Simuler les retours de _run_bw_command pour chaque étape de create_collection
        # 1. _get_session -> unlock --check
        # 2. _get_session -> unlock --passwordenv
        # 3. _sync_vault -> sync
        # 4. create_collection -> encode
        # 5. create_collection -> create org-collection
        mock_run_bw_command_method.side_effect = [
            (1, "stdout_unlock_check", "stderr_unlock_check"),  # unlock --check fails
            (0, f"{session_key_for_test}\n", "stderr_unlock_pass"),  # unlock --passwordenv succeeds
            (0, "stdout_sync", "stderr_sync"),  # sync succeeds
            (0, "encoded_payload_string", "stderr_encode"),  # encode succeeds
            (0, json.dumps({"id": collection_id, "name": collection_name}), "stderr_create"),  # create succeeds
        ]

        client = VaultwardenClient(organization_id=self.organization_id)
        created_id = client.create_collection(collection_name)

        self.assertEqual(created_id, collection_id)

        calls = mock_run_bw_command_method.call_args_list
        self.assertEqual(len(calls), 5)

        # Vérification des commandes passées à _run_bw_command (sans le "bw" initial)
        self.assertEqual(calls[0][0][0], ["unlock", "--check"])
        self.assertEqual(calls[1][0][0], ["unlock", "--passwordenv", "BW_PASSWORD", "--raw"])
        self.assertEqual(calls[2][0][0], ["sync"])
        self.assertEqual(calls[3][0][0], ["encode"])
        self.assertEqual(calls[4][0][0], ["create", "org-collection", "--organizationid", self.organization_id])

        # Vérification de l'input pour encode
        self.assertIn(f'"name": "{collection_name}"', calls[3][1]["input_data"])
        # Vérification de l'input pour create
        self.assertEqual(calls[4][1]["input_data"], "encoded_payload_string")

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_create_collection_already_exists(self, mock_subprocess_run):
        collection_name = "Existing Collection"
        existing_collection_id = "existing-coll-id"

        # Mocks: 1. unlock check, 2. unlock, 3. sync, 4. encode, 5. create (fails, says exists), 6. list, (7. unlock check for list - if session cleared), (8. unlock for list)
        mock_unlock_check1 = MagicMock(returncode=0)  # Session is initially valid
        mock_sync = MagicMock(returncode=0, stdout="Synced", stderr="")
        mock_encode = MagicMock(returncode=0, stdout="encoded_payload_string", stderr="")
        mock_create_fails = MagicMock(
            returncode=1, stdout="", stderr="ERROR: Collection with this name already exists."
        )

        # For get_collection_by_name (called when create fails with "already exists")
        mock_list_collections = MagicMock(
            returncode=0,
            stdout=json.dumps(
                [
                    {"id": "other-id", "name": "Other Collection"},
                    {"id": existing_collection_id, "name": collection_name},
                ]
            ),  # noqa: E501
            stderr="",
        )
        # If session management is very robust, _get_session might be called before list_collections
        mock_unlock_check2 = MagicMock(returncode=0)  # Assume session still valid for list

        mock_subprocess_run.side_effect = [
            mock_unlock_check1,
            mock_sync,
            mock_encode,
            mock_create_fails,
            mock_unlock_check2,
            mock_list_collections,
        ]

        # Pre-set a valid session to simplify the mock flow for this test
        current_session_key = "valid_test_session"
        client = VaultwardenClient(organization_id=self.organization_id)
        client.bw_session = current_session_key  # Pre-set session
        os.environ["BW_SESSION"] = current_session_key  # Ensure it's in env for subprocess

        found_id = client.create_collection(collection_name)
        self.assertEqual(found_id, existing_collection_id)

        all_calls = mock_subprocess_run.call_args_list
        # Check env for each call to ensure session is passed
        self.assertEqual(all_calls[0][1]["env"].get("BW_SESSION"), current_session_key)  # unlock --check
        self.assertEqual(all_calls[1][1]["env"].get("BW_SESSION"), current_session_key)  # sync
        self.assertEqual(all_calls[2][1]["env"].get("BW_SESSION"), current_session_key)  # encode
        self.assertEqual(all_calls[3][1]["env"].get("BW_SESSION"), current_session_key)  # create (fails)
        self.assertEqual(all_calls[4][1]["env"].get("BW_SESSION"), current_session_key)  # unlock --check for list
        self.assertEqual(all_calls[5][1]["env"].get("BW_SESSION"), current_session_key)  # list

        self.assertEqual(
            all_calls[5][0][0], ["bw", "list", "org-collections", "--organizationid", self.organization_id]
        )

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_create_collection_bw_not_found(self, mock_run_bw_command_method):  # Nom du mock corrigé
        # This test needs _ensure_server_configuration to be unpatched if it's the first call to trigger FileNotFoundError
        # However, with _ensure_server_configuration globally patched in setUp,
        # FileNotFoundError would be raised by _get_session or subsequent calls.

        # Patch _run_bw_command pour qu'il lève FileNotFoundError au premier appel
        mock_run_bw_command_method.side_effect = FileNotFoundError("bw CLI not found here")

        client = VaultwardenClient(organization_id=self.organization_id)
        client.bw_session = None

        with self.assertRaises(FileNotFoundError) as context:
            client.create_collection("Any Collection")
        self.assertIn("bw CLI not found here", str(context.exception))

        # Vérifier que _run_bw_command a été appelé une fois (pour unlock --check)
        # et que c'est cet appel qui a levé l'erreur.
        mock_run_bw_command_method.assert_called_once_with(
            command_parts=["unlock", "--check"],
            input_data=None,
            capture_output=True,  # Assurez-vous que cela correspond à l'appel réel
            custom_env=None,  # Assurez-vous que cela correspond à l'appel réel
        )  # noqa: E501

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_get_collection_by_name_found(self, mock_subprocess_run):
        collection_name = "Target Collection"
        collection_id = "target-id-123"

        mock_unlock_check = MagicMock(returncode=0)  # Session valid
        mock_list = MagicMock(
            returncode=0,
            stdout=json.dumps([{"id": "other", "name": "Another"}, {"id": collection_id, "name": collection_name}]),
            stderr="",
        )
        mock_subprocess_run.side_effect = [mock_unlock_check, mock_list]

        current_session_key = "valid_test_session"
        client = VaultwardenClient(organization_id=self.organization_id)
        client.bw_session = current_session_key
        os.environ["BW_SESSION"] = current_session_key

        found_id = client.get_collection_by_name(collection_name)
        self.assertEqual(found_id, collection_id)

        all_calls = mock_subprocess_run.call_args_list
        self.assertEqual(all_calls[0][1]["env"].get("BW_SESSION"), current_session_key)  # unlock --check
        self.assertEqual(
            all_calls[1][0][0], ["bw", "list", "org-collections", "--organizationid", self.organization_id]
        )
        self.assertEqual(all_calls[1][1]["env"].get("BW_SESSION"), current_session_key)  # list

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_get_collection_by_name_not_found(self, mock_subprocess_run):
        collection_name = "NonExistent Collection"
        current_session_key = "valid_test_session"
        mock_unlock_check = MagicMock(returncode=0)
        mock_list = MagicMock(
            returncode=0, stdout=json.dumps([{"id": "other", "name": "Another"}])  # Does not contain target
        )
        mock_subprocess_run.side_effect = [mock_unlock_check, mock_list]

        client = VaultwardenClient(organization_id=self.organization_id)
        client.bw_session = current_session_key
        os.environ["BW_SESSION"] = current_session_key

        found_id = client.get_collection_by_name(collection_name)
        self.assertIsNone(found_id)
        all_calls = mock_subprocess_run.call_args_list
        self.assertEqual(all_calls[0][1]["env"].get("BW_SESSION"), current_session_key)  # unlock --check
        self.assertEqual(all_calls[1][1]["env"].get("BW_SESSION"), current_session_key)  # list

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_create_collection_no_bw_password_env(self, mock_subprocess_run):
        with patch.dict(os.environ, {"BW_PASSWORD": ""}):
            client = VaultwardenClient(organization_id=self.organization_id)
            client.bw_session = None

            mock_subprocess_run.return_value = MagicMock(returncode=1, stdout="", stderr="not unlocked")

            collection_id = client.create_collection("Test Collection No Pass")
            self.assertIsNone(collection_id)
            # _get_session returns None without calling subprocess because BW_PASSWORD is ""
            # create_collection then returns None without further subprocess calls.
            mock_subprocess_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
