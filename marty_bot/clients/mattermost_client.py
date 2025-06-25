import requests
import json
import re
import logging  # Added logging

# Removed direct import of config


def slugify(text: str) -> str:
    """
    Simple slugify function:
    - Convert to lowercase
    - Replace spaces and underscores with hyphens
    - Remove characters that are not alphanumeric or hyphens
    - Ensure it doesn't start or end with a hyphen
    - Truncate to 64 characters (Mattermost limit for channel name)
    - Return a default name if the slug becomes empty
    """
    text = str(text).lower()
    # Replace spaces and underscores with hyphens first
    text = re.sub(r"[\s_]+", "-", text)
    # Replace any sequence of non-alphanumeric characters (excluding existing hyphens) with a single hyphen
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    # Remove leading or trailing hyphens that might have been created
    text = text.strip("-")
    # Consolidate multiple hyphens (e.g., "foo---bar" to "foo-bar").
    # Note: "[^a-z0-9-]+" might create "--" from "!@#$".
    # So, an explicit consolidation step is good.
    text = re.sub(r"-+", "-", text)

    if len(text) > 64:
        text = text[:64].strip("-")  # Re-strip if truncation creates leading/trailing hyphen

    if not text or text == "-":  # Handle if slug becomes empty or just a hyphen
        return "default-channel-name"
    return text


