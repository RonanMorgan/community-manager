import subprocess
import json
import os
import logging

# import tempfile # No longer used


class VaultwardenClient:
    def __init__(
        self,
        organization_id: str,
        server_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        """
        Initializes the VaultwardenClient.
        :param organization_id: The ID of the organization in Vaultwarden.
        :param server_url: The URL of the Vaultwarden server. If None, it's assumed 'bw config server' was already run.
        :param client_id: The BW_CLIENTID for API key login.
        :param client_secret: The BW_CLIENTSECRET for API key login.
        """
        if not organization_id:
            raise ValueError("Vaultwarden organization_id must be provided.")
        self.organization_id = organization_id
        self.server_url = server_url
        self.client_id = client_id
        self.client_secret = client_secret
        # Try to get BW_SESSION from env first, might be set by a wrapper or previous run
        self.bw_session = os.getenv("BW_SESSION")
        self._ensure_server_configuration()  # Initial server config check

    def _run_bw_command(
        self,
        command_parts: list[str],
        input_data: str | None = None,
        capture_output: bool = True,
        custom_env: dict | None = None,
    ) -> tuple[int, str, str]:
        """
        Helper function to run a 'bw' command.
        Returns the return code, stdout, and stderr.
        'custom_env' will override the default environment handling if provided.
        """
        try:
            # Prepare environment for subprocess
            env_for_subprocess = os.environ.copy()
            if self.bw_session:  # Pass current session if available
                env_for_subprocess["BW_SESSION"] = self.bw_session
            if custom_env:  # Allow overriding with a fully custom environment
                env_for_subprocess = custom_env

            logging.debug(f"Running bw command: {' '.join(['bw'] + command_parts)}")  # Ensure 'bw' is part of log
            process = subprocess.run(
                ["bw"] + command_parts,
                input=input_data.encode() if input_data else None,
                capture_output=capture_output,
                text=True,
                check=False,
                env=env_for_subprocess,
            )
            logging.debug(f"bw command stdout: {process.stdout.strip() if process.stdout else ''}")
            logging.debug(f"bw command stderr: {process.stderr.strip() if process.stderr else ''}")
            return process.returncode, process.stdout, process.stderr
        except FileNotFoundError:
            logging.error("'bw' command-line tool not found. Please ensure it is installed and in PATH.")
            raise
        except Exception as e:
            logging.error(f"An unexpected error occurred while running bw command: {e}")
            return 1, "", str(e)

    def _ensure_server_configuration(self):
        """Ensures the Vaultwarden server URL is configured if provided."""
        if self.server_url:
            returncode, stdout, _ = self._run_bw_command(["config", "server"])
            if returncode == 0 and self.server_url in stdout:
                logging.info(f"Vaultwarden server URL is already set to {self.server_url}.")
                return True

            logging.info(f"Attempting to set Vaultwarden server URL to {self.server_url}...")
            returncode, _, stderr = self._run_bw_command(["config", "server", self.server_url])
            if returncode != 0:
                error_message = f"Failed to configure Vaultwarden server URL to {self.server_url}: {stderr.strip()}"
                logging.error(error_message)
                return False
            logging.info(f"Vaultwarden server URL configured to {self.server_url}.")
        return True

    def _check_and_perform_login(self) -> bool:
        """
        Checks current Bitwarden status and performs login if necessary using API key.
        Returns True if login is successful or not needed, False if login fails.
        """
        logging.debug("Checking Bitwarden login status...")
        # Run with a clean env for status check, no session key needed/wanted here for status itself.
        # BW_CLIENTID and BW_CLIENTSECRET might be needed by 'bw status' if not fully logged out,
        # or if the CLI uses them to determine which account's status to check.
        # For safety, pass them if available.
        env_for_status = os.environ.copy()
        env_for_status.pop("BW_SESSION", None)  # Ensure no session key is used for status check
        if self.client_id:
            env_for_status["BW_CLIENTID"] = self.client_id
        if self.client_secret:
            env_for_status["BW_CLIENTSECRET"] = self.client_secret
        # Server config is handled by _ensure_server_configuration called in __init__
        # and can be re-checked if status implies wrong server.

        rc_status, stdout_status, stderr_status = self._run_bw_command(["status", "--raw"], custom_env=env_for_status)

        if rc_status != 0:
            # If status itself fails, it might be because server is not configured yet
            # or other fundamental CLI issue.
            logging.error(f"Failed to get Bitwarden status: {stderr_status.strip()}")
            if self.server_url and "not logged in to a server" in stderr_status.lower():
                logging.info("Attempting to configure server as status check failed...")
                if not self._ensure_server_configuration():
                    logging.error("Server configuration failed. Cannot proceed.")
                    return False
                # Retry status after server configuration
                rc_status, stdout_status, stderr_status = self._run_bw_command(
                    ["status", "--raw"], custom_env=env_for_status
                )
                if rc_status != 0:
                    logging.error(f"Still failed to get Bitwarden status after server config: {stderr_status.strip()}")
                    return False
            else:
                return False  # Unrecoverable status error

        try:
            status_data = json.loads(stdout_status)
            current_cli_status = status_data.get("status")
            # current_server_url_from_status = status_data.get("serverUrl")
            # Re-check server URL if self.server_url is provided and differs
            # if self.server_url and current_server_url_from_status != self.server_url:
            #    logging.warning(f"Server URL mismatch: Expected '{self.server_url}', got '{current_server_url_from_status}'. Re-configuring.")
            #    if not self._ensure_server_configuration(): return False
            # Potentially need to re-fetch status here. For now, assume 'unauthenticated' will trigger login.
        except json.JSONDecodeError:
            logging.error(f"Failed to parse Bitwarden status JSON: {stdout_status.strip()}")
            return False

        if current_cli_status == "unauthenticated":
            logging.info("Bitwarden status is 'unauthenticated'. Attempting API key login.")
            if not self.client_id or not self.client_secret:
                logging.error(
                    "Cannot login with API key: VaultwardenClient not configured with client_id and client_secret."
                )
                return False

            login_env_for_api = os.environ.copy()
            login_env_for_api["BW_CLIENTID"] = self.client_id
            login_env_for_api["BW_CLIENTSECRET"] = self.client_secret
            login_env_for_api.pop("BW_SESSION", None)

            rc_login, _, stderr_login = self._run_bw_command(
                ["login", "--apikey"], custom_env=login_env_for_api, capture_output=True
            )

            if rc_login == 0:
                logging.info("Successfully logged in using API key.")
                # Sync after login to ensure local cache is up to date.
                if not self._sync_vault_after_api_login(login_env_for_api):
                    # Log warning but still consider API login part successful for now,
                    # as the main goal was to authenticate the CLI.
                    # Sync issues can be handled separately if they persist.
                    logging.warning("Sync after API key login failed. Proceeding, but vault might be stale.")

                # Critical: `bw login --apikey` authenticates the CLI but does not output a session key
                # suitable for BW_SESSION. We must clear self.bw_session here to ensure that
                # the main _get_session logic proceeds to a proper unlock sequence (e.g., using BW_PASSWORD)
                # to obtain a usable session key.
                logging.info("API key login and sync successful. Clearing internal/env BW_SESSION to force proper unlock.")
                self.bw_session = None
                if "BW_SESSION" in os.environ:
                    del os.environ["BW_SESSION"]
                return True
            else:
                logging.error(f"Failed to login using API key: {stderr_login.strip()}")
                return False
        elif current_cli_status in ["locked", "unlocked"]:
            logging.info(f"Bitwarden status is '{current_cli_status}'. API key login not immediately needed.")
            return True
        else:
            logging.warning(f"Unknown Bitwarden status: '{current_cli_status}'. Proceeding with caution.")
            return True

    def _sync_vault_after_api_login(self, login_env_with_api_keys: dict) -> bool:
        """
        Runs 'bw sync' specifically after an API key login, using the environment
        that was successful for the login (containing API keys, no session key).
        """
        logging.info("Syncing Vaultwarden local cache after API key login...")
        returncode, _, stderr = self._run_bw_command(["sync"], custom_env=login_env_with_api_keys)
        if returncode != 0:
            logging.error(f"Failed to sync Vaultwarden after API key login: {stderr.strip()}")
            return False
        logging.info("Vaultwarden sync after API key login successful.")
        return True

    def _get_session(self) -> str | None:
        """
        Ensures a valid Bitwarden session key (BW_SESSION) is available.
        Performs login via API key if needed, then unlocks using master password.
        Manages self.bw_session.
        """
        # Step 1: Ensure server config is set if self.server_url is provided.
        # _ensure_server_configuration is called in __init__.
        # It could be called again here if status indicated a server mismatch,
        # but _check_and_perform_login also has a basic check.

        # Step 2: Check login status and perform API key login if client is unauthenticated.
        if not self._check_and_perform_login():
            logging.error("Initial login check/API key login failed. Cannot proceed to get session key.")
            return None

        # Step 3: If we have an existing session key (self.bw_session), check if it's still valid.
        if self.bw_session:
            logging.debug("Checking existing BW_SESSION...")
            # Use default env for _run_bw_command, which will include self.bw_session if set
            rc_check, _, err_check = self._run_bw_command(["unlock", "--check"])
            if rc_check == 0:
                logging.info("Existing BW_SESSION is valid.")
                return self.bw_session
            else:
                logging.warning(
                    f"Existing BW_SESSION is invalid or expired: {err_check.strip()}. Attempting to unlock for new session key."
                )
                self.bw_session = None
                if "BW_SESSION" in os.environ:
                    del os.environ["BW_SESSION"]

        # Step 4: If no valid session, attempt to unlock using master password to get/refresh the session key.
        # This is necessary even after API key login to get the BW_SESSION for command execution.
        bw_password = os.getenv("BW_PASSWORD")
        if not bw_password:
            logging.error("BW_PASSWORD environment variable is not set. Cannot unlock Vaultwarden.")
            return None

        logging.info("Attempting to unlock Vaultwarden using BW_PASSWORD...")

        # Use --passwordenv for passing password
        unlock_env = os.environ.copy()
        unlock_env["BW_PASSWORD"] = bw_password
        # Clear BW_SESSION from this custom_env if it was there, to ensure clean unlock
        unlock_env.pop("BW_SESSION", None)

        # Assign to distinct local variables
        rc_unlock_attempt, sout_unlock_attempt, err_unlock_attempt = self._run_bw_command(
            ["unlock", "--passwordenv", "BW_PASSWORD", "--raw"],
            custom_env=unlock_env,  # Pass the environment with BW_PASSWORD
        )
        new_session_key_val = sout_unlock_attempt.strip()

        # DEBUGGING LOG to see the exact values before the conditional
        logging.debug(
            f"VaultwardenClient._get_session: unlock with password results - "
            f"rc_unlock={rc_unlock_attempt}, "
            f"new_session_key='{new_session_key_val}', "
            f"stderr_unlock='{err_unlock_attempt.strip()}'"
        )

        if rc_unlock_attempt == 0 and new_session_key_val:
            logging.info("Successfully unlocked Vaultwarden and obtained new session key.")
            self.bw_session = new_session_key_val
            os.environ["BW_SESSION"] = self.bw_session
            return self.bw_session
        else:
            logging.error(f"Failed to unlock Vaultwarden: {err_unlock_attempt.strip()}")
            self.bw_session = None
            if "BW_SESSION" in os.environ:
                del os.environ["BW_SESSION"]
            return None

    def _sync_vault(self) -> bool:
        """
        Runs 'bw sync' to ensure the local cache is up-to-date.
        Requires a valid session.
        """
        if not self.bw_session:  # Relies on _get_session having been called if needed
            logging.error("Cannot sync vault: No active BW_SESSION available to client.")
            return False

        logging.info("Syncing Vaultwarden local cache...")
        returncode, _, stderr = self._run_bw_command(["sync"])
        if returncode != 0:
            logging.error(f"Failed to sync Vaultwarden: {stderr.strip()}")
            if "invalid session token" in stderr.lower() or "not logged in" in stderr.lower():
                logging.warning("Sync failed due to session issue. Clearing current BW_SESSION.")
                self.bw_session = None
                if "BW_SESSION" in os.environ:
                    del os.environ["BW_SESSION"]
            return False
        logging.info("Vaultwarden sync successful.")
        return True

    def create_collection(self, collection_name: str, group_ids: list[dict] | None = None) -> str | None:
        """
        Creates a new collection in Vaultwarden.
        :param collection_name: The name for the new collection.
        :param group_ids: Optional. A list of group associations.
        :return: The ID of the created collection if successful, None otherwise.
        """
        if not self._get_session():  # This will attempt to unlock if needed
            logging.error("Cannot create collection: Failed to obtain Vaultwarden session.")
            return None
        if not self._sync_vault():
            logging.warning("Vault sync failed before creating collection. Proceeding, but data might be stale.")

        logging.info(f"Attempting to create Vaultwarden collection: '{collection_name}'")

        collection_data = {
            "organizationId": self.organization_id,
            "name": collection_name,
            "externalId": None,
            "groups": group_ids if group_ids else [],
        }

        returncode_encode, encoded_payload_stdout, stderr_encode = self._run_bw_command(
            ["encode"], input_data=json.dumps(collection_data)
        )
        encoded_payload = encoded_payload_stdout.strip()

        if returncode_encode != 0:
            logging.error(f"Failed to encode collection data using 'bw encode': {stderr_encode.strip()}")
            return None

        logging.debug(f"Encoded payload for collection creation: {encoded_payload}")

        returncode_create, stdout_create, stderr_create = self._run_bw_command(
            ["create", "org-collection", "--organizationid", self.organization_id], input_data=encoded_payload
        )

        if returncode_create == 0:
            try:
                created_collection_info = json.loads(stdout_create)
                new_collection_id = created_collection_info.get("id")
                if new_collection_id:
                    logging.info(
                        f"Successfully created Vaultwarden collection '{collection_name}' "
                        f"with ID: {new_collection_id}"
                    )
                    return new_collection_id
                else:
                    logging.error(
                        f"Ran 'bw create org-collection' for '{collection_name}', "
                        f"but no ID in response: {stdout_create.strip()}"
                    )
                    return None
            except json.JSONDecodeError:
                logging.error(
                    f"Failed to parse JSON from 'bw create org-collection' for '{collection_name}'. "
                    f"Output: {stdout_create.strip()}"
                )
                return None
        else:
            if "already exists" in stderr_create.lower() and "collection" in stderr_create.lower():
                logging.warning(
                    f"Vaultwarden collection '{collection_name}' may already exist. Attempting to find it."
                )
                return self.get_collection_by_name(collection_name)
            else:
                logging.error(f"Failed to create Vaultwarden collection '{collection_name}': {stderr_create.strip()}")
                return None

    def get_collection_by_name(self, collection_name: str) -> str | None:
        """
        Retrieves a collection ID by its name.
        :param collection_name: The name of the collection.
        :return: The ID of the collection if found, None otherwise.
        """
        if not self._get_session():
            logging.error("Cannot get collection by name: Failed to obtain Vaultwarden session.")
            return None

        logging.debug(
            f"Attempting to find Vaultwarden collection by name: '{collection_name}' for org '{self.organization_id}'"
        )
        returncode, stdout, stderr = self._run_bw_command(
            ["list", "org-collections", "--organizationid", self.organization_id]
        )

        if returncode == 0:
            try:
                collections = json.loads(stdout)
                for collection in collections:
                    if collection.get("name") == collection_name:
                        collection_id = collection.get("id")
                        logging.info(f"Found existing collection '{collection_name}' with ID: {collection_id}")
                        return collection_id
                logging.info(f"Collection '{collection_name}' not found in organization '{self.organization_id}'.")
                return None
            except json.JSONDecodeError:
                logging.error(
                    f"Failed to parse JSON response from 'bw list org-collections'. Output: {stdout.strip()}"
                )
                return None
        else:
            logging.error(f"Failed to list Vaultwarden collections: {stderr.strip()}")
            return None


if __name__ == "__main__":
    log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=log_format)
    org_id_env = os.getenv("VAULTWARDEN_ORGANIZATION_ID")
    vw_server_env = os.getenv("VAULTWARDEN_SERVER_URL")
    bw_pass_env = os.getenv("BW_PASSWORD")

    if not org_id_env:
        logging.error("Please set VAULTWARDEN_ORGANIZATION_ID environment variable.")
    elif not bw_pass_env:
        logging.error("Please set BW_PASSWORD environment variable for testing.")
    else:
        client = VaultwardenClient(organization_id=org_id_env, server_url=vw_server_env)
        test_coll_name = "MartyBot Client Test Collection"

        coll_id = client.create_collection(test_coll_name)
        if coll_id:
            logging.info(f"Main test: Collection '{test_coll_name}' created/found with ID: {coll_id}")

            # Verify by name
            verified_id = client.get_collection_by_name(test_coll_name)
            if verified_id == coll_id:
                logging.info(f"Main test: Verification for '{test_coll_name}' by name successful.")
            else:
                logging.error(
                    f"Main test: Verification for '{test_coll_name}' by name failed. Expected {coll_id}, got {verified_id}"
                )
        else:
            logging.error(f"Main test: Failed to create/find collection '{test_coll_name}'.")

        # Test non-existent
        non_exist_id = client.get_collection_by_name("This Collection Definitely Does Not Exist XYZ")
        if non_exist_id is None:
            logging.info("Main test: Correctly determined non-existent collection not found.")
        else:
            logging.error(f"Main test: Incorrectly found non-existent collection with ID {non_exist_id}")
