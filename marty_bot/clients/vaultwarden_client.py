import json
import logging
import os
import subprocess
from enum import Enum

import requests


class VaultwardenAction(Enum):
    USER_INVITED_TO_COLLECTION = "USER_INVITED_TO_VW_COLLECTION"
    USER_INVITED_TO_COLLECTION_AND_DM_SENT = "USER_INVITED_TO_VW_COLLECTION_AND_DM_SENT"
    USER_INVITED_TO_COLLECTION_DM_FAILED = "USER_INVITED_TO_VW_COLLECTION_DM_FAILED"
    USER_INVITED_TO_COLLECTION_DM_SKIPPED_NO_URL = "USER_INVITED_TO_VW_COLLECTION_DM_SKIPPED_NO_URL"
    USER_INVITED_TO_COLLECTION_DM_SKIPPED_NO_MM_USER_ID = "USER_INVITED_TO_VW_COLLECTION_DM_SKIPPED_NO_MM_USER_ID"
    FAILED_TO_INVITE_TO_COLLECTION = "FAILED_TO_INVITE_TO_VW_COLLECTION"
    USER_REMOVED_FROM_COLLECTION = "USER_REMOVED_FROM_VAULTWARDEN_COLLECTION"
    FAILED_TO_REMOVE_FROM_COLLECTION = "FAILED_TO_REMOVE_FROM_VAULTWARDEN_COLLECTION"


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
            logging.warning(
                "Vaultwarden server_url not provided. CLI might work if pre-configured, but API calls will likely fail or use a default."
            )

        self.organization_id = organization_id
        self.server_url = server_url
        self.api_username = api_username
        self.api_password = api_password
        self.bw_session = os.getenv("BW_SESSION")

        # self._ensure_server_configuration() # REMOVED: This call is too aggressive.

    def _get_api_token(self) -> str | None:
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
            "client_id": "w",
            "deviceIdentifier": "2eb66678-b76e-4940-93cd-633d5e66e42f",
            "deviceName": "firefoxeb",
            "deviceType": "10",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            logging.debug(f"Requesting API token from {token_url} for user {self.api_username}")
            response = requests.post(token_url, data=payload, headers=headers)
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get("access_token")
            if access_token:
                logging.info(f"Successfully obtained API token for user {self.api_username}.")
                return access_token
            else:
                logging.error(f"Failed to get access_token from response. Data: {token_data}")
                return None
        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error obtaining API token: {e}. Response: {e.response.text if e.response else 'No response text'}"
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request error obtaining API token: {e}")
            return None
        except json.JSONDecodeError:
            logging.error(
                f"Failed to decode JSON response from token endpoint: {response.text if 'response' in locals() else 'No response object'}"
            )
            return None

    def invite_user_to_collection(
        self,
        user_email: str,
        collection_id: str,
        organization_id: str,
        access_token: str,
    ) -> bool:
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
            "permissions": {"response": None},
            "type": 2,
            "groups": [],
            "accessSecretsManager": False,
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        try:
            logging.info(f"Inviting user {user_email} to collection {collection_id} in organization {organization_id}")
            response = requests.post(invite_url, json=payload, headers=headers)
            response.raise_for_status()
            logging.info(
                f"Successfully sent invitation for {user_email} to collection {collection_id}. Status: {response.status_code}"
            )
            return True
        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error inviting user {user_email} to collection {collection_id}: {e}. "
                f"Status: {e.response.status_code if e.response else 'N/A'}. "
                f"Response: {e.response.text if e.response else 'No response text.'}"
            )

            is_idempotent_condition_met = False
            if e.response is not None and e.response.status_code == 400:
                try:
                    response_data = e.response.json()
                    error_model_message = response_data.get("errorModel", {}).get("message", "").lower()
                    # Changed to "ValidationErrors" to match typical API casing and test mock
                    validation_errors = response_data.get("ValidationErrors", {})

                    already_member_messages = [
                        "already a member",
                        "user already invited",
                        "is already a member",
                        "already in this collection",
                        "user is already confirmed",
                    ]

                    if any(phrase in error_model_message for phrase in already_member_messages):
                        logging.warning(
                            f"User {user_email} is already a member of/invited to collection {collection_id} (or confirmed via errorModel). Treating as success."
                        )
                        is_idempotent_condition_met = True

                    if not is_idempotent_condition_met:
                        for error_list in validation_errors.values():
                            if isinstance(error_list, list):
                                for err_msg in error_list:
                                    if any(phrase in err_msg.lower() for phrase in already_member_messages):
                                        logging.warning(
                                            f"User {user_email} is already a member of/invited to collection {collection_id} (or confirmed via validationErrors). Treating as success."
                                        )
                                        is_idempotent_condition_met = True
                                        break
                            if is_idempotent_condition_met:
                                break
                except json.JSONDecodeError:
                    logging.warning(
                        f"Could not parse JSON from 400 error response when inviting {user_email} to check for idempotency."
                    )
                except Exception as parse_ex:
                    logging.warning(
                        f"Unexpected error while parsing 'already member' response for {user_email}: {parse_ex}"
                    )

            if is_idempotent_condition_met:
                return True

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
            if custom_env:
                env_for_subprocess.update(custom_env)
            if self.bw_session and "BW_SESSION" not in (custom_env or {}):
                env_for_subprocess["BW_SESSION"] = self.bw_session

            logging.debug(f"Running bw command: {' '.join(['bw'] + command_parts)}")
            logging.debug(f"input_data: {input_data}")
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
        cleaned_current_url = current_server_stdout.strip()
        if "Current server URL: " in cleaned_current_url:
            cleaned_current_url = cleaned_current_url.replace("Current server URL: ", "").strip()

        expected_server_url = self.server_url.strip()

        if current_server_rc == 0 and cleaned_current_url == expected_server_url:
            logging.info(f"Vaultwarden server URL is already correctly set to {expected_server_url}.")
            return True
        elif current_server_rc != 0:
            logging.warning(
                f"Failed to get current Vaultwarden server URL (rc={current_server_rc}): {current_server_stderr.strip()}. "
                f"Proceeding to attempt configuration to {expected_server_url}."
            )
        else:
            logging.info(
                f"Current Vaultwarden server URL ('{cleaned_current_url}') does not match expected ('{expected_server_url}'). "
                "Attempting to set it."
            )
        logging.info(f"Attempting to set Vaultwarden server URL to {expected_server_url}...")
        set_rc, _, set_stderr = self._run_bw_command(
            ["config", "server", self.server_url], custom_env=env_for_config_ops
        )
        if set_rc != 0:
            logging.error(f"Failed to configure Vaultwarden server URL to {self.server_url}: {set_stderr.strip()}")
            return False
        logging.info(f"Vaultwarden server URL configured to {self.server_url}.")
        return True

    def _get_cli_status(self) -> str:
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
            logging.error("Vaultwarden CLI is unauthenticated. Manual 'bw login' required.")
            return None

        if cli_status == "unlocked" and self.bw_session:
            rc_check, _, err_check = self._run_bw_command(["unlock", "--check"])
            if rc_check == 0:
                logging.info("Existing BW_SESSION is valid and vault is unlocked.")
                return self.bw_session
            else:
                logging.warning(f"Existing BW_SESSION invalid (rc={rc_check}): {err_check.strip()}. Unlocking.")
                self.bw_session = None
                if "BW_SESSION" in os.environ:
                    del os.environ["BW_SESSION"]

        logging.info(f"CLI status is '{cli_status}'. Attempting to unlock vault.")
        bw_master_password = os.getenv("BW_PASSWORD")
        if not bw_master_password:
            logging.error("BW_PASSWORD not set. Cannot unlock Vaultwarden.")
            return None

        unlock_env_vars = os.environ.copy()
        unlock_env_vars["BW_PASSWORD"] = bw_master_password
        unlock_env_vars.pop("BW_SESSION", None)
        if "PATH" not in unlock_env_vars:
            unlock_env_vars["PATH"] = os.getenv("PATH", "")

        rc_unlock, sout_unlock, err_unlock = self._run_bw_command(
            ["unlock", "--passwordenv", "BW_PASSWORD", "--raw"],
            custom_env=unlock_env_vars,
        )
        new_session_key = sout_unlock.strip()
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
            logging.error("Cannot sync vault: No active BW_SESSION.")
            return False
        logging.info("Syncing Vaultwarden local cache...")
        rc, _, stderr = self._run_bw_command(["sync"])
        if rc != 0:
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
            "groups": group_ids or [],
        }
        rc_encode, encoded_payload, err_encode = self._run_bw_command(
            ["encode"], input_data=json.dumps(collection_data)
        )
        if rc_encode != 0:
            logging.error(f"Failed to encode collection data: {err_encode.strip()}")
            return None

        rc_create, sout_create, err_create = self._run_bw_command(
            ["create", "org-collection", "--organizationid", self.organization_id],
            input_data=encoded_payload.strip(),
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
        if not self._get_session():
            logging.error("Cannot get collection by name: Failed to obtain Vaultwarden CLI session.")
            return None
        if not self._sync_vault():
            logging.warning("Vault sync failed before listing collections. Proceeding, but data might be stale.")

        logging.debug(
            f"Attempting to find Vaultwarden collection by name: '{collection_name}' using 'bw list collections'."
        )
        rc_list, sout_list, err_list = self._run_bw_command(["list", "collections"])
        if rc_list == 0:
            try:
                collections = json.loads(sout_list)
                for collection in collections:
                    if (
                        collection.get("name") == collection_name
                        and collection.get("organizationId") == self.organization_id
                    ):
                        coll_id = collection.get("id")
                        if coll_id:
                            logging.info(
                                f"Found collection '{collection_name}' with ID: {coll_id} in organization {self.organization_id}."
                            )
                            return coll_id
                        else:
                            logging.warning(f"Collection '{collection_name}' found but has no ID.")
                logging.info(
                    f"Collection '{collection_name}' not found in organization '{self.organization_id}' or user does not have access."
                )
                return None
            except json.JSONDecodeError:
                logging.error(f"Failed to parse JSON from 'bw list collections': {sout_list.strip()}")
                return None
        else:
            logging.error(f"Failed to list collections using 'bw list collections': {err_list.strip()}")
            return None

    def get_collections_details(self) -> list | None:
        access_token = self._get_api_token()
        if not access_token:
            return None

        details_url = f"{self.server_url.rstrip('/')}/api/organizations/{self.organization_id}/collections/details"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = requests.get(details_url, headers=headers)
            response.raise_for_status()
            return response.json().get("data", [])
        except requests.exceptions.RequestException as e:
            logging.error(f"Error getting collection details: {e}")
            return None

    def get_collections(self) -> tuple[int, str, str]:
        if not self._get_session():
            logging.error("Cannot get collection by name: Failed to obtain Vaultwarden CLI session.")
            return None
        if not self._sync_vault():
            logging.warning("Vault sync failed before listing collections. Proceeding, but data might be stale.")

        logging.debug("Attempting to find Vaultwarden collection by using 'bw list collections'.")

        return self._run_bw_command(["list", "org-collections", "--organizationid", self.organization_id])

    def get_members(self) -> tuple[int, str, str]:
        if not self._get_session():
            logging.error("Cannot get member: Failed to obtain Vaultwarden CLI session.")
            return None
        if not self._sync_vault():
            logging.warning("Vault sync failed before listing members. Proceeding, but data might be stale.")

        logging.debug("Attempting to find Vaultwarden collection by using 'bw list collections'.")

        return self._run_bw_command(["list", "org-members", "--organizationid", self.organization_id])

    def get_name_from_collections(self, collection_id: str, sout_list: str) -> str:
        try:
            collections = json.loads(sout_list)
            for collection in collections:
                if collection.get("id") == collection_id and collection.get("organizationId") == self.organization_id:
                    coll_name = collection.get("name")
                    if coll_name:
                        logging.info(
                            f"Found collection '{coll_name}' with ID: {coll_name} in organization {self.organization_id}."
                        )
                        return coll_name
                    else:
                        logging.warning(f"Collection '{coll_name}' found but has no ID.")
            logging.info(
                f"Collection '{collection_id}' not found in organization '{self.organization_id}' or user does not have access."
            )
            return None
        except json.JSONDecodeError:
            logging.error(f"Failed to parse JSON from 'bw list collections': {sout_list.strip()}")
            return None

    def get_email_from_members(self, user_id: str, sout_list: str) -> str:
        try:
            users = json.loads(sout_list)
            for user in users:
                if user.get("id") == user_id:
                    email = user.get("email")
                    if email:
                        logging.info(
                            f"Found user '{email}' with ID: {user_id} in organization {self.organization_id}."
                        )
                        return email
                    else:
                        logging.warning(f"User '{email}' found but has no ID.")
            logging.info(
                f"User '{user_id}' not found in organization '{self.organization_id}' or user does not have access."
            )
            return None
        except json.JSONDecodeError:
            logging.error(f"Failed to parse JSON from 'bw list collections': {sout_list.strip()}")
            return None

    def update_collection(self, collection_id: str, payload: dict) -> bool:
        access_token = self._get_api_token()
        if not access_token:
            return False

        update_url = (
            f"{self.server_url.rstrip('/')}/api/organizations/{self.organization_id}/collections/{collection_id}"
        )
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.put(update_url, json=payload, headers=headers)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logging.error(f"Error updating collection: {e}")
            return False

    def list_users(self) -> list | None:
        """
        Fetches all users from the Vaultwarden organization.
        """
        access_token = self._get_api_token()
        if not access_token:
            return None

        users_url = f"{self.server_url.rstrip('/')}/api/organizations/{self.organization_id}/users"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = requests.get(users_url, headers=headers)
            response.raise_for_status()
            return response.json().get("data", [])
        except requests.exceptions.RequestException as e:
            logging.error(f"Error getting users from organization: {e}")
            return None

    def delete_user(self, user_id: str) -> bool:
        """
        Deletes a user from the Vaultwarden organization.
        """
        access_token = self._get_api_token()
        if not access_token:
            return False

        delete_url = f"{self.server_url.rstrip('/')}/api/organizations/{self.organization_id}/users/{user_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = requests.delete(delete_url, headers=headers)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logging.error(f"Error deleting user from organization: {e}")
            return False


if __name__ == "__main__":
    log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=log_format)
    # ... (rest of __main__ block for direct testing) ...