class MattermostClient:
    def __init__(self, base_url: str, token: str, team_id: str):
        """
        Initializes the MattermostClient.
        :param base_url: The base URL of the Mattermost instance (e.g., http://localhost:8065).
        :param token: The Bot's Access Token for Mattermost API operations.
        :param team_id: The default Mattermost Team ID to use for operations like channel creation.
        """
        if not base_url or not token or not team_id:
            raise ValueError("Mattermost base_url, token, and team_id must be provided.")
        self.base_url = base_url.rstrip("/")  # Ensure no trailing slash
        self.token = token
        self.team_id = team_id  # Default team_id
        self.headers = {
            "Content-Type": "application/json",  # Good default for POST/PUT
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        self.bot_user_id: str | None = None  # Will store the bot's own user ID
        self._initialize_bot_user_id()

    def _initialize_bot_user_id(self) -> None:
        """
        Fetches and stores the bot's own user ID by calling get_me().
        Logs an error if fetching fails, as DMs will not work.
        """
        logging.debug("MattermostClient: Initializing Bot User ID...")
        user_details = self.get_me()
        if user_details and user_details.get("id"):
            self.bot_user_id = user_details["id"]
            logging.info(f"MattermostClient: Bot User ID initialized to {self.bot_user_id}")
        else:
            self.bot_user_id = None  # Ensure it's None if fetching failed
            logging.error(
                "MattermostClient: FAILED to fetch Bot User ID. Direct messaging functionality will be impaired."
            )
            # Depending on requirements, one might raise an error here if bot_user_id is critical for all operations

    def get_me(self) -> dict | None:
        """
        Fetches details for the currently authenticated user (assumed to be the bot).
        Corresponds to Mattermost API: GET /api/v4/users/me
        :return: A dictionary containing user details if successful, None otherwise.
        """
        api_url = f"{self.base_url}/api/v4/users/me"
        logging.debug(f"Mattermost API >> Getting current user (bot) details from {api_url}")
        try:
            response = requests.get(api_url, headers=self.headers)
            response.raise_for_status()
            user_data = response.json()
            logging.info(f"Successfully fetched bot's user details. Bot User ID: {user_data.get('id')}")
            return user_data
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP error fetching bot user details: {e.response.status_code} - {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception fetching bot user details: {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from bot user details response: {e}")
            return None

    def post_message(self, channel_id: str, message: str) -> bool:
        """
        Posts a message to a specific channel.
        Corresponds to Mattermost API: POST /api/v4/posts
        :param channel_id: The ID of the channel to post to (can be a public, private, or DM channel).
        :param message: The message string to post.
        :return: True if successful, False otherwise.
        """
        if not channel_id or message is None:  # message can be an empty string
            logging.error("Channel ID and message must be provided to post a message.")
            return False

        api_url = f"{self.base_url}/api/v4/posts"
        payload = {
            "channel_id": channel_id,
            "message": message,
        }
        logging.debug(f"Mattermost API >> Posting to channel {channel_id}: {json.dumps(payload)}")
        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()
            logging.info(f"Message posted successfully to channel {channel_id}.")
            return True
        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error posting to Mattermost channel {channel_id}: {e.response.status_code} - {e.response.text}"
            )
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception during Mattermost post to channel {channel_id}: {e}")
            return False
        except json.JSONDecodeError as e:  # Should not happen on success, but good practice
            logging.error(f"Error decoding JSON from post message response to channel {channel_id}: {e}")
            return False

    def create_channel(self, project_name: str, channel_type: str = "O", team_id: str = None) -> bool:
        """
        Creates a new channel in Mattermost.
        :param project_name: The display name for the new channel. Will be slugified for the URL-safe name.
        :param channel_type: Type of the channel. 'O' for public, 'P' for private. Defaults to 'O'.
        :param team_id: Optional. If provided, overrides the default team_id set during client initialization.
        :return: True if successful, False otherwise.
        """
        current_team_id = team_id or self.team_id
        if not current_team_id:
            logging.error("Mattermost Team ID is not available for channel creation.")
            return False

        if channel_type not in ["O", "P"]:
            logging.error(f"Invalid channel_type '{channel_type}'. Must be 'O' (public) or 'P' (private).")
            return False

        api_url = f"{self.base_url}/api/v4/channels"
        channel_name_slug = slugify(project_name)
        payload = {
            "team_id": current_team_id,
            "name": channel_name_slug,
            "display_name": project_name,
            "type": channel_type,
            "purpose": f"Channel for project {project_name}",
            "header": f"Project {project_name}",
        }

        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()  # Check for HTTP errors
            created_channel = response.json()
            log_msg = (
                f"Mattermost channel '{created_channel.get('display_name')}' "
                f"(name: {created_channel.get('name')}) created successfully on team "
                f"{current_team_id}. Channel ID: {created_channel.get('id')}"
            )
            logging.info(log_msg)
            return True
        except requests.exceptions.HTTPError as e:
            error_message = (
                f"HTTP error creating Mattermost channel '{project_name}' (slug: {channel_name_slug}, type: {channel_type}) "
                f"on team {current_team_id}: {e.response.status_code} - {e.response.text}"
            )
            try:
                error_details = e.response.json()
                if error_details.get("id") == "store.sql_channel.save_channel.exists.app_error":
                    error_message += " (Hint: Channel with this name/display name might already exist.)"
                elif error_details.get("id") == "api.channel.create_channel.invalid_name.app_error":
                    error_message += f" (Hint: The generated channel name '{channel_name_slug}' is invalid.)"
            except json.JSONDecodeError:
                pass  # No JSON in error response
            logging.error(error_message)
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception during Mattermost channel creation for '{project_name}': {e}")
            return False
        except json.JSONDecodeError as e:  # In case response.json() fails on success (unlikely for 201)
            logging.error(f"Error decoding JSON from Mattermost channel creation response for '{project_name}': {e}")
            return False

    def get_channel_by_name(self, team_id: str, channel_name: str):
        """Fetches a Mattermost channel by its URL-safe name (slug) within a given team_id."""
        if not self.base_url or not self.token:
            logging.error("Mattermost client not configured (URL or Token missing).")
            return None
        if not team_id or not channel_name:
            logging.error("Team ID and Channel Name must be provided.")
            return None

        # channel_name here should be the URL-safe name (slug), not the display name.
        url = f"{self.base_url}/api/v4/teams/{team_id}/channels/name/{channel_name}"

        logging.debug(f"Fetching Mattermost channel by name '{channel_name}' in team '{team_id}' from {url}")
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            channel_data = response.json()
            logging.info(f"Successfully fetched channel '{channel_name}' (ID: {channel_data.get('id')}).")
            return channel_data
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logging.warning(f"Mattermost channel '{channel_name}' not found in team '{team_id}'.")
                return None
            logging.error(
                f"HTTP error fetching channel '{channel_name}': {e.response.status_code} - {e.response.text}"
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching Mattermost channel '{channel_name}': {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from Mattermost channel response ({url}): {e}")
            return None

    def get_users_in_channel(self, channel_id: str):
        """Fetches user details for all members of a given channel_id, handling pagination."""
        if not self.base_url or not self.token:
            logging.error("Mattermost client not configured (URL or Token missing).")
            return []
        if not channel_id:
            logging.error("Channel ID must be provided to fetch users.")
            return []

        all_users = []
        page = 0
        per_page = 200  # Max users per page for Mattermost API

        logging.debug(f"Fetching users in Mattermost channel '{channel_id}' (page size: {per_page})")
        while True:
            url = f"{self.base_url}/api/v4/users?in_channel={channel_id}&page={page}&per_page={per_page}"
            logging.debug(f"Fetching page {page} of users for channel '{channel_id}' from {url}.")
            try:
                response = requests.get(url, headers=self.headers)
                response.raise_for_status()
                users_page = response.json()

                if not users_page:  # No more users on this page, or an empty list was returned.
                    break

                all_users.extend(users_page)

                if len(users_page) < per_page:  # Last page
                    break

                page += 1

            except requests.exceptions.HTTPError as e:
                error_msg = (  # noqa: E501
                    f"HTTP error fetching users for channel '{channel_id}' (page {page}): "
                    f"{e.response.status_code} - {e.response.text}"  # noqa: E501
                )
                logging.error(error_msg)
                # Depending on desired behavior, could return partial list `all_users` or empty
                return []
            except requests.exceptions.RequestException as e:
                logging.error(f"Error fetching users for Mattermost channel '{channel_id}' (page {page}): {e}")
                return []
            except json.JSONDecodeError as e:
                error_msg = (  # noqa: E501
                    f"Error decoding JSON from Mattermost users response "
                    f"(channel {channel_id}, page {page}): {e}"  # noqa: E501
                )
                logging.error(error_msg)
                return []

        logging.info(f"Successfully fetched {len(all_users)} users from channel '{channel_id}'.")
        return all_users

    def create_direct_channel(self, other_user_id: str) -> str | None:
        """
        Creates a direct message (DM) channel between the bot and another user.
        Corresponds to Mattermost API: POST /api/v4/channels/direct
        :param other_user_id: The user ID of the other participant in the DM channel.
        :return: The ID of the DM channel if successful, None otherwise.
        """
        if not self.bot_user_id:
            logging.error("Cannot create direct channel: Bot User ID is not initialized.")
            return None
        if not other_user_id:
            logging.error("Cannot create direct channel: Other user ID is not provided.")
            return None

        api_url = f"{self.base_url}/api/v4/channels/direct"
        # Payload is a list of two user IDs: [bot_id, other_user_id]
        payload = [self.bot_user_id, other_user_id]

        logging.debug(
            f"Mattermost API >> Creating direct channel with user '{other_user_id}'. Payload: {json.dumps(payload)}"
        )
        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()
            channel_data = response.json()
            dm_channel_id = channel_data.get("id")
            if dm_channel_id:
                logging.info(
                    f"Successfully created/retrieved direct channel with user '{other_user_id}'. Channel ID: {dm_channel_id}"
                )
                return dm_channel_id
            else:
                logging.error(
                    f"Failed to create/retrieve direct channel with user '{other_user_id}'. 'id' missing in response: {channel_data}"
                )
                return None
        except requests.exceptions.HTTPError as e:
            # Mattermost often returns 200 or 201 even if channel exists.
            # Specific errors like 400 for invalid user ID, 401/403 for permissions.
            logging.error(
                f"HTTP error creating direct channel with user '{other_user_id}': {e.response.status_code} - {e.response.text}"
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception creating direct channel with user '{other_user_id}': {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from create direct channel response with user '{other_user_id}': {e}")
            return None

    def send_dm(self, user_id: str, message: str) -> bool:
        """
        Sends a direct message to a specific user.
        This is a helper method that first creates/retrieves the DM channel
        and then posts the message to it.
        :param user_id: The Mattermost User ID of the recipient.
        :param message: The message string to send.
        :return: True if the DM was sent successfully, False otherwise.
        """
        if not user_id or not message:
            logging.error("User ID and message must be provided to send a DM.")
            return False

        # 1. Create/Get the direct channel
        dm_channel_id = self.create_direct_channel(user_id)
        if not dm_channel_id:
            logging.error(f"Failed to create/get DM channel with user '{user_id}'. Cannot send DM.")
            return False

        # 2. Post the message to the DM channel
        logging.info(f"Sending DM to user '{user_id}' (channel ID: {dm_channel_id}).")
        return self.post_message(channel_id=dm_channel_id, message=message)


if __name__ == "__main__":
    from dotenv import load_dotenv
    import os

    load_dotenv()
    # Setup basic logging for script direct execution
    log_format = "%(asctime)s - %(levelname)s [%(filename)s:%(lineno)d] - %(message)s"  # noqa: E501
    logging.basicConfig(level=logging.DEBUG, format=log_format)

    mm_url_env = os.getenv("MATTERMOST_URL")
    mm_bot_token_env = os.getenv("BOT_TOKEN")
    mm_team_id_env = os.getenv("MATTERMOST_TEAM_ID")
    # For testing get_channel_by_name and get_users_in_channel
    test_channel_name_slug = os.getenv("MATTERMOST_TEST_CHANNEL_SLUG", "town-square")  # Default to town-square

    if not mm_url_env or not mm_bot_token_env or not mm_team_id_env:
        logging.error(
            "Please set MATTERMOST_URL, BOT_TOKEN, and MATTERMOST_TEAM_ID " "environment variables for this example."
        )
    else:
        logging.info(f"Attempting to connect to Mattermost at {mm_url_env} for team {mm_team_id_env} using Bot Token")
        try:
            client = MattermostClient(base_url=mm_url_env, token=mm_bot_token_env, team_id=mm_team_id_env)

            # Test get_channel_by_name
            logging.info(
                f"\nAttempting to fetch channel by name: '{test_channel_name_slug}' in team '{mm_team_id_env}'"
            )
            channel = client.get_channel_by_name(mm_team_id_env, test_channel_name_slug)
            if channel:
                logging.info(
                    f"Fetched channel: ID={channel.get('id')}, Name={channel.get('name')}, DisplayName={channel.get('display_name')}"
                )

                # Test get_users_in_channel if channel was found
                channel_id_for_users = channel.get("id")
                logging.info(f"\nAttempting to fetch users in channel ID: '{channel_id_for_users}'")
                users = client.get_users_in_channel(channel_id_for_users)
                if users:
                    logging.info(f"Found {len(users)} users in channel '{test_channel_name_slug}'. First few users:")
                    for i, user in enumerate(users[:3]):  # Print first 3 users
                        logging.info(
                            f"  User {i+1}: ID={user.get('id')}, Username={user.get('username')}, Email={user.get('email')}"
                        )
                else:
                    logging.info(f"No users found in channel '{test_channel_name_slug}' or an error occurred.")
            else:
                logging.warning(f"Could not fetch channel '{test_channel_name_slug}' to test fetching users.")

            # Test create_channel (optional, can be commented out)
            # project_to_create = "Test MM Client Script Channel"
            # logging.info(f"\nAttempting to create Mattermost channel: '{project_to_create}' using default team ID.")
            # success_create = client.create_channel(project_to_create)
            # logging.info(f"Mattermost channel creation success: {success_create}")

        except ValueError as ve:
            logging.error(f"Configuration error: {ve}")
        except Exception as e:
            logging.error(f"An unexpected error occurred in __main__: {e}", exc_info=True)
