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
        text = text[:64].strip(
            "-"
        )  # Re-strip if truncation creates leading/trailing hyphen

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
            raise ValueError(
                "Mattermost base_url, token, and team_id must be provided."
            )
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
            logging.info(
                f"MattermostClient: Bot User ID initialized to {self.bot_user_id}"
            )
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
        logging.debug(
            f"Mattermost API >> Getting current user (bot) details from {api_url}"
        )
        try:
            response = requests.get(api_url, headers=self.headers)
            response.raise_for_status()
            user_data = response.json()
            logging.info(
                f"Successfully fetched bot's user details. Bot User ID: {user_data.get('id')}"
            )
            return user_data
        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error fetching bot user details: {e.response.status_code} - {e.response.text}"
            )
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
        logging.debug(
            f"Mattermost API >> Posting to channel {channel_id}: {json.dumps(payload)}"
        )
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
            logging.error(
                f"Request exception during Mattermost post to channel {channel_id}: {e}"
            )
            return False
        except (
            json.JSONDecodeError
        ) as e:  # Should not happen on success, but good practice
            logging.error(
                f"Error decoding JSON from post message response to channel {channel_id}: {e}"
            )
            return False

    def create_channel(
        self, project_name: str, channel_type: str = "O", team_id: str = None
    ) -> dict | None:
        """
        Creates a new channel in Mattermost.
        :param project_name: The display name for the new channel. Will be slugified for the URL-safe name.
        :param channel_type: Type of the channel. 'O' for public, 'P' for private. Defaults to 'O'.
        :param team_id: Optional. If provided, overrides the default team_id set during client initialization.
        :return: The created channel data as a dictionary if successful, None otherwise.
        """
        current_team_id = team_id or self.team_id
        if not current_team_id:
            logging.error("Mattermost Team ID is not available for channel creation.")
            return None

        if channel_type not in ["O", "P"]:
            logging.error(
                f"Invalid channel_type '{channel_type}'. Must be 'O' (public) or 'P' (private)."
            )
            return None

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
                f"(name: {created_channel.get('name')}, type: {created_channel.get('type')}) created successfully on team "
                f"{current_team_id}. Channel ID: {created_channel.get('id')}"
            )
            logging.info(log_msg)
            return created_channel  # Return the channel data
        except requests.exceptions.HTTPError as e:
            error_message = (
                f"HTTP error creating Mattermost channel '{project_name}' (slug: {channel_name_slug}, type: {channel_type}) "
                f"on team {current_team_id}: {e.response.status_code} - {e.response.text}"
            )
            try:
                error_details = e.response.json()
                if (
                    error_details.get("id")
                    == "store.sql_channel.save_channel.exists.app_error"
                ):
                    logging.warning(
                        f"Channel '{project_name}' (slug: {channel_name_slug}) already exists on team {current_team_id}."
                    )  # Log as warning
                    # Attempt to fetch the existing channel by name if it exists
                    existing_channel = self.get_channel_by_name(
                        current_team_id, channel_name_slug
                    )
                    if existing_channel:
                        logging.info(
                            f"Returning existing channel data for '{channel_name_slug}'. ID: {existing_channel.get('id')}"
                        )
                        return existing_channel  # Return existing channel data
                    error_message += " (Hint: Channel with this name/display name might already exist.)"
                elif (
                    error_details.get("id")
                    == "api.channel.create_channel.invalid_name.app_error"
                ):
                    error_message += f" (Hint: The generated channel name '{channel_name_slug}' is invalid.)"
            except json.JSONDecodeError:
                pass  # No JSON in error response
            logging.error(error_message)
            return None
        except requests.exceptions.RequestException as e:
            logging.error(
                f"Request exception during Mattermost channel creation for '{project_name}': {e}"
            )
            return None
        except (
            json.JSONDecodeError
        ) as e:  # In case response.json() fails on success (unlikely for 201)
            logging.error(
                f"Error decoding JSON from Mattermost channel creation response for '{project_name}': {e}"
            )
            return None

    def get_channel_by_name(self, team_id: str, channel_name: str) -> dict | None:
        """Fetches a Mattermost channel by its URL-safe name (slug) within a given team_id."""
        if not self.base_url or not self.token:
            logging.error("Mattermost client not configured (URL or Token missing).")
            return None
        if not team_id or not channel_name:
            logging.error("Team ID and Channel Name must be provided.")
            return None

        # channel_name here should be the URL-safe name (slug), not the display name.
        url = f"{self.base_url}/api/v4/teams/{team_id}/channels/name/{channel_name}"

        logging.debug(
            f"Fetching Mattermost channel by name '{channel_name}' in team '{team_id}' from {url}"
        )
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            channel_data = response.json()
            logging.info(
                f"Successfully fetched channel '{channel_name}' (ID: {channel_data.get('id')})."
            )
            return channel_data
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logging.warning(
                    f"Mattermost channel '{channel_name}' not found in team '{team_id}'."
                )
                return None
            logging.error(
                f"HTTP error fetching channel '{channel_name}': {e.response.status_code} - {e.response.text}"
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching Mattermost channel '{channel_name}': {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(
                f"Error decoding JSON from Mattermost channel response ({url}): {e}"
            )
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

        logging.debug(
            f"Fetching users in Mattermost channel '{channel_id}' (page size: {per_page})"
        )
        while True:
            url = f"{self.base_url}/api/v4/users?in_channel={channel_id}&page={page}&per_page={per_page}"
            logging.debug(
                f"Fetching page {page} of users for channel '{channel_id}' from {url}."
            )
            try:
                response = requests.get(url, headers=self.headers)
                response.raise_for_status()
                users_page = response.json()

                if (
                    not users_page
                ):  # No more users on this page, or an empty list was returned.
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
                logging.error(
                    f"Error fetching users for Mattermost channel '{channel_id}' (page {page}): {e}"
                )
                return []
            except json.JSONDecodeError as e:
                error_msg = (  # noqa: E501
                    f"Error decoding JSON from Mattermost users response "
                    f"(channel {channel_id}, page {page}): {e}"  # noqa: E501
                )
                logging.error(error_msg)
                return []

        logging.info(
            f"Successfully fetched {len(all_users)} users from channel '{channel_id}'."
        )
        return all_users

    def create_direct_channel(self, other_user_id: str) -> str | None:
        """
        Creates a direct message (DM) channel between the bot and another user.
        Corresponds to Mattermost API: POST /api/v4/channels/direct
        :param other_user_id: The user ID of the other participant in the DM channel.
        :return: The ID of the DM channel if successful, None otherwise.
        """
        if not self.bot_user_id:
            logging.error(
                "Cannot create direct channel: Bot User ID is not initialized."
            )
            return None
        if not other_user_id:
            logging.error(
                "Cannot create direct channel: Other user ID is not provided."
            )
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
            logging.error(
                f"Request exception creating direct channel with user '{other_user_id}': {e}"
            )
            return None
        except json.JSONDecodeError as e:
            logging.error(
                f"Error decoding JSON from create direct channel response with user '{other_user_id}': {e}"
            )
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
            logging.error(
                f"Failed to create/get DM channel with user '{user_id}'. Cannot send DM."
            )
            return False

        # 2. Post the message to the DM channel
        logging.info(f"Sending DM to user '{user_id}' (channel ID: {dm_channel_id}).")
        return self.post_message(channel_id=dm_channel_id, message=message)

    def add_user_to_channel(self, channel_id: str, user_id: str) -> bool:
        """
        Adds a user to a specific channel.
        Corresponds to Mattermost API: POST /api/v4/channels/{channel_id}/members
        :param channel_id: The ID of the channel to add the user to.
        :param user_id: The ID of the user to add.
        :return: True if successful, False otherwise.
        """
        if not channel_id or not user_id:
            logging.error(
                "Channel ID and User ID must be provided to add user to channel."
            )
            return False

        api_url = f"{self.base_url}/api/v4/channels/{channel_id}/members"
        payload = {"user_id": user_id}

        logging.debug(
            f"Mattermost API >> Adding user {user_id} to channel {channel_id}: {json.dumps(payload)}"
        )
        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()  # Check for HTTP errors (201 Created is success)
            logging.info(f"User {user_id} successfully added to channel {channel_id}.")
            return True
        except requests.exceptions.HTTPError as e:
            # Handle cases like user already in channel (often a 500 error with specific message)
            # or other permission/not found errors.
            error_message = (
                f"HTTP error adding user {user_id} to channel {channel_id}: "
                f"{e.response.status_code} - {e.response.text}"
            )
            try:
                error_details = e.response.json()
                if (
                    error_details.get("id")
                    == "api.channel.add_user.already_member.app_error"
                ):
                    logging.info(
                        f"User {user_id} is already a member of channel {channel_id}. Considered success."
                    )
                    return True  # Or a more specific status if needed
            except json.JSONDecodeError:
                pass  # No JSON in error response
            logging.error(error_message)
            return False
        except requests.exceptions.RequestException as e:
            logging.error(
                f"Request exception adding user {user_id} to channel {channel_id}: {e}"
            )
            return False
        except (
            json.JSONDecodeError
        ) as e:  # Should not happen on success, but good practice
            logging.error(
                f"Error decoding JSON from add user to channel response for channel {channel_id}: {e}"
            )
            return False

    def get_channels_for_team(self, team_id: str = None) -> list[dict]:
        """
        Fetches all public and private channels for a given team_id.
        Corresponds to Mattermost API: GET /api/v4/teams/{team_id}/channels
        (Note: This endpoint typically returns public channels. For private channels,
         additional permissions or a different endpoint might be needed if the bot
         is not already a member. For simplicity, this fetches what's available via this route.)
        :param team_id: Optional. The ID of the team. If None, uses the client's default team_id.
        :return: A list of channel objects (dictionaries) if successful, an empty list otherwise.
        """
        current_team_id = team_id or self.team_id
        if not current_team_id:
            logging.error("Mattermost Team ID is not available for fetching channels.")
            return []

        all_channels = {}  # Use a dict to store channels by ID to avoid duplicates

        # API endpoint for private channels
        api_url_private = (
            f"{self.base_url}/api/v4/teams/{current_team_id}/channels/private"
        )
        # API endpoint for public channels
        api_url_public = f"{self.base_url}/api/v4/teams/{current_team_id}/channels"

        urls_to_fetch = {
            "private": api_url_private,
            "public": api_url_public,
        }

        for channel_type, api_url in urls_to_fetch.items():
            # For full robustness, pagination handling (page, per_page) would be needed here too.
            # For now, fetching the default first page (usually up to 60-200 channels).
            logging.debug(
                f"Mattermost API >> Fetching {channel_type} channels for team {current_team_id} from {api_url}"
            )
            try:
                response = requests.get(api_url, headers=self.headers)
                response.raise_for_status()
                channels_data = response.json()
                logging.debug(
                    f"{channel_type} channels_data: {channels_data} from {api_url}"
                )

                if isinstance(channels_data, list):
                    for channel in channels_data:
                        if channel.get("id"):  # Ensure channel has an ID
                            all_channels[channel["id"]] = (
                                channel  # Add/update channel in dict
                            )
                    logging.info(
                        f"Successfully fetched {len(channels_data)} {channel_type} channels for team {current_team_id}."
                    )
                else:
                    logging.error(
                        f"Unexpected response format when fetching {channel_type} channels for team {current_team_id}: {channels_data}"
                    )
            except requests.exceptions.HTTPError as e:
                # Log non-404 errors, as a 404 might just mean no channels of that type or team not found
                if e.response.status_code == 404:
                    logging.warning(
                        f"Mattermost API >> No {channel_type} channels found or team {current_team_id} not found (404) from {api_url}."
                    )
                elif e.response.status_code == 403:
                    logging.warning(
                        f"Mattermost API >> Permission denied (403) when fetching {channel_type} channels from {api_url}. "
                        "The bot might not have permissions to list these channels."
                    )
                else:
                    logging.error(
                        f"HTTP error fetching {channel_type} channels for team {current_team_id} from {api_url}: "
                        f"{e.response.status_code} - {e.response.text}"
                    )
            except requests.exceptions.RequestException as e:
                logging.error(
                    f"Request exception fetching {channel_type} channels for team {current_team_id} from {api_url}: {e}"
                )
            except json.JSONDecodeError as e:
                logging.error(
                    f"Error decoding JSON from {channel_type} channels response for team {current_team_id} from {api_url}: {e}"
                )

        final_channel_list = list(all_channels.values())
        logging.info(
            f"Total unique channels fetched for team {current_team_id}: {len(final_channel_list)}"
        )
        return final_channel_list

    def get_channel_by_id(self, channel_id: str) -> dict | None:
        """Fetches a Mattermost channel by its ID."""
        if not channel_id:
            logging.error("Channel ID must be provided.")
            return None

        url = f"{self.base_url}/api/v4/channels/{channel_id}"
        logging.debug(f"Fetching Mattermost channel by ID '{channel_id}' from {url}")
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            channel_data = response.json()
            logging.info(
                f"Successfully fetched channel ID '{channel_id}' (Name: {channel_data.get('name')})."
            )
            return channel_data
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logging.warning(f"Mattermost channel with ID '{channel_id}' not found.")
            else:
                logging.error(
                    f"HTTP error fetching channel ID '{channel_id}': {e.response.status_code} - {e.response.text}"
                )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching Mattermost channel ID '{channel_id}': {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(
                f"Error decoding JSON from Mattermost channel response (ID: {channel_id}): {e}"
            )
            return None

    def get_user_roles(self, user_id: str) -> list[str]:
        """
        Fetches the roles of a specific user by their ID.
        Corresponds to Mattermost API: GET /api/v4/users/{user_id}
        :param user_id: The ID of the user.
        :return: A list of role names (e.g., ['system_user', 'system_admin']) if successful,
                 an empty list otherwise or if the user has no roles string.
        """
        if not user_id:
            logging.error("User ID must be provided to fetch user roles.")
            return []

        api_url = f"{self.base_url}/api/v4/users/{user_id}"
        logging.debug(
            f"Mattermost API >> Getting user roles for user_id {user_id} from {api_url}"
        )
        try:
            response = requests.get(api_url, headers=self.headers)
            response.raise_for_status()
            user_data = response.json()
            roles_str = user_data.get("roles")
            if roles_str:
                # Roles are space-separated, e.g., "system_user system_admin"
                roles_list = roles_str.split(" ")
                logging.info(
                    f"Successfully fetched roles for user {user_id}: {roles_list}"
                )
                return roles_list
            else:
                logging.info(
                    f"User {user_id} has no 'roles' string in their data or it's empty."
                )
                return []  # Return empty list if roles string is missing or empty
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logging.warning(
                    f"User with ID '{user_id}' not found when fetching roles."
                )
            else:
                logging.error(
                    f"HTTP error fetching user roles for {user_id}: {e.response.status_code} - {e.response.text}"
                )
            return []
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception fetching user roles for {user_id}: {e}")
            return []
        except json.JSONDecodeError as e:
            logging.error(
                f"Error decoding JSON from user roles response for {user_id}: {e}"
            )
            return []


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
    test_channel_name_slug = os.getenv(
        "MATTERMOST_TEST_CHANNEL_SLUG", "town-square"
    )  # Default to town-square

    if not mm_url_env or not mm_bot_token_env or not mm_team_id_env:
        logging.error(
            "Please set MATTERMOST_URL, BOT_TOKEN, and MATTERMOST_TEAM_ID "
            "environment variables for this example."
        )
    else:
        logging.info(
            f"Attempting to connect to Mattermost at {mm_url_env} for team {mm_team_id_env} using Bot Token"
        )
        try:
            client = MattermostClient(
                base_url=mm_url_env, token=mm_bot_token_env, team_id=mm_team_id_env
            )

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
                logging.info(
                    f"\nAttempting to fetch users in channel ID: '{channel_id_for_users}'"
                )
                users = client.get_users_in_channel(channel_id_for_users)
                if users:
                    logging.info(
                        f"Found {len(users)} users in channel '{test_channel_name_slug}'. First few users:"
                    )
                    for i, user in enumerate(users[:3]):  # Print first 3 users
                        logging.info(
                            f"  User {i+1}: ID={user.get('id')}, Username={user.get('username')}, Email={user.get('email')}"
                        )
                else:
                    logging.info(
                        f"No users found in channel '{test_channel_name_slug}' or an error occurred."
                    )
            else:
                logging.warning(
                    f"Could not fetch channel '{test_channel_name_slug}' to test fetching users."
                )

            # Test create_channel (optional, can be commented out)
            # project_to_create = "Test MM Client Script Channel"
            # logging.info(f"\nAttempting to create Mattermost channel: '{project_to_create}' using default team ID.")
            # success_create = client.create_channel(project_to_create)
            # logging.info(f"Mattermost channel creation success: {success_create}")

        except ValueError as ve:
            logging.error(f"Configuration error: {ve}")
        except Exception as e:
            logging.error(
                f"An unexpected error occurred in __main__: {e}", exc_info=True
            )
