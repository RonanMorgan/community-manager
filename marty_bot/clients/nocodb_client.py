import logging
from enum import Enum

import requests


class NocoDBAction(Enum):
    USER_REMOVED_FROM_BASE = "NOCODB_USER_REMOVED_FROM_BASE"
    USER_ROLE_UPDATED_TO_OWNER = "NOCODB_USER_ROLE_UPDATED_TO_OWNER"
    USER_ROLE_UPDATED_TO_CREATOR = "NOCODB_USER_ROLE_UPDATED_TO_CREATOR"
    USER_ROLE_UPDATED_TO_EDITOR = "NOCODB_USER_ROLE_UPDATED_TO_EDITOR"
    USER_ROLE_UPDATED_TO_COMMENTER = "NOCODB_USER_ROLE_UPDATED_TO_COMMENTER"
    USER_ROLE_UPDATED_TO_VIEWER = "NOCODB_USER_ROLE_UPDATED_TO_VIEWER"
    USER_ROLE_UPDATED_TO_GUEST = "NOCODB_USER_ROLE_UPDATED_TO_GUEST"
    USER_ALREADY_IN_BASE_WITH_CORRECT_ROLE = "NOCODB_USER_ALREADY_IN_BASE_WITH_CORRECT_ROLE"
    USER_INVITED_AS_OWNER = "NOCODB_USER_INVITED_AS_OWNER"
    USER_INVITED_AS_CREATOR = "NOCODB_USER_INVITED_AS_CREATOR"
    USER_INVITED_AS_EDITOR = "NOCODB_USER_INVITED_AS_EDITOR"
    USER_INVITED_AS_COMMENTER = "NOCODB_USER_INVITED_AS_COMMENTER"
    USER_INVITED_AS_VIEWER = "NOCODB_USER_INVITED_AS_VIEWER"
    USER_INVITED_AS_GUEST = "NOCODB_USER_INVITED_AS_GUEST"
    USER_INVITED_AS_OWNER_AND_DM_SENT = "NOCODB_USER_INVITED_AS_OWNER_AND_DM_SENT"
    USER_INVITED_AS_CREATOR_AND_DM_SENT = "NOCODB_USER_INVITED_AS_CREATOR_AND_DM_SENT"
    USER_INVITED_AS_EDITOR_AND_DM_SENT = "NOCODB_USER_INVITED_AS_EDITOR_AND_DM_SENT"
    USER_INVITED_AS_COMMENTER_AND_DM_SENT = "NOCODB_USER_INVITED_AS_COMMENTER_AND_DM_SENT"
    USER_INVITED_AS_VIEWER_AND_DM_SENT = "NOCODB_USER_INVITED_AS_VIEWER_AND_DM_SENT"
    USER_INVITED_AS_GUEST_AND_DM_SENT = "NOCODB_USER_INVITED_AS_GUEST_AND_DM_SENT"
    USER_INVITED_AS_OWNER_DM_FAILED = "NOCODB_USER_INVITED_AS_OWNER_DM_FAILED"
    USER_INVITED_AS_CREATOR_DM_FAILED = "NOCODB_USER_INVITED_AS_CREATOR_DM_FAILED"
    USER_INVITED_AS_EDITOR_DM_FAILED = "NOCODB_USER_INVITED_AS_EDITOR_DM_FAILED"
    USER_INVITED_AS_COMMENTER_DM_FAILED = "NOCODB_USER_INVITED_AS_COMMENTER_DM_FAILED"
    USER_INVITED_AS_VIEWER_DM_FAILED = "NOCODB_USER_INVITED_AS_VIEWER_DM_FAILED"
    USER_INVITED_AS_GUEST_DM_FAILED = "NOCODB_USER_INVITED_AS_GUEST_DM_FAILED"
    USER_INVITED_AS_OWNER_DM_SKIPPED_NO_URL = "NOCODB_USER_INVITED_AS_OWNER_DM_SKIPPED_NO_URL"
    USER_INVITED_AS_CREATOR_DM_SKIPPED_NO_URL = "NOCODB_USER_INVITED_AS_CREATOR_DM_SKIPPED_NO_URL"
    USER_INVITED_AS_EDITOR_DM_SKIPPED_NO_URL = "NOCODB_USER_INVITED_AS_EDITOR_DM_SKIPPED_NO_URL"
    USER_INVITED_AS_COMMENTER_DM_SKIPPED_NO_URL = "NOCODB_USER_INVITED_AS_COMMENTER_DM_SKIPPED_NO_URL"
    USER_INVITED_AS_VIEWER_DM_SKIPPED_NO_URL = "NOCODB_USER_INVITED_AS_VIEWER_DM_SKIPPED_NO_URL"
    USER_INVITED_AS_GUEST_DM_SKIPPED_NO_URL = "NOCODB_USER_INVITED_AS_GUEST_DM_SKIPPED_NO_URL"
    FAILED_TO_UPDATE_NOCODB_USER_ROLE = "FAILED_TO_UPDATE_NOCODB_USER_ROLE"
    FAILED_TO_INVITE_NOCODB_USER = "FAILED_TO_INVITE_NOCODB_USER"


