import requests
import logging

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
            "xc-token": token,
            "Content-Type": "application/json",
        }
        logger.debug(f"NocoDBClient initialized for URL: {self.base_url}")

    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict | list | None:
        """Helper function to make requests to the NoCoDB API."""
        url = f"{self.base_url}/api/v1/db/meta/{endpoint.lstrip('/')}"
        json_params = kwargs.get("json")
        log_message = (
            f"NoCoDB API >> Request: {method.upper()} {url} - " f"Headers: {self.headers} - JSON Params: {json_params}"
        )
        logger.debug(log_message)
        try:
            response = requests.request(method, url, headers=self.headers, **kwargs)
            response.raise_for_status()
            if response.content:
                return response.json()
            return None
        except requests.exceptions.HTTPError as e:
            if e.response is not None:
                log_msg = (
                    f"NoCoDB API << HTTP error for {method.upper()} {url}: "
                    f"{e.response.status_code} - {e.response.text}"
                )
                logger.error(log_msg)
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
        }
        logger.info(f"Attempting to create NoCoDB base with title: {base_title}")
        response_data = self._make_request("post", "projects/", json=payload)
        if response_data and isinstance(response_data, dict) and response_data.get("id"):
            logger.info(f"Successfully created NoCoDB base '{base_title}' with ID: {response_data['id']}")
            return response_data
        logger.warning(f"Failed to create NoCoDB base '{base_title}'. Response: {response_data}")
        return None

    def get_base_by_title(self, base_title: str) -> dict | None:
        """
        Retrieves a specific base by its title.
        API: GET /api/v1/db/meta/projects/
        Filters locally as NoCoDB API for listing projects doesn't seem to have a direct name filter.
        """
        logger.debug(f"Attempting to find NoCoDB base with title: {base_title}")
        logger.debug(
            "NocoDBClient.get_base_by_title: This method lists all bases to find one by title. "
            "If many bases exist, this can be inefficient and contribute to DB connection load. "
            "Consider caching base IDs or implementing server-side filtering if available."
        )
        response_data = self._make_request("get", "projects/")
        if response_data and isinstance(response_data, dict) and "list" in response_data:
            for base in response_data["list"]:
                if base.get("title") == base_title:
                    logger.debug(f"Found NoCoDB base '{base_title}' with ID: {base['id']}")
                    return base
            logger.debug(f"NoCoDB base with title '{base_title}' not found in the list of bases.")
        else:
            logger.warning(f"Failed to list NoCoDB bases or unexpected response format. Response: {response_data}")
        return None

    def invite_user_to_base(self, base_id: str, email: str, role: str) -> bool:
        """
        Invites a user to a base with a specific role.
        API: POST /api/v1/db/meta/projects/{baseId}/users
        Role can be: "owner", "creator", "editor", "commenter", "viewer", "guest", "no-access"
        """
        payload = {"email": email, "roles": role}
        logger.info(f"Attempting to invite user '{email}' to NoCoDB base ID '{base_id}' with role '{role}'")
        endpoint = f"projects/{base_id}/users"
        response_data = self._make_request("post", endpoint, json=payload)
        if response_data and isinstance(response_data, dict) and "msg" in response_data:
            logger.info(
                f"Successfully invited user '{email}' to base ID '{base_id}'. "
                f"Message: {response_data['msg']}"  # noqa: E501
            )
            return True
        logger.warning(f"Failed to invite user '{email}' to base ID '{base_id}'. Response: {response_data}")
        return False

    def update_base_user(self, base_id: str, user_id: str, role: str) -> bool:
        """
        Updates a user's role in a specific base.
        API: PATCH /api/v1/db/meta/projects/{baseId}/users/{userId}
        """
        payload = {"roles": role}
        logger.info(f"Attempting to update user ID '{user_id}' in NoCoDB base ID '{base_id}' to role '{role}'")
        endpoint = f"projects/{base_id}/users/{user_id}"
        response_data = self._make_request("patch", endpoint, json=payload)
        if response_data and isinstance(response_data, dict) and "msg" in response_data:
            log_msg = (
                f"Successfully updated user ID '{user_id}' in base ID '{base_id}'. " f"Message: {response_data['msg']}"
            )
            logger.info(log_msg)
            return True
        logger.warning(f"Failed to update user ID '{user_id}' in base ID '{base_id}'. Response: {response_data}")
        return False

    def list_base_users(self, base_id: str) -> list[dict]:
        """
        Lists all users associated with a specific base.
        API: GET /api/v1/db/meta/projects/{baseId}/users
        """
        logger.debug(f"Listing users for NoCoDB base ID '{base_id}'")
        endpoint = f"projects/{base_id}/users"
        response_data = self._make_request("get", endpoint)
        if (
            response_data
            and isinstance(response_data, dict)
            and "users" in response_data
            and "list" in response_data["users"]
        ):
            users_list = response_data["users"]["list"]
            logger.debug(f"Found {len(users_list)} users for base ID '{base_id}'.")
            return users_list
        logger.warning(
            f"Failed to list users for base ID '{base_id}' or unexpected format. " f"Response: {response_data}"
        )
        return []

    def delete_base_user(self, base_id: str, user_id: str) -> bool:
        """
        Deletes/removes a user from a specific base by setting role to 'no-access'.
        """
        logger.info(
            f"Attempting to remove user ID '{user_id}' from NoCoDB base ID '{base_id}' "
            "by setting role to 'no-access'."
        )
        return self.update_base_user(base_id, user_id, role="no-access")

    def get_user_by_email_in_base(self, base_id: str, email: str) -> dict | None:
        """
        Helper to find a user's details by their email within a specific base.
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


if __name__ == "__main__":
    pass
