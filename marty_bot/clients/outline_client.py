import json
import logging
from enum import Enum
from typing import Optional

import requests


class OutlineAction(Enum):
    USER_ADDED_TO_COLLECTION_WITH_READ_ACCESS_AND_DM_SENT = (
        "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_ACCESS_AND_DM_SENT"
    )
    USER_ADDED_TO_COLLECTION_WITH_READ_WRITE_ACCESS_AND_DM_SENT = (
        "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_WRITE_ACCESS_AND_DM_SENT"
    )
    USER_ADDED_TO_COLLECTION_WITH_READ_ACCESS_DM_FAILED = "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_ACCESS_DM_FAILED"
    USER_ADDED_TO_COLLECTION_WITH_READ_WRITE_ACCESS_DM_FAILED = (
        "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_WRITE_ACCESS_DM_FAILED"
    )
    USER_ALREADY_IN_COLLECTION_PERMISSION_ENSURED = "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED"
    USER_REMOVED_FROM_COLLECTION = "USER_REMOVED_FROM_OUTLINE_COLLECTION"


class OutlineClient:
    def __init__(self, base_url: str, token: str):
        """
        Initializes the OutlineClient.
        :param base_url: The base URL of the Outline instance (e.g., https://app.getoutline.com)
        :param token: The API token for Outline.
        """
        if not base_url or not token:
            raise ValueError("Outline base_url and token must be provided.")
        self.base_url = base_url.rstrip("/")  # Ensure no trailing slash
        self.token = token
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def create_group(self, project_name: str) -> str:
        """
        Ensures a collection (space) in Outline exists, creating it if necessary.
        :param project_name: The name of the project/collection.
        :return: The collection object (dict with at least 'id' and 'name') if successful/exists, None otherwise.
        """
        # 1. Check if collection already exists
        existing_collection = self.list_collections(name=project_name)
        if existing_collection is not None:
            if existing_collection:
                return existing_collection  # Return the existing collection object
        else:
            return None

        # 2. If not found (and no error during check), try to create it
        create_api_url = f"{self.base_url}/api/collections.create"
        payload = {"name": project_name}

        logging.debug(
            f"Outline API >> Collection '{project_name}' not found. "
            f"Attempting to create with payload: {json.dumps(payload)}"
        )
        try:
            response = requests.post(create_api_url, headers=self.headers, json=payload)
            if response.status_code == 200:
                response_data = response.json()
                data_content = response_data.get("data")
                if isinstance(data_content, dict) and data_content.get("id"):
                    collection_id = data_content.get("id")
                    logging.info(f"Outline collection '{project_name}' (ID: {collection_id}) created successfully.")
                    return data_content  # Return the newly created collection object
                else:
                    logging.warning(
                        f"Outline collection '{project_name}' creation reported success (200), "
                        f"but 'id' or valid data could not be retrieved from response: {response.text}"
                    )
                    return None
            else:
                error_details_msg = ""
                try:
                    error_json = response.json()
                    error_details_msg = f" (API Error: {error_json.get('message', 'No specific message')})"
                except json.JSONDecodeError:
                    error_details_msg = " (Could not parse JSON error response)"
                logging.error(
                    f"Error creating Outline collection '{project_name}': {response.status_code} - {response.text}{error_details_msg}"
                )
                return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception during Outline collection creation for '{project_name}': {e}")
            return None

    def get_user_by_email(self, email: str) -> dict | None:
        """
        Retrieves a user from Outline by their email address.
        :param email: The email address of the user to find.
        :return: A dictionary containing the user data if found, None otherwise.
        """
        api_url = f"{self.base_url}/api/users.list"
        payload = {
            "emails": [email.lower()],  # API expects a list, convert email to lowercase for case-insensitivity
            "limit": 1,  # We only expect one user or none
        }
        logging.debug(f"Outline API >> Getting user by email '{email}' with payload: {json.dumps(payload)}")
        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()  # Check for HTTP errors like 401, 403, etc.

            response_data = response.json()
            users = response_data.get("data", [])

            if users and len(users) > 0:
                # Assuming the first user found with that email is the correct one
                user_data = users[0]
                logging.info(f"Found Outline user (ID: {user_data.get('id')}) for email '{email}'.")
                return user_data
            else:
                logging.info(f"No Outline user found for email '{email}'.")
                return None
        except requests.exceptions.HTTPError as e:
            # Log specific HTTP errors, e.g. if the API endpoint itself is wrong or auth fails
            logging.error(
                f"HTTP error fetching Outline user by email '{email}': {e.response.status_code} - {e.response.text}"  # noqa: E501
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed while fetching Outline user by email '{email}': {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from Outline users.list response for email '{email}': {e}")
            return None

    def list_collections(self, name: Optional[str] = None, limit: int = 100) -> list[dict] | dict | None:
        """
        Retrieves collections from Outline. If a name is provided, it returns a single matching collection object.
        If no name is provided, it returns all collections.
        :param name: The exact name of the collection to find (optional).
        :param limit: The number of items to return per page. Max 100.
        :return: A list of collection objects or a single collection object, or None on failure.
        """
        api_url = f"{self.base_url}/api/collections.list"
        all_collections = []
        offset = 0

        if name:
            logging.debug(f"Outline API >> Attempting to find collection by name '{name}'.")
        else:
            logging.info("Outline API >> Listing all collections...")

        try:
            while True:
                payload = {"limit": min(limit, 100), "offset": offset}
                if name:
                    payload["query"] = name
                response = requests.post(api_url, headers=self.headers, json=payload)
                response.raise_for_status()
                response_data = response.json()
                collections = response_data.get("data", [])
                pagination = response_data.get("pagination", {})
                total = pagination.get("total", 0)

                if name:
                    if collections:
                        for collection in collections:
                            if collection.get("name") == name:
                                logging.info(f"Found Outline collection '{name}' (ID: {collection.get('id')}).")
                                return collection
                        logging.info(f"Outline collection named '{name}' not found after checking results.")
                        return []  # Aucun nom exactement égal
                    else:
                        logging.info(f"Outline collection named '{name}' not found after checking all collections.")
                        return []
                else:
                    all_collections.extend(collections)

                if not collections or len(all_collections) >= total:
                    break

                offset += len(all_collections)

            logging.info(f"Successfully fetched {len(all_collections)} Outline collections.")
            return all_collections
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP error fetching Outline collections: {e.response.status_code} - {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed while fetching Outline collections: {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from Outline collections.list response: {e}")
            return None

    def get_collection_members(self, collection_id: str, limit: int = 100) -> list[str] | None:
        """
        Retrieves user IDs of members for a specific collection.
        :param collection_id: The ID of the collection.
        :param limit: The number of items to return per page. Max 100.
        :return: A list of user IDs if successful, None otherwise.
        """
        if not collection_id:
            logging.error("Collection ID must be provided to get collection members.")
            return None

        api_url = f"{self.base_url}/api/collections.memberships"
        member_user_ids = []
        offset = 0
        page_count = 0

        logging.debug(f"Outline API >> Getting collection members for ID '{collection_id}'")

        try:
            while True:
                page_count += 1
                payload = {
                    "id": collection_id,
                    "offset": offset,
                    "limit": min(limit, 100),
                }
                logging.debug(
                    f"Outline API >> Fetching page {page_count} for collection members "
                    f"(offset: {offset}, limit: {payload['limit']})"
                )
                response = requests.post(api_url, headers=self.headers, json=payload)
                response.raise_for_status()
                response_data = response.json()

                data_block = response_data.get("data", {})
                memberships = data_block.get("memberships", [])

                if not memberships and not data_block.get("users"):
                    if offset == 0:
                        logging.info(f"No members found for Outline collection ID '{collection_id}'.")
                    break

                for membership in memberships:
                    user_id = membership.get("userId")
                    if user_id:
                        member_user_ids.append(user_id)

                pagination_info = response_data.get("pagination", {})
                response_limit = pagination_info.get("limit", payload["limit"])

                if len(memberships) < response_limit:
                    break

                offset += len(memberships)
                if offset >= 10000:
                    logging.warning(
                        f"Safety break after fetching {len(member_user_ids)} members for "
                        f"collection {collection_id}. Reached offset {offset}."
                    )
                    break

            logging.info(  # noqa: E501
                f"Successfully fetched {len(member_user_ids)} member IDs for Outline collection ID "
                f"'{collection_id}' over {page_count} pages."
            )
            return member_user_ids

        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error fetching members for Outline collection ID '{collection_id}': "
                f"{e.response.status_code} - {e.response.text}"  # noqa: E501
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed while fetching members for Outline collection ID '{collection_id}': {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(
                f"Error decoding JSON from Outline collections.memberships response for collection ID '{collection_id}': {e}"  # noqa: E501
            )
            return None

    def add_user_to_collection(self, collection_id: str, user_id: str, permission: str = "read") -> bool:
        """
        Adds a user to an Outline collection.
        :param collection_id: The ID of the collection.
        :param user_id: The ID of the user.
        :param permission: The permission level to grant (e.g., "read", "read_write"). Defaults to "read".
        :return: True if the user was successfully added (or was already a member with compatible permissions), False otherwise.
        """
        api_url = f"{self.base_url}/api/collections.add_user"
        payload = {
            "id": collection_id,
            "userId": user_id,
            "permission": permission,
        }
        log_msg = (
            f"Outline API >> Adding user ID '{user_id}' to collection ID '{collection_id}' "
            f"with permission '{permission}'. Payload: {json.dumps(payload)}"
        )  # noqa: E501
        logging.debug(log_msg)
        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()

            response_data = response.json()
            if response_data and "data" in response_data:
                logging.info(
                    f"Successfully processed add_user_to_collection for user ID '{user_id}' to collection ID '{collection_id}'."  # noqa: E501
                )
                return True
            else:
                logging.warning(
                    f"Outline collections.add_user for user ID '{user_id}' to collection ID '{collection_id}' "
                    f"returned 200 but 'data' key was missing or response was unexpected: {response.text}"  # noqa: E501
                )
                return False

        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error adding user ID '{user_id}' to Outline collection ID '{collection_id}': "
                f"{e.response.status_code} - {e.response.text}"  # noqa: E501
            )
            return False
        except requests.exceptions.RequestException as e:
            logging.error(
                f"Request failed while adding user ID '{user_id}' to Outline collection ID '{collection_id}': {e}"  # noqa: E501
            )
            return False
        except json.JSONDecodeError as e:
            logging.error(
                f"Error decoding JSON from Outline collections.add_user response for user '{user_id}' "
                f"in collection '{collection_id}': {e}"  # noqa: E501
            )
            return False

    def get_collection_details(self, collection_id: str) -> dict | None:
        """
        Retrieves details for a specific collection by its ID.
        :param collection_id: The ID of the collection.
        :return: A dictionary containing the collection data if found, None otherwise.
        """
        if not collection_id:
            logging.error("Collection ID must be provided to get collection details.")
            return None

        api_url = f"{self.base_url}/api/collections.info"
        payload = {"id": collection_id}
        logging.debug(f"Outline API >> Getting collection details for ID '{collection_id}'")

        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()

            response_data = response.json()
            collection_data = response_data.get("data")

            if collection_data:
                logging.info(f"Successfully fetched details for Outline collection ID '{collection_id}'.")
                return collection_data
            else:
                logging.warning(
                    f"Outline collection.info for ID '{collection_id}' returned successfully "
                    f"but 'data' key was missing or response was unexpected: {response.text}"  # noqa: E501
                )
                return None
        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error fetching details for Outline collection ID '{collection_id}': "
                f"{e.response.status_code} - {e.response.text}"  # noqa: E501
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed while fetching details for Outline collection ID '{collection_id}': {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(
                f"Error decoding JSON from Outline collections.info response for collection ID '{collection_id}': {e}"  # noqa: E501
            )
            return None

    def get_user_by_id(self, user_id: str) -> dict | None:
        """
        Retrieves a user from Outline by their ID.
        Uses /api/users.info endpoint.
        :param user_id: The ID of the user to find.
        :return: A dictionary containing the user data if found, None otherwise.
        """
        if not user_id:
            logging.error("User ID must be provided to get user by ID.")
            return None

        api_url = f"{self.base_url}/api/users.info"
        payload = {"id": user_id}
        logging.debug(f"Outline API >> Getting user by ID '{user_id}'")

        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()
            response_data = response.json()
            user_data = response_data.get("data")

            if user_data:
                logging.info(f"Successfully fetched Outline user (ID: {user_id}, Name: {user_data.get('name')}).")
                return user_data
            else:
                logging.warning(f"Outline user ID '{user_id}' not found or no data returned.")
                return None
        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error fetching Outline user by ID '{user_id}': {e.response.status_code} - {e.response.text}"
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed while fetching Outline user by ID '{user_id}': {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from Outline users.info response for ID '{user_id}': {e}")
            return None

    def get_collection_members_with_details(self, collection_id: str) -> list[dict] | None:
        """
        Retrieves full user details for all members of a specific collection.
        :param collection_id: The ID of the collection.
        :return: A list of user detail dictionaries if successful, None otherwise.
        """
        member_ids = self.get_collection_members(collection_id)
        if member_ids is None:
            return None  # Error occurred during member ID fetching

        member_details = []
        for user_id in member_ids:
            user_details = self.get_user_by_id(user_id)
            if user_details:
                member_details.append(user_details)
            else:
                logging.warning(f"Could not fetch details for user ID '{user_id}' in collection '{collection_id}'.")
        return member_details

    def remove_user_from_collection(self, collection_id: str, user_id: str) -> bool:
        """
        Removes a user from an Outline collection.
        :param collection_id: The ID of the collection.
        :param user_id: The ID of the user to remove.
        :return: True if successful, False otherwise.
        """
        if not collection_id or not user_id:
            logging.error("Collection ID and User ID must be provided to remove user from collection.")
            return False

        api_url = f"{self.base_url}/api/collections.remove_user"
        payload = {
            "id": collection_id,  # Corrigé: "id" au lieu de "collectionId"
            "userId": user_id,
        }
        logging.info(
            f"Outline API >> Removing user ID '{user_id}' from collection ID '{collection_id}'. Payload: {json.dumps(payload)}"
        )
        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()  # Check for HTTP errors

            # Outline API usually returns a success boolean or specific data structure
            # For remove_user, a 200 OK with {"success": true} is common, or 204 No Content
            if response.status_code == 204:  # Successfully removed, no content
                logging.info(f"Successfully removed user ID '{user_id}' from Outline collection ID '{collection_id}'.")
                return True

            response_data = response.json()
            if response_data.get("success"):
                logging.info(f"Successfully removed user ID '{user_id}' from Outline collection ID '{collection_id}'.")
                return True
            else:
                # This case handles 200 OK but success:false or missing success field
                logging.warning(
                    f"Outline collections.remove_user for user ID '{user_id}' in collection ID '{collection_id}' "
                    f"did not report success or returned unexpected data: {response.text}"
                )
                return False
        except requests.exceptions.HTTPError as e:
            # Specific check if user was not in collection - Outline might return 400/404 or specific error
            # Example: if e.response.status_code == 400 and "User is not a member" in e.response.text:
            #    logging.info(f"User {user_id} was not in collection {collection_id}. Considered successful removal.")
            #    return True
            logging.error(
                f"HTTP error removing user ID '{user_id}' from Outline collection ID '{collection_id}': "
                f"{e.response.status_code} - {e.response.text}"
            )
            return False
        except requests.exceptions.RequestException as e:
            logging.error(
                f"Request exception removing user ID '{user_id}' from Outline collection ID '{collection_id}': {e}"
            )
            return False
        except json.JSONDecodeError as e:  # If response is not JSON
            logging.error(
                f"Error decoding JSON from Outline collections.remove_user response for user '{user_id}' "
                f"in collection '{collection_id}': {e}. Response text: {response.text}"
            )
            return False

    def list_users(self, limit: int = 100) -> list[dict] | None:
        """
        Retrieves all users from Outline, handling pagination.
        :param limit: The number of users to return per page. Max 100.
        :return: A list of user objects, or None on failure.
        """
        api_url = f"{self.base_url}/api/users.list"
        all_users = []
        offset = 0

        logging.info("Outline API >> Listing all users...")

        try:
            while True:
                # The payload should be `json=None` as the user mentioned, but the API probably expects a body for POST.
                # An empty json body `{}` is safer. Or `json=payload`.
                # The user mentioned `offset` and `limit` as parameters, so I will use them.
                payload = {"limit": min(limit, 100), "offset": offset}
                response = requests.post(api_url, headers=self.headers, json=payload)
                response.raise_for_status()
                response_data = response.json()
                users = response_data.get("data", [])

                all_users.extend(users)

                pagination = response_data.get("pagination", {})
                total = pagination.get("total")  # Can be None if not provided by API

                # Stop if we've received all users
                if not users or (total is not None and len(all_users) >= total):
                    break

                offset += len(users)

            logging.info(f"Successfully fetched {len(all_users)} Outline users.")
            return all_users
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP error fetching Outline users: {e.response.status_code} - {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed while fetching Outline users: {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from Outline users.list response: {e}")
            return None

    def delete_user(self, user_id: str) -> bool:
        """
        Deletes a user from Outline.
        :param user_id: The ID of the user to delete.
        :return: True if successful, False otherwise.
        """
        if not user_id:
            logging.error("User ID must be provided to delete a user.")
            return False

        api_url = f"{self.base_url}/api/users.delete"
        payload = {"id": user_id}
        logging.info(f"Outline API >> Deleting user ID '{user_id}'. Payload: {json.dumps(payload)}")
        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()

            # A successful deletion might return 204 No Content
            if response.status_code == 204:
                logging.info(f"Successfully deleted user ID '{user_id}' from Outline.")
                return True

            response_data = response.json()
            if response_data.get("success"):
                logging.info(f"Successfully deleted user ID '{user_id}' from Outline.")
                return True
            else:
                logging.warning(
                    f"Outline users.delete for user ID '{user_id}' "
                    f"did not report success or returned unexpected data: {response.text}"
                )
                return False
        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error deleting user ID '{user_id}' from Outline: "
                f"{e.response.status_code} - {e.response.text}"
            )
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception deleting user ID '{user_id}' from Outline: {e}")
            return False
        except json.JSONDecodeError as e:
            logging.error(
                f"Error decoding JSON from Outline users.delete response for user '{user_id}': {e}. Response text: {response.text}"
            )
            return False


if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv()

    outline_url_env = os.getenv("OUTLINE_URL")
    outline_token_env = os.getenv("OUTLINE_TOKEN")

    if not outline_url_env or not outline_token_env:
        print("Please set OUTLINE_URL and OUTLINE_TOKEN environment variables for this example.")  # noqa: E501
    else:
        print(f"Attempting to connect to Outline at {outline_url_env}")
        try:
            client = OutlineClient(base_url=outline_url_env, token=outline_token_env)

            project_to_create = "Test Project Collection OOP"
            print(f"\nAttempting to create Outline collection: '{project_to_create}'")
            success = client.create_group(project_to_create)
            print(f"Outline collection creation success: {success}")

            if success:
                print(f"\nAttempting to create Outline collection AGAIN: '{project_to_create}'")
                success_again = client.create_group(project_to_create)
                print(
                    f"Second Outline collection creation success: {success_again} (expected False if already exists or handled by Outline)"  # noqa: E501
                )

        except ValueError as ve:
            print(f"Configuration error: {ve}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
