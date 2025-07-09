import subprocess
import json
import os
import logging
import requests # Added for API calls


class VaultwardenClient:
    def __init__(
        self,
        organization_id: str,
        server_url: str | None = None,
        api_username: str | None = None,
        api_password: str | None = None,
    ):
        """
        Initializes the VaultwardenClient.
        Relies on 'bw login' having been performed manually in the environment for CLI operations,
        and uses BW_PASSWORD environment variable for 'bw unlock'.
        API operations use api_username and api_password.

        :param organization_id: The ID of the organization in Vaultwarden.
        :param server_url: The URL of the Vaultwarden server. If None, it's assumed 'bw config server' was already run for CLI.
                           For API calls, this should be the base URL like https://vaultwarden.services.dataforgood.fr.
        :param api_username: Username (email) for Vaultwarden API authentication.
        :param api_password: Password for Vaultwarden API authentication.
        """
        if not organization_id:
            raise ValueError("Vaultwarden organization_id must be provided.")
        if not server_url:
            # While server_url is optional for CLI if pre-configured, it's essential for API calls.
            # We might want to make it mandatory if API calls are a core function.
            # For now, allow it to be None but API calls will fail if it's not the correct API base URL.
            logging.warning(
                "Vaultwarden server_url not provided. CLI might work if pre-configured, but API calls will likely fail or use a default."
            )

        self.organization_id = organization_id
        self.server_url = server_url  # Used by CLI and as base for API calls
        self.api_username = api_username
        self.api_password = api_password
        self.bw_session = os.getenv("BW_SESSION")  # Current session key for CLI

        # self._ensure_server_configuration() # REMOVED: This call is too aggressive.

    def _get_api_token(self) -> str | None:
        """
        Fetches an API access token from Vaultwarden.
        Uses self.api_username and self.api_password.
        The self.server_url must be the base URL of the Vaultwarden instance (e.g., https://vaultwarden.services.dataforgood.fr).
        """
        if not self.api_username or not self.api_password:
            logging.error("Vaultwarden API username or password not configured. Cannot get API token.")
            return None
        if not self.server_url:
            logging.error("Vaultwarden server URL not configured. Cannot determine token endpoint.")
            return None

        token_url = f"{self.server_url.rstrip('/')}/identity/connect/token"
        payload = {
            "grant_type": "password",
            "username": self.api_username,
            "password": self.api_password,
            "scope": "api offline_access",
            "client_id": "web", # As per example, 'w' might be an alias for 'web' or a specific client
            "deviceIdentifier": "2eb66678-b76e-4940-93cd-633d5e66e42f", # Static as per instructions
            "deviceName": "firefoxeb", # Static
            "deviceType": "10", # Static
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            logging.debug(f"Requesting API token from {token_url} for user {self.api_username}")
            response = requests.post(token_url, data=payload, headers=headers)
            response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)

            token_data = response.json()
            access_token = token_data.get("access_token")
            if access_token:
                logging.info(f"Successfully obtained API token for user {self.api_username}.")
                return access_token
            else:
                logging.error(f"Failed to get access_token from response. Data: {token_data}")
                return None
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP error obtaining API token: {e}. Response: {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request error obtaining API token: {e}")
            return None
        except json.JSONDecodeError:
            logging.error(f"Failed to decode JSON response from token endpoint: {response.text}")
            return None

    def invite_user_to_collection(
        self, user_email: str, collection_id: str, organization_id: str, access_token: str
    ) -> bool:
        """
        Invites a user to a specific collection via the Vaultwarden API.
        The self.server_url must be the base URL of the Vaultwarden instance.
        """
        if not self.server_url:
            logging.error("Vaultwarden server URL not configured. Cannot determine invite endpoint.")
            return False

        invite_url = f"{self.server_url.rstrip('/')}/api/organizations/{organization_id}/users/invite"
        payload = {
            "emails": [user_email],
            "collections": [
                {
                    "id": collection_id,
                    "readOnly": True,
                    "hidePasswords": False,
                    "manage": False,
                }
            ],
            "permissions": {"response": None}, # As per example
            "type": 2, # User type: 2 for regular user, as per example
            "groups": [], # As per example
            "accessSecretsManager": False, # As per example
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        try:
            logging.info(f"Inviting user {user_email} to collection {collection_id} in organization {organization_id}")
            response = requests.post(invite_url, json=payload, headers=headers)
            response.raise_for_status()
            # Typically, a 200 OK or 204 No Content indicates success for this type of operation.
            # The example doesn't specify the exact success code, so we'll assume raise_for_status is sufficient.
            logging.info(f"Successfully sent invitation for {user_email} to collection {collection_id}. Status: {response.status_code}")
            return True
        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error inviting user {user_email} to collection {collection_id}: {e}. Response: {e.response.text}"
            )
            # Specific check for user already invited or member, which might not be an "error" for idempotency
            if response.status_code == 400: # Example: Bitwarden API often returns 400 for such cases
                response_data = {}
                try:
                    response_data = response.json()
                except json.JSONDecodeError:
                    pass # Ignore if response is not JSON

                # Attempt to check for common messages indicating user is already part of the collection or invited
                # This is highly dependent on the actual API error messages.
                # Example: response_data.get("message", "").lower().contains("already a member")
                # For now, just log it. If this needs to be idempotent, more checks are needed here.
                logging.warning(f"User {user_email} might already be invited/member of collection {collection_id}. API response: {response.text}")
                # Consider returning True if "already member/invited" to make the operation idempotent.
                # For now, sticking to False on HTTPError unless it's a clear success.
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Request error inviting user {user_email} to collection {collection_id}: {e}")
            return False

    def _run_bw_command(
        self,
        command_parts: list[str],
        input_data: str | None = None,
        capture_output: bool = True,
        custom_env: dict | None = None,
    ) -> tuple[int, str, str]:
        try:
            env_for_subprocess = os.environ.copy()

            # Start with a base environment (copy of current os.environ)
            # Update it with custom_env if provided (custom_env takes precedence for its keys)
            if custom_env:
                env_for_subprocess.update(custom_env)

            # Ensure BW_SESSION from self.bw_session is used if set and not overridden by custom_env
            # This is important for commands that need the active session.
            # If custom_env explicitly sets BW_SESSION (e.g. to None or a different value), that will be used.
            # If custom_env does not set BW_SESSION, then self.bw_session (if any) is used.
            if self.bw_session and "BW_SESSION" not in (custom_env or {}):
                env_for_subprocess["BW_SESSION"] = self.bw_session
            elif "BW_SESSION" not in (custom_env or {}) and "BW_SESSION" in env_for_subprocess:
                # If no self.bw_session and custom_env doesn't set it, ensure any ambient BW_SESSION from os.environ is cleared
                # unless it's intentionally part of a custom_env.
                # This case is tricky: should ambient os.environ["BW_SESSION"] be used if self.bw_session is None?
                # For most commands, if self.bw_session is None, we don't want an old ambient session to interfere.
                # Specific commands like unlock might provide their own custom_env that explicitly sets/unsets BW_SESSION.
                # Let's assume for now: if self.bw_session is None, and custom_env doesn't define BW_SESSION,
                # then BW_SESSION should not be in env_for_subprocess unless it came from os.environ.copy()
                # and was *not* meant to be an active session key (e.g. for `bw unlock --passwordenv`).
                # The current logic is fine: custom_env overrides, then self.bw_session if not in custom_env.
                pass

            logging.debug(f"Running bw command: {' '.join(['bw'] + command_parts)}")            
            logging.debug(f"input_data: { input_data }")

            process = subprocess.run(
                ["bw"] + command_parts,
                input=input_data,
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

    def _ensure_server_configuration(self) -> bool:
        if not self.server_url:
            logging.debug("No server_url provided to VaultwardenClient, skipping server configuration check.")
            return True

        env_for_config_ops = os.environ.copy()
        env_for_config_ops.pop("BW_SESSION", None)
        if "PATH" not in env_for_config_ops:
            env_for_config_ops["PATH"] = os.getenv("PATH", "")

        current_server_rc, current_server_stdout, current_server_stderr = self._run_bw_command(
            ["config", "server"], custom_env=env_for_config_ops
        )

        # Clean the output, as `bw config server` might return "Current server URL: <url>"
        # or just "<url>" or might be empty or have error messages.
        cleaned_current_url = current_server_stdout.strip()
        if "Current server URL: " in cleaned_current_url: # Handle verbose output
            cleaned_current_url = cleaned_current_url.replace("Current server URL: ", "").strip()

        # Ensure self.server_url is also stripped for comparison
        expected_server_url = self.server_url.strip()

        if current_server_rc == 0 and cleaned_current_url == expected_server_url:
            logging.info(f"Vaultwarden server URL is already correctly set to {expected_server_url}.")
            return True
        elif current_server_rc != 0:
            logging.warning(
                f"Failed to get current Vaultwarden server URL (rc={current_server_rc}): {current_server_stderr.strip()}. "
                f"Proceeding to attempt configuration to {expected_server_url}."
            )
        else: # rc == 0 but URL does not match
             logging.info(
                f"Current Vaultwarden server URL ('{cleaned_current_url}') does not match expected ('{expected_server_url}'). "
                "Attempting to set it."
            )


        logging.info(f"Attempting to set Vaultwarden server URL to {expected_server_url}...")

        set_rc, _, set_stderr = self._run_bw_command(
            ["config", "server", self.server_url], custom_env=env_for_config_ops
        )
        if set_rc != 0:
            error_message = f"Failed to configure Vaultwarden server URL to {self.server_url}: {set_stderr.strip()}"
            logging.error(error_message)
            return False
        logging.info(f"Vaultwarden server URL configured to {self.server_url}.")
        return True

    def _get_cli_status(self) -> str:
        # REMOVED: if not self._ensure_server_configuration():
        #     logging.error("Server configuration check failed. Cannot reliably get CLI status.")
        #     return "error"
        # CLI server configuration is now assumed to be handled by the environment.

        logging.debug("Checking Bitwarden CLI status...")
        env_for_status = os.environ.copy()
        env_for_status.pop("BW_SESSION", None)
        if "PATH" not in env_for_status:
            env_for_status["PATH"] = os.getenv("PATH", "")

        rc_status, stdout_status, stderr_status = self._run_bw_command(["status", "--raw"], custom_env=env_for_status)

        if rc_status != 0:
            logging.error(f"Failed to get Bitwarden status (rc={rc_status}): {stderr_status.strip()}")
            return "error"
        try:
            status_data = json.loads(stdout_status)
            current_status = status_data.get("status")
            if current_status in ["unauthenticated", "locked", "unlocked"]:
                logging.info(f"Bitwarden CLI status: {current_status}")
                return current_status
            else:
                logging.warning(f"Unknown Bitwarden status from CLI: '{current_status}'")
                return "error"
        except json.JSONDecodeError:
            logging.error(f"Failed to parse Bitwarden status JSON: {stdout_status.strip()}")
            return "error"

    def _get_session(self) -> str | None:
        cli_status = self._get_cli_status()

        if cli_status == "error":
            logging.error("Failed to determine CLI status. Cannot obtain session.")
            return None
        if cli_status == "unauthenticated":
            logging.error(
                "Vaultwarden CLI is unauthenticated. A manual 'bw login' is required in the bot's environment. "
                "The bot cannot proceed to get a session."
            )
            return None

        if cli_status == "unlocked" and self.bw_session:
            logging.debug(f"CLI status is 'unlocked'. Checking existing BW_SESSION: {self.bw_session[:10]}...")
            rc_check, _, err_check = self._run_bw_command(["unlock", "--check"])
            if rc_check == 0:
                logging.info("Existing BW_SESSION is valid and vault is unlocked.")
                return self.bw_session
            else:
                logging.warning(
                    f"Existing BW_SESSION is invalid or vault became locked (rc_check={rc_check}): {err_check.strip()}. "
                    "Attempting to unlock for new session key."
                )
                self.bw_session = None
                if "BW_SESSION" in os.environ:
                    del os.environ["BW_SESSION"]

        logging.info(f"CLI status is '{cli_status}'. Attempting to unlock vault to obtain/refresh session key.")

        bw_master_password = os.getenv("BW_PASSWORD")
        if not bw_master_password:
            logging.error("BW_PASSWORD environment variable (master password) is not set. Cannot unlock Vaultwarden.")
            return None

        logging.info("Attempting to unlock Vaultwarden using BW_PASSWORD (master password)...")

        unlock_env_vars = os.environ.copy()  # Start with a full copy for subprocess
        unlock_env_vars["BW_PASSWORD"] = bw_master_password
        unlock_env_vars.pop("BW_SESSION", None)  # Ensure no old session is sent for unlock command
        if "PATH" not in unlock_env_vars:
            unlock_env_vars["PATH"] = os.getenv("PATH", "")

        rc_unlock, sout_unlock, err_unlock = self._run_bw_command(
            ["unlock", "--passwordenv", "BW_PASSWORD", "--raw"],
            custom_env=unlock_env_vars,
        )
        new_session_key = sout_unlock.strip()

        logging.debug(
            f"VaultwardenClient._get_session: unlock attempt results - "
            f"rc={rc_unlock}, new_session_key='{new_session_key[:10] if new_session_key else 'EMPTY'}...', "
            f"stderr='{err_unlock.strip()}'"
        )

        if rc_unlock == 0 and new_session_key:
            logging.info("Successfully unlocked Vaultwarden and obtained new session key.")
            self.bw_session = new_session_key
            os.environ["BW_SESSION"] = self.bw_session
            return self.bw_session
        else:
            logging.error(f"Failed to unlock Vaultwarden (rc={rc_unlock}): {err_unlock.strip() or new_session_key}")
            self.bw_session = None
            if "BW_SESSION" in os.environ:
                del os.environ["BW_SESSION"]
            return None

    def _sync_vault(self) -> bool:
        if not self.bw_session:
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
        if not self._get_session():
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
        rc_encode, encoded_payload, err_encode = self._run_bw_command(
            ["encode"], input_data=json.dumps(collection_data)
        )
        if rc_encode != 0:
            logging.error(f"Failed to encode collection data: {err_encode.strip()}")
            return None

        rc_create, sout_create, err_create = self._run_bw_command(
            ["create", "org-collection", "--organizationid", self.organization_id], input_data=encoded_payload.strip()
        )
        if rc_create == 0:
            try:
                created_info = json.loads(sout_create)
                coll_id = created_info.get("id")
                if coll_id:
                    logging.info(f"Collection '{collection_name}' created/verified with ID: {coll_id}")
                    return coll_id
                else:
                    logging.error(
                        f"'bw create org-collection' for '{collection_name}' succeeded but no ID in response: {sout_create.strip()}"
                    )
                    return None
            except json.JSONDecodeError:
                logging.error(
                    f"Failed to parse JSON from 'bw create org-collection' for '{collection_name}': {sout_create.strip()}"
                )
                return None
        else:
            if "already exists" in err_create.lower():
                logging.warning(f"Collection '{collection_name}' may already exist. Attempting to find it.")
                return self.get_collection_by_name(collection_name)
            else:
                logging.error(f"Failed to create collection '{collection_name}': {err_create.strip()}")
                return None

    def get_collection_by_name(self, collection_name: str) -> str | None:
        """
        Retrieves a collection ID by its name using the `bw list collections` CLI command.
        This command lists all collections accessible to the logged-in user.
        Filters by organization_id if provided to the client.

        :param collection_name: The name of the collection to find.
        :return: The ID of the collection if found, otherwise None.
        """
        if not self._get_session(): # Ensures CLI is unlocked and session is active
            logging.error("Cannot get collection by name: Failed to obtain Vaultwarden CLI session.")
            return None

        # Sync vault to ensure local cache is up-to-date before listing
        if not self._sync_vault():
            logging.warning("Vault sync failed before listing collections. Proceeding, but data might be stale.")

        logging.debug(f"Attempting to find Vaultwarden collection by name: '{collection_name}' using 'bw list collections'.")

        # The command `bw list collections` lists all collections the user has access to.
        # We will filter this list for the matching name and organization ID.
        rc_list, sout_list, err_list = self._run_bw_command(
            ["list", "collections"]
        )

        if rc_list == 0:
            try:
                collections = json.loads(sout_list)
                for collection in collections:
                    # Check if the collection name matches and if it belongs to the target organization
                    if collection.get("name") == collection_name and collection.get("organizationId") == self.organization_id:
                        coll_id = collection.get("id")
                        if coll_id: # Ensure ID is not null or empty
                            logging.info(
                                f"Found collection '{collection_name}' with ID: {coll_id} in organization {self.organization_id}."
                            )
                            return coll_id
                        else:
                            logging.warning(f"Collection '{collection_name}' found but has no ID.")

                logging.info(
                    f"Collection '{collection_name}' not found in organization '{self.organization_id}' "
                    f"or user does not have access."
                )
                return None
            except json.JSONDecodeError:
                logging.error(f"Failed to parse JSON from 'bw list collections': {sout_list.strip()}")
                return None
        else:
            logging.error(f"Failed to list collections using 'bw list collections': {err_list.strip()}")
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
        logging.error("Please set BW_PASSWORD (master password) environment variable for testing.")
    else:
        if "BW_CLIENTID" in os.environ:
            del os.environ["BW_CLIENTID"]
        if "BW_CLIENTSECRET" in os.environ:
            del os.environ["BW_CLIENTSECRET"]

        client = VaultwardenClient(organization_id=org_id_env, server_url=vw_server_env)

        session = client._get_session()
        if session:
            logging.info(f"Main test: Successfully obtained session key: {session[:10]}...")

            test_coll_name = "MartyBot Client Test Collection (Unlock)"
            coll_id = client.create_collection(test_coll_name)
            if coll_id:
                logging.info(f"Main test: Collection '{test_coll_name}' created/found with ID: {coll_id}")
                verified_id = client.get_collection_by_name(test_coll_name)
                if verified_id == coll_id:
                    logging.info(f"Main test: Verification for '{test_coll_name}' by name successful.")
                else:
                    logging.error(f"Main test: Verification failed. Expected {coll_id}, got {verified_id}")
            else:
                logging.error(f"Main test: Failed to create/find collection '{test_coll_name}'.")
        else:
            logging.error("Main test: Failed to obtain session. Collection test skipped.")
            logging.error(
                "Reminder: For this test to fully pass if CLI is unauthenticated, a manual 'bw login' is needed in the environment first."
            )

        non_exist_id = client.get_collection_by_name("This Collection Definitely Does Not Exist XYZ")
        if non_exist_id is None:
            logging.info("Main test: Correctly determined non-existent collection not found (or session failed).")
        else:
            logging.error(f"Main test: Incorrectly found non-existent collection with ID {non_exist_id}")
