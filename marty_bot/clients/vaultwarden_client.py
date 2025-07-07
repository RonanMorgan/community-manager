import os
import subprocess
import json
import logging
import tempfile
from typing import Optional  # Added Optional


class VaultwardenClient:
    def __init__(self, organization_id: str, session_token: str = None, server_url: str = None):
        """
        Initializes the VaultwardenClient.
        :param organization_id: The Vaultwarden Organization ID.
        :param session_token: An existing BW_SESSION token (optional).
        :param server_url: The URL of the Vaultwarden server (optional, defaults to official).
        """
        if not organization_id:
            raise ValueError("Vaultwarden organization_id must be provided.")

        self.organization_id = organization_id
        self.bw_session = session_token or os.getenv("BW_SESSION")
        self.server_url = server_url or os.getenv(
            "BW_SERVER_URL", "https://vaultwarden.services.dataforgood.fr"
        )  # Default from script

        self._configure_server()

    def _run_bw_command(
        self, command_args: list[str], input_data: str = None, capture_output: bool = True, use_session: bool = True
    ) -> subprocess.CompletedProcess:
        """
        Helper function to run a 'bw' command.
        :param command_args: A list of arguments for the 'bw' command.
        :param input_data: Optional string data to pass to the command's stdin.
        :param capture_output: Whether to capture stdout/stderr.
        :param use_session: Whether to include the --session token.
        :return: CompletedProcess object.
        """
        full_command = ["bw"] + command_args
        env = os.environ.copy()

        if use_session and self.bw_session:
            # Some commands take --session as an arg, others need it in env
            # For simplicity here, primarily assume BW_SESSION env var is picked up by bw CLI
            # or add --session if explicitly needed by a command.
            # The provided example `bw create org-collection` doesn't show --session,
            # but `bw get item` does. `bw sync` also likely needs it.
            # Let's add it for commands that might need it.
            # The bw CLI should also respect BW_SESSION env var if set.
            env["BW_SESSION"] = self.bw_session
            # Some commands like `bw get item --raw --session` need it explicitly.
            # We will add it to specific commands if required.

        logging.debug(f"Running bw command: {' '.join(full_command)}")
        if input_data:
            logging.debug(f"Input data for bw: {input_data[:200]}...")  # Log snippet of input

        process = subprocess.run(
            full_command,
            input=input_data.encode() if input_data else None,
            capture_output=capture_output,
            text=True,
            check=False,  # We will check the return code manually
            env=env,
        )

        if process.returncode != 0:
            logging.error(f"Error running bw command: {' '.join(full_command)}")
            logging.error(f"bw stdout: {process.stdout}")
            logging.error(f"bw stderr: {process.stderr}")
        return process

    def _configure_server(self):
        """Configures the Vaultwarden server URL if not already set correctly."""
        try:
            status_process = self._run_bw_command(["status"], use_session=False)  # Status doesn't need session
            if status_process.returncode == 0:
                status_data = json.loads(status_process.stdout)
                current_server_url = status_data.get("serverUrl")
                if current_server_url != self.server_url:
                    logging.info(f"Current Vaultwarden server is '{current_server_url}'.")
                    logging.info("Configuring Vaultwarden server to:")
                    logging.info(self.server_url)
                    self._run_bw_command(["logout"], use_session=False, capture_output=False)  # Logout from old server
                    config_proc = self._run_bw_command(["config", "server", self.server_url], use_session=False)
                    if config_proc.returncode != 0:
                        err_msg = f"Failed to configure Vaultwarden server URL. stderr: {config_proc.stderr}"
                        logging.error(f"Failed to configure Vaultwarden server URL to {self.server_url}.")
                        raise RuntimeError(err_msg)
                    logging.info(f"Vaultwarden server URL configured to {self.server_url}.")
                else:
                    logging.info(f"Vaultwarden server URL is already correctly set to '{self.server_url}'.")
            else:
                # This might happen if bw is not logged in at all or no server is configured yet.
                # Attempt to configure it directly.
                logging.info(
                    "Could not determine current Vaultwarden server status or not logged in. Attempting to configure server URL."
                )
                config_proc = self._run_bw_command(["config", "server", self.server_url], use_session=False)
                if config_proc.returncode != 0:
                    logging.warning(f"Failed to config server {self.server_url} (might be ok).")
                    logging.warning(f"stderr: {config_proc.stderr}")
                else:
                    logging.info(f"Vaultwarden server URL configured to {self.server_url}.")

        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse 'bw status' output: {e}. Assuming server needs configuration.")
            # Attempt to configure it directly if status parsing fails
            config_proc = self._run_bw_command(["config", "server", self.server_url], use_session=False)
            if config_proc.returncode != 0:
                logging.error(
                    f"Failed to configure Vaultwarden server URL to {self.server_url}. stderr: {config_proc.stderr}"
                )
                # raise RuntimeError(f"Failed to configure Vaultwarden server URL after status parse error. stderr: {config_proc.stderr}")
            else:
                logging.info(f"Vaultwarden server URL configured to {self.server_url} after status parse error.")
        except Exception as e:
            logging.error(f"An unexpected error occurred during server configuration: {e}")
            # raise

    def _get_session(self) -> Optional[str]:
        """
        Ensures a valid BW_SESSION is available, attempting to unlock or login if necessary.
        Relies on BW_PASSWORD environment variable if unlocking is needed.
        """
        if self.bw_session:
            # Check if the current session is valid
            # `bw unlock --check` is a good way, or `bw status`
            check_process = self._run_bw_command(["unlock", "--check", "--session", self.bw_session])
            if check_process.returncode == 0:
                logging.info("Existing BW_SESSION is valid.")
                # Sync vault after confirming session
                sync_proc = self._run_bw_command(["sync", "--session", self.bw_session])
                if sync_proc.returncode != 0:
                    logging.warning("Failed to sync vault with existing session.")
                return self.bw_session
            else:
                logging.info("Existing BW_SESSION is invalid or expired.")
                self.bw_session = None  # Clear invalid session

        # Try to unlock if no valid session
        bw_password = os.getenv("BW_PASSWORD")
        if bw_password:
            logging.info("Attempting to unlock vault using BW_PASSWORD environment variable.")
            # Create a temporary file for the password to avoid exposing it in process list
            with tempfile.NamedTemporaryFile(mode="w", delete=True) as tmp_pass_file:
                tmp_pass_file.write(bw_password)
                tmp_pass_file.flush()  # Ensure data is written to disk

                # Use BW_PASSWORD_FILE environment variable that points to this temp file
                env_unlock = os.environ.copy()
                env_unlock["BW_PASSWORD_FILE"] = tmp_pass_file.name

                unlock_process = subprocess.run(
                    ["bw", "unlock", "--raw"],  # BW_PASSWORD_FILE should be picked up
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env_unlock,
                )

            if unlock_process.returncode == 0 and unlock_process.stdout.strip():
                self.bw_session = unlock_process.stdout.strip()
                logging.info("Vault unlocked successfully. New BW_SESSION obtained.")
                os.environ["BW_SESSION"] = self.bw_session  # Make it available for subsequent direct bw calls if any

                # Sync vault after unlocking
                sync_proc = self._run_bw_command(["sync", "--session", self.bw_session])
                if sync_proc.returncode != 0:
                    logging.warning("Failed to sync vault after unlocking.")
                return self.bw_session
            else:
                logging.error(
                    f"Failed to unlock vault. stdout: {unlock_process.stdout}, stderr: {unlock_process.stderr}"
                )
                # Fall through to login attempt or failure
        else:
            logging.warning("BW_PASSWORD environment variable not set. Cannot unlock automatically.")

        # If unlock failed or no password, check status and try login (which might be interactive or fail)
        # This part is problematic for non-interactive environments.
        # For now, we assume login must be handled externally if BW_PASSWORD is not set.
        status_process = self._run_bw_command(["status"], use_session=False)
        if status_process.returncode == 0:
            status_data = json.loads(status_process.stdout)
            if status_data.get("status") == "unauthenticated":
                logging.error("Vaultwarden unauthenticated. Login required externally or via BW_PASSWORD.")
                raise RuntimeError("Login required via CLI or BW_PASSWORD env var for unlock.")
            elif status_data.get("status") == "locked":
                logging.error("Vault locked & BW_PASSWORD unlock failed/not set. Manual unlock or BW_PASSWORD needed.")
                raise RuntimeError("Vaultwarden is locked and automatic unlock failed.")

        if not self.bw_session:
            logging.error("Could not obtain BW_SESSION.")
            return None
        return self.bw_session

    def create_collection(self, collection_name: str, groups: list = None, users: list = None) -> Optional[dict]:
        """
        Creates a new collection in Vaultwarden.
        :param collection_name: The name for the new collection.
        :param groups: Optional list of group associations.
        :param users: Optional list of user associations.
        :return: The created collection object as a dictionary if successful, None otherwise.
        """
        if not self._get_session():
            logging.error("Failed to create collection: No valid Vaultwarden session.")
            return None

        collection_data = {
            "organizationId": self.organization_id,
            "name": collection_name,
            "externalId": None,  # As per example
            "groups": groups or [],
            "users": users or [],
        }

        # The jq part from the example:
        # echo '{"organizationId":"..."}' | jq ".name = \"manual test\" | .groups = [] | .organizationId=\"c9...\""
        # This implies the initial JSON is a template, and we override parts of it.
        # Our collection_data is already constructed with the correct name and orgId.

        input_json_str = json.dumps(collection_data)

        # Step 1: Encode the collection data
        encode_process = self._run_bw_command(["encode"], input_data=input_json_str, use_session=True)
        if encode_process.returncode != 0 or not encode_process.stdout:
            logging.error(f"Failed to encode collection data for '{collection_name}'. stderr: {encode_process.stderr}")
            return None

        encoded_data = encode_process.stdout.strip()
        logging.debug(f"Encoded data for collection '{collection_name}': {encoded_data}")

        # Step 2: Create the organization collection with the encoded data
        # Command: bw create org-collection --organizationid <org_id> --pretty
        # It expects the encoded data via stdin.
        create_args = [
            "create",
            "org-collection",
            "--organizationid",
            self.organization_id,
            # "--pretty" # Optional, for human-readable output if needed, but parsing raw is safer
        ]

        create_process = self._run_bw_command(create_args, input_data=encoded_data, use_session=True)

        if create_process.returncode == 0 and create_process.stdout:
            try:
                created_collection_info = json.loads(create_process.stdout)
                logging.info(
                    f"BW Coll '{collection_name}' created. ID: {created_collection_info.get('id')}"  # Shortened
                )
                return created_collection_info
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse 'bw create org-collection' JSON: {e}.")
                logging.error(f"Response: {create_process.stdout}")
                # Sometimes bw might output non-JSON success messages. If creation is confirmed by other means, this might be okay.
                # For now, strict parsing. If bw create returns non-json on success, need to adapt.
                # The example shows --pretty, which might be an issue. Removing --pretty for safer JSON.
                return {
                    "raw_output": create_process.stdout,
                    "message": "Collection likely created, but output was not JSON.",
                }  # Fallback
        else:
            logging.error(f"Failed to create BW coll '{collection_name}'.")  # Shortened
            logging.error(f"stderr: {create_process.stderr}")
            logging.error(f"stdout: {create_process.stdout}")
            return None
