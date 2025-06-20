import requests
import json
import re

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

    if not text or text == "-":  # Also handle if the slug becomes just a hyphen after stripping # noqa: E501
        return "default-channel-name"
    return text


class MattermostClient:
    def __init__(self, base_url: str, token: str, team_id: str):
        """
        Initializes the MattermostClient.
        :param base_url: The base URL of the Mattermost instance (e.g., http://localhost:8065).
        :param token: The API token (Personal Access Token of a bot/admin) for Mattermost operations.
        :param team_id: The default Mattermost Team ID to use for operations like channel creation.
        """
        if not base_url or not token or not team_id:
            raise ValueError("Mattermost base_url, token, and team_id must be provided.")
        self.base_url = base_url.rstrip("/")  # Ensure no trailing slash
        self.token = token
        self.team_id = team_id  # Default team_id
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def create_channel(self, project_name: str, team_id: str = None) -> bool:
        """
        Creates a new public channel in Mattermost.
        :param project_name: The display name for the new channel. Will be slugified for the URL-safe name.
        :param team_id: Optional. If provided, overrides the default team_id set during client initialization.
        :return: True if successful, False otherwise.
        """
        current_team_id = team_id or self.team_id
        if not current_team_id:  # Should have been caught by constructor if self.team_id was the only source
            print("Error: Mattermost Team ID is not available for channel creation.")
            return False

        api_url = f"{self.base_url}/api/v4/channels"

        channel_name_slug = slugify(project_name)

        payload = {
            "team_id": current_team_id,
            "name": channel_name_slug,
            "display_name": project_name,
            "type": "O",  # "O" for public, "P" for private
            "purpose": f"Channel for project {project_name}",
            "header": f"Project {project_name}",
        }

        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            if response.status_code == 201:
                created_channel = response.json()
                print(
                    f"Mattermost channel '{created_channel.get('display_name')}' (name: {created_channel.get('name')}) created successfully on team {current_team_id}. Channel ID: {created_channel.get('id')}"  # noqa: E501
                )
                return True
            else:
                error_message = f"Error creating Mattermost channel '{project_name}' (slug: {channel_name_slug}) on team {current_team_id}: {response.status_code} - {response.text}"  # noqa: E501
                try:
                    error_details = response.json()
                    if error_details.get("id") == "store.sql_channel.save_channel.exists.app_error":
                        error_message += " (Hint: A channel with this name or display name might already exist on the team.)"  # noqa: E501
                    elif error_details.get("id") == "api.channel.create_channel.invalid_name.app_error":
                        error_message += f" (Hint: The generated channel name '{channel_name_slug}' is invalid.)"
                except json.JSONDecodeError:
                    pass
                print(error_message)
                return False
        except requests.exceptions.RequestException as e:
            print(f"Request failed for Mattermost channel creation '{project_name}': {e}")
            return False


if __name__ == "__main__":
    from dotenv import load_dotenv
    import os

    load_dotenv()

    mm_url_env = os.getenv("MATTERMOST_URL")
    mm_token_env = os.getenv("MATTERMOST_TOKEN")  # This should be the admin/bot API token
    mm_team_id_env = os.getenv("MATTERMOST_TEAM_ID")

    if not mm_url_env or not mm_token_env or not mm_team_id_env:
        print(
            "Please set MATTERMOST_URL, MATTERMOST_TOKEN, and MATTERMOST_TEAM_ID environment variables for this example."  # noqa: E501
        )
    else:
        print(f"Attempting to connect to Mattermost at {mm_url_env} for team {mm_team_id_env}")
        try:
            client = MattermostClient(base_url=mm_url_env, token=mm_token_env, team_id=mm_team_id_env)

            project_to_create = "Test MM Channel OOP"
            print(f"\nAttempting to create Mattermost channel: '{project_to_create}' using default team ID.")
            success = client.create_channel(project_to_create)
            print(f"Mattermost channel creation success: {success}")

            if success:
                print(f"\nAttempting to create Mattermost channel AGAIN: '{project_to_create}' (should fail).")
                success_again = client.create_channel(project_to_create)
                print(f"Second channel creation success: {success_again}")

            # Test with a different team ID override
            override_team_id = os.getenv("MATTERMOST_OTHER_TEAM_ID", "another_fake_team_id")
            if (
                override_team_id != "another_fake_team_id" or mm_team_id_env != "another_fake_team_id"
            ):  # only run if it's a distinct team
                project_for_other_team = "Test MM Channel Other Team OOP"
                print(
                    f"\nAttempting to create channel on specific team '{override_team_id}': '{project_for_other_team}'"
                )
                success_override = client.create_channel(project_for_other_team, team_id=override_team_id)
                print(f"Mattermost channel creation on specific team success: {success_override}")
            else:
                print(
                    "\nSkipping test for override_team_id as MATTERMOST_OTHER_TEAM_ID is not set or same as default."
                )

        except ValueError as ve:
            print(f"Configuration error: {ve}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
