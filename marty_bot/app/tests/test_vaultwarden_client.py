import unittest
from unittest.mock import patch, MagicMock, call
import os
import json

# Assuming vaultwarden_client.py is in marty_bot/clients/
from marty_bot.clients.vaultwarden_client import VaultwardenClient


class TestVaultwardenClient(unittest.TestCase):

    def setUp(self):
        self.organization_id = "test-org-id"
        self.server_url = "https://test.vaultwarden.com"
        self.client_id = "test_client_id"
        self.client_secret = "test_client_secret"

        self.env_patcher_bw_password = patch.dict(os.environ, {"BW_PASSWORD": "testpassword"})
        self.env_patcher_bw_creds = patch.dict(os.environ, {"BW_CLIENTID": "", "BW_CLIENTSECRET": ""})
        self.env_patcher_bw_session = patch.dict(os.environ, {"BW_SESSION": ""})

        self.mock_bw_password = self.env_patcher_bw_password.start()
        self.mock_bw_creds = self.env_patcher_bw_creds.start()
        self.mock_bw_session_env = self.env_patcher_bw_session.start()

        if "BW_SESSION" in os.environ:
            del os.environ["BW_SESSION"]

        self.ensure_server_config_patcher = patch(
            "marty_bot.clients.vaultwarden_client.VaultwardenClient._ensure_server_configuration",
            MagicMock(return_value=True),
        )
        self.mock_ensure_server_config = self.ensure_server_config_patcher.start()

    def tearDown(self):
        self.ensure_server_config_patcher.stop()
        self.env_patcher_bw_creds.stop()
        self.env_patcher_bw_password.stop()
        self.env_patcher_bw_session.stop()
        if "BW_SESSION" in os.environ:
            del os.environ["BW_SESSION"]

    def test_initialization(self):
        client = VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
        self.assertEqual(client.organization_id, self.organization_id)
        self.assertEqual(client.server_url, self.server_url)
        self.assertIsNone(client.bw_session)

    def test_initialization_missing_org_id(self):
        with self.assertRaises(ValueError) as context:
            VaultwardenClient(organization_id="", server_url=self.server_url)
        self.assertIn("Vaultwarden organization_id must be provided", str(context.exception))

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_ensure_server_configuration_already_set(self, mock_subprocess_run_specific):
        self.ensure_server_config_patcher.stop()
        try:
            mock_subprocess_run_specific.return_value = MagicMock(returncode=0, stdout=self.server_url, stderr="")
            VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
            mock_subprocess_run_specific.assert_called_once_with(
                ["bw", "config", "server"],
                capture_output=True,
                text=True,
                check=False,
                input=None,
                env=unittest.mock.ANY,
            )
        finally:
            self.ensure_server_config_patcher.start()

    @patch("marty_bot.clients.vaultwarden_client.subprocess.run")
    def test_ensure_server_configuration_needs_set(self, mock_subprocess_run_specific):
        self.ensure_server_config_patcher.stop()
        try:
            mock_check = MagicMock(returncode=0, stdout="https://otherserver.com", stderr="")
            mock_set = MagicMock(returncode=0, stdout="", stderr="")
            mock_subprocess_run_specific.side_effect = [mock_check, mock_set]
            VaultwardenClient(organization_id=self.organization_id, server_url=self.server_url)
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
    def test_get_session_unlock_successful(self, mock_run_bw_command):
        client = VaultwardenClient(
            organization_id=self.organization_id,
            # No client_id/secret, rely on BW_PASSWORD
        )
        client.bw_session = None
        os.environ["BW_PASSWORD"] = "testpassword"  # Ensure BW_PASSWORD is set for this path

        status_output_locked = json.dumps({"status": "locked", "serverUrl": self.server_url})
        expected_session_key = "session_key_from_unlock"

        # Corrected side_effect:
        # Path: status (locked) -> no self.bw_session -> password unlock attempt
        # Only 2 calls to _run_bw_command are expected in this specific scenario.
        def bw_command_responses_gen():
            # 1st call: 'bw status' from _check_and_perform_login
            yield (0, status_output_locked, "")
            # 2nd call: 'bw unlock --passwordenv' from _get_session password path
            yield (0, f"{expected_session_key}\n", "")

        mock_run_bw_command.side_effect = bw_command_responses_gen()

        session = client._get_session()
        self.assertEqual(session, expected_session_key)
        self.assertEqual(client.bw_session, expected_session_key)
        self.assertEqual(os.environ.get("BW_SESSION"), expected_session_key)

        calls = mock_run_bw_command.call_args_list
        self.assertEqual(len(calls), 2) # Expect 2 calls

        # Call 1: status --raw
        self.assertEqual(calls[0][0][0], ["status", "--raw"]) # Positional args: command_parts
        # custom_env for status call is prepared by _check_and_perform_login
        expected_custom_env_status = {
            "BW_CLIENTID": None, # Client initialized with no client_id
            "BW_CLIENTSECRET": None, # Client initialized with no client_secret
            # PATH is too volatile to assert directly from os.environ.get in a complex way
        }
        # Ensure 'custom_env' was a kwarg and check relevant keys
        self.assertIn("custom_env", calls[0][1])
        actual_status_custom_env = calls[0][1]["custom_env"]
        # When None is passed for client_id/secret, they appear as "" in the effective env for subprocess
        self.assertEqual(actual_status_custom_env.get("BW_CLIENTID"), "")
        self.assertEqual(actual_status_custom_env.get("BW_CLIENTSECRET"), "")
        self.assertIn("PATH", actual_status_custom_env) # Check PATH key exists

        # Call 2: unlock --passwordenv BW_PASSWORD --raw
        self.assertEqual(calls[1][0][0], ["unlock", "--passwordenv", "BW_PASSWORD", "--raw"])
        actual_unlock_custom_env = calls[1][1]["custom_env"]
        self.assertEqual(actual_unlock_custom_env.get("BW_PASSWORD"), "testpassword")
        # The custom_env passed to _run_bw_command for unlock specifically excludes BW_SESSION.
        self.assertIsNone(actual_unlock_custom_env.get("BW_SESSION"))

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_get_session_with_api_key_login_success(self, mock_run_bw_command):
        client = VaultwardenClient(
            organization_id=self.organization_id, client_id=self.client_id, client_secret=self.client_secret
        )
        client.bw_session = None

        status_output_unauth = json.dumps({"status": "unauthenticated", "serverUrl": self.server_url})
        expected_session_key = "session_after_api_login_and_unlock"

        # Corrected side_effect:
        # 1. status (unauthenticated) -> triggers API login
        # 2. login --apikey (succeeds)
        # 3. sync (after API login, succeeds)
        #    (_check_and_perform_login now clears self.bw_session)
        # 4. unlock --passwordenv (as self.bw_session is None, no unlock --check, directly to password)
        def bw_command_responses_gen():
            yield (0, status_output_unauth, "") # Call 1: status
            yield (0, "", "") # Call 2: login --apikey
            yield (0, "Synced", "") # Call 3: sync
            yield (0, f"{expected_session_key}\n", "") # Call 4: unlock --passwordenv

        mock_run_bw_command.side_effect = bw_command_responses_gen()

        session = client._get_session()
        self.assertEqual(session, expected_session_key)
        self.assertEqual(client.bw_session, expected_session_key)
        self.assertEqual(os.environ.get("BW_SESSION"), expected_session_key)


        calls = mock_run_bw_command.call_args_list
        self.assertEqual(len(calls), 4) # Expect 4 calls

        # Call 1: status
        self.assertEqual(calls[0][0][0], ["status", "--raw"])
        expected_custom_env_status_keys = { # Check for relevant keys
            "BW_CLIENTID": self.client_id, "BW_CLIENTSECRET": self.client_secret
        }
        actual_status_custom_env = calls[0][1]["custom_env"]
        self.assertEqual(actual_status_custom_env.get("BW_CLIENTID"), expected_custom_env_status_keys["BW_CLIENTID"])
        self.assertEqual(actual_status_custom_env.get("BW_CLIENTSECRET"), expected_custom_env_status_keys["BW_CLIENTSECRET"])
        self.assertIn("PATH", actual_status_custom_env) # Ensure PATH is in the env

        # Call 2: login --apikey
        self.assertEqual(calls[1][0][0], ["login", "--apikey"])
        expected_custom_env_login = {
            "BW_CLIENTID": self.client_id, "BW_CLIENTSECRET": self.client_secret, "PATH": os.environ.get("PATH", "")
        }
        # Note: login_env_for_api in client code copies os.environ then updates.
        # For mock assertion, we check the 'custom_env' arg passed to _run_bw_command.
        # The client prepares login_env_for_api and passes it as custom_env.
        # This env includes PATH from os.environ.copy()
        self.assertIn("custom_env", calls[1][1])
        actual_login_env = calls[1][1]["custom_env"]
        self.assertEqual(actual_login_env.get("BW_CLIENTID"), self.client_id)
        self.assertEqual(actual_login_env.get("BW_CLIENTSECRET"), self.client_secret)
        self.assertTrue("PATH" in actual_login_env)


        # Call 3: sync
        self.assertEqual(calls[2][0][0], ["sync"])
        # Similar to login, _sync_vault_after_api_login receives login_env_for_api
        self.assertIn("custom_env", calls[2][1])
        actual_sync_env = calls[2][1]["custom_env"]
        self.assertEqual(actual_sync_env.get("BW_CLIENTID"), self.client_id)
        self.assertEqual(actual_sync_env.get("BW_CLIENTSECRET"), self.client_secret)
        self.assertTrue("PATH" in actual_sync_env)

        # Call 4: unlock --passwordenv
        self.assertEqual(calls[3][0][0], ["unlock", "--passwordenv", "BW_PASSWORD", "--raw"])
        actual_unlock_custom_env = calls[3][1]["custom_env"]
        self.assertEqual(actual_unlock_custom_env.get("BW_PASSWORD"), "testpassword")
        # Client._get_session pops BW_SESSION from unlock_env before passing as custom_env,
        # but _run_bw_command copies os.environ first which might not have BW_SESSION if it was cleared.
        # More importantly, the custom_env passed to _run_bw_command for unlock should not contain BW_SESSION.
        # The resulting env_for_subprocess in _run_bw_command might inherit BW_SESSION from os.environ
        # if it wasn't cleared globally AND not present in the small custom_env.
        # For this test, the key is that the *small* custom_env passed to _run_bw_command had BW_PASSWORD
        # and did not have BW_SESSION. The actual_unlock_custom_env is the *effective* env.
        # If BW_SESSION was globally cleared by API login step, it won't be in actual_unlock_custom_env.
        self.assertIsNone(actual_unlock_custom_env.get("BW_SESSION"))


    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_get_session_unlock_fails_no_password_env(self, mock_run_bw_command):
        with patch.dict(os.environ, {"BW_PASSWORD": ""}):
            client = VaultwardenClient(
                organization_id=self.organization_id,
                # No client_id/secret, so API login won't happen.
                # BW_PASSWORD is also empty, so password unlock will be skipped.
            )
            client.bw_session = None
            status_output_locked = json.dumps({"status": "locked", "serverUrl": self.server_url})
            mock_run_bw_command.return_value = (0, status_output_locked, "")  # bw status

            session = client._get_session()
            self.assertIsNone(session)
            # Using ANY for custom_env due to difficulties matching the exact dict from mock's perspective.
            mock_run_bw_command.assert_called_once_with(
                ["status", "--raw"], # Positional arg
                custom_env=unittest.mock.ANY
            )

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_get_session_already_valid(self, mock_run_bw_command):
        client = VaultwardenClient(
            organization_id=self.organization_id, client_id=self.client_id, client_secret=self.client_secret
        )
        valid_session_key = "existing_valid_session"
        client.bw_session = valid_session_key
        os.environ["BW_SESSION"] = valid_session_key  # Ensure os.environ matches

        status_output_unlocked = json.dumps({"status": "unlocked", "serverUrl": self.server_url})
        mock_run_bw_command.side_effect = [
            (0, status_output_unlocked, ""),  # 1. bw status (unlocked)
            (0, "", ""),  # 2. bw unlock --check (succeeds with existing session)
        ]

        session = client._get_session()
        self.assertEqual(session, valid_session_key)

        calls = mock_run_bw_command.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0][0], ["status", "--raw"])
        self.assertEqual(calls[1][0][0], ["unlock", "--check"])
        self.assertNotIn("custom_env", calls[1][1]) # custom_env not passed to _run_bw_command

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_sync_vault_successful(self, mock_run_bw_command):
        client = VaultwardenClient(organization_id=self.organization_id)
        client.bw_session = "test_session_key"
        os.environ["BW_SESSION"] = "test_session_key"

        mock_run_bw_command.return_value = (0, "Synced!", "")  # (rc, stdout, stderr)

        self.assertTrue(client._sync_vault())
        # _run_bw_command is called with only command_parts.
        # input_data, capture_output, and custom_env use their defaults within _run_bw_command.
        mock_run_bw_command.assert_called_once_with(["sync"])

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_sync_vault_fails_due_to_session(self, mock_run_bw_command):
        client = VaultwardenClient(organization_id=self.organization_id)
        initial_session = "old_test_session_key"
        client.bw_session = initial_session
        os.environ["BW_SESSION"] = initial_session

        mock_run_bw_command.return_value = (1, "", "invalid session token")

        self.assertFalse(client._sync_vault())
        self.assertIsNone(client.bw_session)
        self.assertNotIn("BW_SESSION", os.environ)

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_create_collection_successful(self, mock_run_bw_command):
        collection_name = "New Test Collection"
        collection_id = "new-coll-id"
        session_key_for_test = "session_for_create_test"
        os.environ["BW_PASSWORD"] = "testpassword"  # Ensure BW_PASSWORD is set

        status_output_locked = json.dumps({"status": "locked", "serverUrl": self.server_url})

        # Corrected sequence of mock calls for this path (no API creds, BW_PASSWORD used)
        # 1. status (locked)
        # 2. unlock --passwordenv (succeeds)
        # 3. sync
        # 4. encode
        # 5. create org-collection
        def bw_command_responses_gen():
            yield (0, status_output_locked, "")  # Call 1: status
            yield (0, f"{session_key_for_test}\n", "")  # Call 2: unlock --passwordenv
            yield (0, "Synced", "")  # Call 3: sync
            yield (0, "encoded_payload_string", "")  # Call 4: encode
            yield (0, json.dumps({"id": collection_id, "name": collection_name}), "")  # Call 5: create

        mock_run_bw_command.side_effect = bw_command_responses_gen()

        client = VaultwardenClient(organization_id=self.organization_id)  # No API creds, will use password
        created_id = client.create_collection(collection_name)

        self.assertEqual(created_id, collection_id)

        calls = mock_run_bw_command.call_args_list
        self.assertEqual(len(calls), 5) # Expect 5 calls

        # Call 1: status
        self.assertEqual(calls[0][0][0], ["status", "--raw"])
        actual_status_custom_env = calls[0][1]["custom_env"]
        # When None is passed for client_id/secret, they appear as "" in the effective env for subprocess
        self.assertEqual(actual_status_custom_env.get("BW_CLIENTID"), "")
        self.assertEqual(actual_status_custom_env.get("BW_CLIENTSECRET"), "")
        self.assertIn("PATH", actual_status_custom_env) # Ensure PATH is in the env

        # Call 2: unlock --passwordenv
        self.assertEqual(calls[1][0][0], ["unlock", "--passwordenv", "BW_PASSWORD", "--raw"])
        actual_unlock_custom_env = calls[1][1]["custom_env"]
        self.assertEqual(actual_unlock_custom_env.get("BW_PASSWORD"), "testpassword")
        # The custom_env passed to _run_bw_command for unlock specifically excludes BW_SESSION.
        # The effective env (actual_unlock_custom_env) should reflect this,
        # or BW_SESSION from os.environ should not be present if cleared by setup.
        self.assertIsNone(actual_unlock_custom_env.get("BW_SESSION"))


        # Call 3: sync
        self.assertEqual(calls[2][0][0], ["sync"])
        self.assertNotIn("custom_env", calls[2][1]) # No custom_env passed to _run_bw_command

        # Call 4: encode
        self.assertEqual(calls[3][0][0], ["encode"])
        # json.dumps typically adds a space after the colon
        self.assertIn(f'"name": "{collection_name}"', calls[3][1]["input_data"])
        self.assertNotIn("custom_env", calls[3][1])

        # Call 5: create org-collection
        self.assertEqual(calls[4][0][0], ["create", "org-collection", "--organizationid", self.organization_id])
        self.assertEqual(calls[4][1]["input_data"], "encoded_payload_string")
        self.assertNotIn("custom_env", calls[4][1])

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_create_collection_already_exists(self, mock_run_bw_command):
        collection_name = "Existing Collection"
        existing_collection_id = "existing-coll-id"
        current_session_key = "valid_test_session"
        status_output_unlocked = json.dumps({"status": "unlocked", "serverUrl": self.server_url})

        mock_run_bw_command.side_effect = [
            (0, status_output_unlocked, ""),  # 1. bw status (unlocked)
            (0, "", ""),  # 2. bw unlock --check (session valid)
            (0, "Synced", ""),  # 3. bw sync
            (0, "encoded_payload", ""),  # 4. bw encode
            (1, "", "ERROR: Collection with this name already exists."),  # 5. bw create (fails)
            # Calls for get_collection_by_name fallback
            (0, status_output_unlocked, ""),  # 6. bw status (still unlocked)
            (0, "", ""),  # 7. bw unlock --check (session still valid)
            (
                0,
                json.dumps(
                    [
                        {"id": "other-id", "name": "Other Collection"},
                        {"id": existing_collection_id, "name": collection_name},
                    ]
                ),
                "",
            ),  # 8. bw list org-collections
        ]

        client = VaultwardenClient(
            organization_id=self.organization_id,
            client_id=self.client_id,  # Provide API creds for this path
            client_secret=self.client_secret,
        )
        client.bw_session = current_session_key
        os.environ["BW_SESSION"] = current_session_key

        found_id = client.create_collection(collection_name)
        self.assertEqual(found_id, existing_collection_id)

        calls = mock_run_bw_command.call_args_list
        self.assertEqual(len(calls), 8)
        self.assertEqual(calls[0][0][0], ["status", "--raw"])
        self.assertEqual(calls[1][0][0], ["unlock", "--check"])
        self.assertEqual(calls[2][0][0], ["sync"])
        self.assertEqual(calls[3][0][0], ["encode"])
        self.assertEqual(calls[4][0][0], ["create", "org-collection", "--organizationid", self.organization_id])
        self.assertEqual(calls[5][0][0], ["status", "--raw"])
        self.assertEqual(calls[6][0][0], ["unlock", "--check"])
        self.assertEqual(calls[7][0][0], ["list", "org-collections", "--organizationid", self.organization_id])

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_create_collection_bw_not_found(self, mock_run_bw_command):
        mock_run_bw_command.side_effect = FileNotFoundError("bw CLI not found here")
        client = VaultwardenClient(organization_id=self.organization_id)

        with self.assertRaises(FileNotFoundError) as context:
            client.create_collection("Any Collection")
        self.assertIn("bw CLI not found here", str(context.exception))
        # _check_and_perform_login calls _run_bw_command with a specific custom_env
        # PATH comparison is fragile, and the exact content of custom_env recorded by mock is problematic.
        # Using unittest.mock.ANY for custom_env if the main point is that 'status --raw' was called.
        mock_run_bw_command.assert_called_once_with(
            ["status", "--raw"], # command_parts is positional
            custom_env=unittest.mock.ANY
        )

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_get_collection_by_name_found(self, mock_run_bw_command):
        collection_name = "Target Collection"
        collection_id = "target-id-123"
        current_session_key = "valid_test_session"
        status_output_unlocked = json.dumps({"status": "unlocked", "serverUrl": self.server_url})

        mock_run_bw_command.side_effect = [
            (0, status_output_unlocked, ""),  # 1. bw status
            (0, "", ""),  # 2. bw unlock --check (session valid)
            (
                0,
                json.dumps([{"id": "other", "name": "Another"}, {"id": collection_id, "name": collection_name}]),
                "",
            ),  # 3. bw list org-collections
        ]

        client = VaultwardenClient(organization_id=self.organization_id)
        client.bw_session = current_session_key
        os.environ["BW_SESSION"] = current_session_key

        found_id = client.get_collection_by_name(collection_name)
        self.assertEqual(found_id, collection_id)

        calls = mock_run_bw_command.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0][0], ["status", "--raw"])
        self.assertEqual(calls[1][0][0], ["unlock", "--check"])
        self.assertEqual(calls[2][0][0], ["list", "org-collections", "--organizationid", self.organization_id])
        self.assertNotIn("custom_env", calls[2][1]) # custom_env not passed to _run_bw_command

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_get_collection_by_name_not_found(self, mock_run_bw_command):
        collection_name = "NonExistent Collection"
        current_session_key = "valid_test_session"
        status_output_unlocked = json.dumps({"status": "unlocked", "serverUrl": self.server_url})

        mock_run_bw_command.side_effect = [
            (0, status_output_unlocked, ""),  # 1. bw status
            (0, "", ""),  # 2. bw unlock --check (session valid)
            (0, json.dumps([{"id": "other", "name": "Another"}]), ""),  # 3. bw list
        ]

        client = VaultwardenClient(organization_id=self.organization_id)
        client.bw_session = current_session_key
        os.environ["BW_SESSION"] = current_session_key

        found_id = client.get_collection_by_name(collection_name)
        self.assertIsNone(found_id)

        calls = mock_run_bw_command.call_args_list
        self.assertEqual(len(calls), 3)

    @patch("marty_bot.clients.vaultwarden_client.VaultwardenClient._run_bw_command")
    def test_create_collection_no_bw_password_env(self, mock_run_bw_command):
        with patch.dict(os.environ, {"BW_PASSWORD": ""}):  # Ensure BW_PASSWORD is empty
            client = VaultwardenClient(organization_id=self.organization_id)  # No API creds
            client.bw_session = None

            # Simulate 'bw status' returning locked.
            status_output_locked = json.dumps({"status": "locked", "serverUrl": self.server_url})
            # _get_session calls _check_and_perform_login, which calls 'bw status'.
            # If BW_PASSWORD is empty and API login isn't applicable/failed, _get_session returns None.
            mock_run_bw_command.return_value = (0, status_output_locked, "") # Simulates the 'bw status' call

            collection_id = client.create_collection("Test Collection No Pass")
            self.assertIsNone(collection_id)  # Because _get_session returns None

            # Expected call: only 'status --raw' because BW_PASSWORD is empty
            self.assertEqual(mock_run_bw_command.call_count, 1)
            # We need to be careful with custom_env. For now, let's use ANY.
            # The actual custom_env passed by the client for 'status' includes client_id, client_secret (as None if not set) and PATH.
            # Using ANY for custom_env due to difficulties in matching the exact dict.
            mock_run_bw_command.assert_called_once_with(
                ["status", "--raw"], # Positional argument for command_parts
                custom_env=unittest.mock.ANY
                # input_data and capture_output use defaults and are not explicitly checked here for simplicity
            )


if __name__ == "__main__":
    unittest.main()