# Configure logging for the client
logger = logging.getLogger(__name__)


class NocoDBClient:
    def __init__(self, nocodb_url: str, token: str):
        if not nocodb_url:
            logger.error("NocoDB URL is required for NocoDBClient initialization.")
            raise ValueError("NocoDB URL is required.")
        if not token:
            logger.error("NocoDB Token is required for NocoDBClient initialization.")
            raise ValueError("NocoDB Token is required.")

        self.base_url = nocodb_url.rstrip("/")
        self.headers = {
            "xc-token": token,  # Based on NoCoDB docs, token is often passed as xc-token
            "Content-Type": "application/json",
        }
        logger.debug("NocoDBClient initialized for URL: %s", self.base_url)  # Changed to DEBUG

    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict | list | None:
        """Helper function to make requests to the NoCoDB API."""
        url = f"{self.base_url}/api/v1/db/meta/{endpoint.lstrip('/')}"
        # Removed detailed logging of headers and full JSON params from DEBUG by default,
        # as it can be very verbose and contain sensitive info if not careful.
        # Users can add it back if specific request debugging is needed.
        logger.debug(f"NoCoDB API >> Request: {method.upper()} {url}")
        if kwargs.get("json"):
            logger.debug(f"NoCoDB API >> JSON Payload: {kwargs.get('json')}")

        try:
            response = requests.request(method, url, headers=self.headers, **kwargs)
            response.raise_for_status()
            if response.content:  # Handle cases where response might be empty (e.g., 204 No Content)
                return response.json()
            return None  # Or return a specific success indicator if appropriate for empty responses
        except requests.exceptions.HTTPError as e:
            if e.response is not None:
                logger.error(
                    f"NoCoDB API << HTTP error for {method.upper()} {url}: "
                    f"{e.response.status_code} - {e.response.text}"
                )
            else:
                logger.error(f"NoCoDB API << HTTP error for {method.upper()} {url} with no response body: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"NoCoDB API << Request exception for {method.upper()} {url}: {e}")
        except ValueError as e:  # Includes JSONDecodeError
            logger.error(f"NoCoDB API << Error decoding JSON response from {method.upper()} {url}: {e}")
        return None

    def create_base(self, base_title: str, description: str = "") -> dict | None:
        """
        Creates a new base (project) in NoCoDB.
        API: POST /api/v1/db/meta/projects/
        """
        payload = {
            "title": base_title,
            "description": description,
            # "sources": [], # Default, can be customized if needed
            # "color": "#24716E" # Default color
        }
        logger.info(f"Attempting to create NoCoDB base with title: {base_title}")  # Kept as INFO
        response_data = self._make_request("post", "projects/", json=payload)
        if response_data and isinstance(response_data, dict) and response_data.get("id"):
            logger.info(
                f"Successfully created NoCoDB base '{base_title}' with ID: {response_data['id']}"
            )  # Kept as INFO
            return response_data
        logger.warning(f"Failed to create NoCoDB base '{base_title}'. Response: {response_data}")  # Kept as WARNING
        return None

    def get_base_by_title(self, base_title: str) -> dict | None:
        """
        Retrieves a specific base by its title.
        API: GET /api/v1/db/meta/projects/
        Filters locally as NoCoDB API for listing projects doesn't seem to have a direct name filter.
        """
        logger.debug("Attempting to find NoCoDB base with title: %s", base_title)
        response_data = self._make_request("get", "projects/")
        if response_data and isinstance(response_data, dict) and "list" in response_data:
            for base in response_data["list"]:
                if base.get("title") == base_title:
                    logger.debug("Found NoCoDB base '%s' with ID: %s", base_title, base["id"])
                    return base
            logger.debug(
                "NoCoDB base with title '%s' not found in the list of bases.",
                base_title,
            )
        else:
            logger.warning(
                "Failed to list NoCoDB bases or unexpected response format. Response: %s",
                response_data,
            )
        return None

    def invite_user_to_base(self, base_id: str, email: str, role: str) -> bool:
        """
        Invites a user to a base with a specific role.
        API: POST /api/v1/db/meta/projects/{baseId}/users
        Role can be: "owner", "creator", "editor", "commenter", "viewer", "guest", "no-access"
        """
        payload = {"email": email, "roles": role}
        logger.info(
            f"Attempting to invite user '{email}' to NoCoDB base ID '{base_id}' with role '{role}'"
        )  # Kept as INFO
        endpoint = f"projects/{base_id}/users"
        response_data = self._make_request("post", endpoint, json=payload)
        # Successful invitation typically returns a message like:
        # {"msg": "The user has been invited successfully"}
        if response_data and isinstance(response_data, dict) and "msg" in response_data:
            user_info = f"Successfully invited user '{email}' to base ID '{base_id}'."
            message_info = f"Message: {response_data['msg']}"
            logger.info(f"{user_info} {message_info}")
            return True
        logger.warning(f"Failed to invite user '{email}' to base ID '{base_id}'. Response: {response_data}")
        return False

    def update_base_user(self, base_id: str, user_id: str, role: str) -> bool:
        """
        Updates a user's role in a specific base.
        API: PATCH /api/v1/db/meta/projects/{baseId}/users/{userId}
        Note: The API doc provided shows "email" in payload, but typically PATCH for a specific user ID wouldn't need email.
              Assuming role is the primary updatable field here. If email change is needed, API might differ.
              For now, following the provided roles example.
        """
        payload = {"roles": role}  # Assuming only role can be updated this way.
        logger.info(
            f"Attempting to update user ID '{user_id}' in NoCoDB base ID '{base_id}' to role '{role}'"
        )  # Kept as INFO
        endpoint = f"projects/{base_id}/users/{user_id}"
        response_data = self._make_request("patch", endpoint, json=payload)
        if (
            response_data and isinstance(response_data, dict) and "msg" in response_data
        ):  # e.g. {"msg": "The user has been updated successfully"}
            log_msg = (
                f"Successfully updated user ID '{user_id}' in base ID '{base_id}'. " f"Message: {response_data['msg']}"
            )
            logger.info(log_msg)  # Kept as INFO
            return True
        logger.warning(
            f"Failed to update user ID '{user_id}' in base ID '{base_id}'. Response: {response_data}"
        )  # Kept as WARNING
        return False

    def list_base_users(self, base_id: str) -> list[dict]:
        """
        Lists all users associated with a specific base.
        API: GET /api/v1/db/meta/projects/{baseId}/users
        """
        logger.debug("Listing users for NoCoDB base ID '%s'", base_id)
        endpoint = f"projects/{base_id}/users"
        response_data = self._make_request("get", endpoint)
        if (
            response_data
            and isinstance(response_data, dict)
            and "users" in response_data
            and "list" in response_data["users"]
        ):
            users_list = response_data["users"]["list"]
            logger.debug("Found %d users for base ID '%s'.", len(users_list), base_id)
            return users_list
        logger.warning(
            "Failed to list users for base ID '%s' or unexpected format. Response: %s",
            base_id,
            response_data,
        )
        return []

    def list_bases(self) -> list[dict]:
        """
        List all base meta data
        """
        logger.debug("Listing bases in NoCoDB")
        endpoint = "projects/"
        response_data = self._make_request("get", endpoint)
        return response_data

    def delete_base_user(self, base_id: str, user_id: str) -> bool:
        """
        Deletes/removes a user from a specific base.
        The provided API docs do not show a direct DELETE user endpoint.
        Common practice might be to use PATCH with role "no-access" or look for a specific DELETE verb.
        Attempting PATCH with "no-access" as a common alternative. If a true DELETE exists, this should be updated.
        Considered:
        PATCH /api/v1/db/meta/projects/{baseId}/users/{userId} with {"roles": "no-access"}
        If NoCoDB has a dedicated DELETE /api/v1/db/meta/projects/{baseId}/users/{userId}, that would be preferred.
        For now, implementing the "no-access" role update.
        """
        logger.info(  # Kept as INFO, as this is a significant action (semantically a delete)
            f"Attempting to remove user ID '{user_id}' from NoCoDB base ID '{base_id}' "
            "by setting role to 'no-access'."
        )
        # This effectively uses the update_base_user method with a specific role.
        # If a direct delete is confirmed, this method should be changed.
        return self.update_base_user(base_id, user_id, role="no-access")

    def get_user_by_email_in_base(self, base_id: str, email: str) -> dict | None:
        """
        Helper to find a user's details (like ID) by their email within a specific base.
        This is not a direct API call but uses list_base_users and filters locally.
        """
        logger.debug(f"Searching for user with email '{email}' in base ID '{base_id}'.")
        users = self.list_base_users(base_id)
        for user in users:
            if user.get("email", "").lower() == email.lower():
                log_msg = f"Found user '{email}' with ID '{user.get('id')}' " f"in base '{base_id}'."
                logger.debug(log_msg)
                return user
        logger.debug(f"User with email '{email}' not found in base ID '{base_id}'.")
        return None

    def list_users(self) -> list[dict] | None:
        """
        Retrieves all users from all bases in NocoDB.
        :return: A list of user objects, or None on failure.
        """
        logging.info("NocoDB API >> Listing all users from all bases...")
        bases_response = self.list_bases()
        if not bases_response or "list" not in bases_response:
            logging.error("Failed to retrieve the list of bases from NocoDB.")
            return None

        all_users = {}  # Use a dict to store users by ID to handle duplicates
        for base in bases_response["list"]:
            base_id = base.get("id")
            if not base_id:
                continue

            base_users = self.list_base_users(base_id)
            for user in base_users:
                user_id = user.get("id")
                if user_id and user_id not in all_users:
                    all_users[user_id] = user

        users_list = list(all_users.values())
        logging.info(f"Successfully fetched {len(users_list)} unique users across all bases.")
        return users_list

    def delete_user(self, base_id: str, user_id: str) -> bool:
        """
        Deletes a user from a specific base in NocoDB.
        API: DELETE /api/v1/db/meta/projects/{baseId}/users/{userId}
        """
        if not base_id or not user_id:
            logging.error("Base ID and User ID must be provided to delete a user.")
            return False

        logger.info(f"Attempting to delete user ID '{user_id}' from NocoDB base ID '{base_id}'.")
        endpoint = f"projects/{base_id}/users/{user_id}"
        response_data = self._make_request("delete", endpoint)

        # A successful DELETE might return a 204 No Content or a success message
        if response_data is None:  # Likely a 204 No Content success
            logger.info(f"Successfully deleted user ID '{user_id}' from base ID '{base_id}'.")
            return True
        if isinstance(response_data, dict) and response_data.get("msg") == "The user has been deleted successfully":
            logger.info(f"Successfully deleted user ID '{user_id}' from base ID '{base_id}'.")
            return True

        logger.warning(f"Failed to delete user ID '{user_id}' from base ID '{base_id}'. Response: {response_data}")
        return False


if __name__ == "__main__":
    # This block is for example usage and local testing.
    # It's commented out to prevent flake8 errors about unused 'os' and 'dotenv'
    # when this file is linted as part of the project's production code.
    # To run this example:
    # 1. Uncomment the block.
    # 2. Ensure you have a .env file with NOCODB_URL and NOCODB_TOKEN in the marty_bot/clients/ directory
    #    or in the project root, or have these environment variables set.
    # 3. Run this script directly: python marty_bot/clients/nocodb_client.py

    # import os
    # from dotenv import load_dotenv
    #
    # dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
    # if not os.path.exists(dotenv_path):
    #     dotenv_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env") # Project root
    # load_dotenv(dotenv_path=dotenv_path)
    #
    # NOCODB_URL_ENV = os.getenv("NOCODB_URL")
    # NOCODB_TOKEN_ENV = os.getenv("NOCODB_TOKEN")
    #
    # if not NOCODB_URL_ENV or not NOCODB_TOKEN_ENV:
    #     print("NOCODB_URL and NOCODB_TOKEN must be set for example usage.")
    # else:
    #     logging.basicConfig(level=logging.DEBUG)
    #     client = NocoDBClient(nocodb_url=NOCODB_URL_ENV, token=NOCODB_TOKEN_ENV)
    #     print(f"\n--- Testing with NocoDB instance: {NOCODB_URL_ENV[:20]}... ---")
    #
    #     # Example: List existing bases
    #     print("\n--- Listing existing bases (first few) ---")
    #     existing_bases = client._make_request("get", "projects/")
    #     if existing_bases and existing_bases.get("list"):
    #         for i, b in enumerate(existing_bases["list"][:3]):
    #             print(f"  Base {i+1}: Title='{b.get('title')}', ID='{b.get('id')}'")
    #         if len(existing_bases["list"]) > 3:
    #             print(f"  ... and {len(existing_bases['list']) - 3} more.")
    #     else:
    #         print("  Could not list bases or no bases found.")
    #
    #     # Example: Get a specific base by title (replace with an actual title from your instance)
    #     # target_title_to_find = "YourActualBaseTitle"
    #     # print(f"\n--- Attempting to get base by title: {target_title_to_find} ---")
    #     # found_base = client.get_base_by_title(target_title_to_find)
    #     # if found_base:
    #     #     print(f"  Found base: {found_base}")
    #     #     base_id_for_user_tests = found_base.get("id")
    #     #
    #     #     if base_id_for_user_tests:
    #     #         print(f"\n--- Listing users for base ID: {base_id_for_user_tests} ---")
    #     #         users = client.list_base_users(base_id_for_user_tests)
    #     #         if users:
    #     #             for user in users:
    #     #                 print(f"  User: {user.get('email')}, Roles: {user.get('roles')}, ID: {user.get('id')}")
    #     #         else:
    #     #             print(f"  No users found for base {base_id_for_user_tests} or failed to list.")
    #     # else:
    #     #     print(f"  Base with title '{target_title_to_find}' not found.")
    #
    #     print("\n--- Example usage script finished. ---")
    pass
