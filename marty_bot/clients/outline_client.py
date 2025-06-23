import requests
import json
import logging  # Added logging

# Removed direct import of config


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

    def create_group(self, project_name: str) -> bool:
        """
        Creates a collection (space) in Outline.
        :param project_name: The name of the project/collection to create.
        :return: True if successful, False otherwise.
        """
        # Outline's API endpoint for creating collections is /api/collections.create
        api_url = f"{self.base_url}/api/collections.create"

        payload = {
            "name": project_name,
            # "description": f"Collection for project {project_name}",
            # "permission": "read_write",
            # "private": False
        }
        logging.debug(f"Outline API >> Creating collection '{project_name}' with payload: {json.dumps(payload)}")
        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            # Outline API often returns 200 on successful creation, even if it already exists
            # For example, creating an existing collection returns the existing collection data.
            if response.status_code == 200:
                response_data = response.json()
                collection_id = response_data.get("data", {}).get("id")
                if collection_id:
                    logging.info(
                        f"Outline collection '{project_name}' (ID: {collection_id}) processed successfully (either created or existed)."
                    )
                    return True  # Assuming success if we get an ID, actual creation or existence.
                else:
                    logging.warning(
                        f"Outline collection '{project_name}' creation/fetch reported success (200), "
                        f"but response data is not as expected: {response.text}"
                    )
                    return False  # Or handle as a specific state if needed
            else:
                # Attempt to parse error for better logging
                error_details_msg = ""
                try:
                    error_json = response.json()
                    error_details_msg = f" (API Error: {error_json.get('message', 'No specific message')})"
                except json.JSONDecodeError:
                    error_details_msg = " (Could not parse JSON error response)"

                logging.error(
                    f"Error creating/processing Outline collection '{project_name}': {response.status_code} - {response.text}{error_details_msg}"
                )
                return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed for Outline collection creation '{project_name}': {e}")
            return False

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
                f"HTTP error fetching Outline user by email '{email}': {e.response.status_code} - {e.response.text}"
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed while fetching Outline user by email '{email}': {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from Outline users.list response for email '{email}': {e}")
            return None

    def get_collection_by_name(self, name: str) -> dict | None:
        """
        Retrieves an Outline collection by its exact name.
        Note: This might be inefficient if there are many collections, as it lists them and filters.
        :param name: The exact name of the collection to find.
        :return: A dictionary containing the collection data if found, None otherwise.
        """
        api_url = f"{self.base_url}/api/collections.list"
        # No direct name filter, so we list and filter. Consider pagination if many collections.
        # For now, assuming a reasonable number of collections that fit in one page or a few.
        limit = 100  # Adjust as needed, or implement pagination
        offset = 0

        logging.debug(f"Outline API >> Attempting to find collection by name '{name}'. Listing collections...")
        try:
            while True:
                payload = {"limit": limit, "offset": offset}
                response = requests.post(api_url, headers=self.headers, json=payload)
                response.raise_for_status()
                response_data = response.json()
                collections = response_data.get("data", [])

                for collection in collections:
                    if collection.get("name") == name:
                        logging.info(f"Found Outline collection '{name}' (ID: {collection.get('id')}).")
                        return collection

                if not collections or len(collections) < limit:  # Last page or no collections
                    break
                offset += limit  # Move to next page

            logging.info(f"Outline collection named '{name}' not found after checking all collections.")
            return None
        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error fetching Outline collections to find '{name}': {e.response.status_code} - {e.response.text}"
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed while fetching Outline collections to find '{name}': {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(
                f"Error decoding JSON from Outline collections.list response when searching for '{name}': {e}"
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
        logging.debug(
            f"Outline API >> Adding user ID '{user_id}' to collection ID '{collection_id}' "
            f"with permission '{permission}'. Payload: {json.dumps(payload)}"
        )
        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()  # Check for HTTP errors

            # According to example, a successful response contains 'data' with 'users' and 'memberships'.
            # The API might return success even if the user is already a member.
            # We'll consider it a success if the API doesn't error out and returns a 200.
            response_data = response.json()
            if response_data and "data" in response_data:  # Check if 'data' key exists
                logging.info(
                    f"Successfully processed add_user_to_collection for user ID '{user_id}' to collection ID '{collection_id}'."
                )
                return True
            else:
                logging.warning(
                    f"Outline collections.add_user for user ID '{user_id}' to collection ID '{collection_id}' "
                    f"returned 200 but 'data' key was missing or response was unexpected: {response.text}"
                )
                return False

        except requests.exceptions.HTTPError as e:
            # Log specific HTTP errors
            # Example: 403 if user already member with higher permission, or if collection/user not found.
            # Outline's API might return 403 if "User is already a member of the collection"
            # or if trying to add with a permission that's already effectively there.
            # For simplicity, we'll log the error and return False.
            # More sophisticated error handling could inspect e.response.json().get("message")
            logging.error(
                f"HTTP error adding user ID '{user_id}' to Outline collection ID '{collection_id}': "
                f"{e.response.status_code} - {e.response.text}"
            )
            # Check if user was already a member - this might not be a true "failure" for our sync logic
            # For now, if API call fails for any HTTP reason, we report False.
            # if "already a member" in e.response.text.lower():
            #     logging.info(f"User {user_id} already a member of collection {collection_id}.")
            #     return True # Or a specific status indicating "already_exists"
            return False
        except requests.exceptions.RequestException as e:
            logging.error(
                f"Request failed while adding user ID '{user_id}' to Outline collection ID '{collection_id}': {e}"
            )
            return False
        except json.JSONDecodeError as e:  # Should be caught by HTTPError if status is not 2xx
            logging.error(
                f"Error decoding JSON from Outline collections.add_user response for user '{user_id}' "
                f"in collection '{collection_id}': {e}"
            )
            return False


if __name__ == "__main__":
    from dotenv import load_dotenv
    import os

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
