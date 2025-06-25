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

    def create_group(self, project_name: str) -> str:
        """
        Ensures a collection (space) in Outline exists, creating it if necessary.
        :param project_name: The name of the project/collection.
        :return: "CREATED" if newly created, "EXISTS" if already there, "FAILED" otherwise.
        """
        # 1. Check if collection already exists
        try:
            existing_collection = self.get_collection_by_name(project_name)
            if existing_collection:
                collection_id = existing_collection.get("id")
                logging.info(f"Outline collection '{project_name}' (ID: {collection_id}) already exists.")
                return "EXISTS"
        except requests.exceptions.RequestException as e:
            # This exception would come from get_collection_by_name if requests.post fails there
            logging.error(
                f"Outline API >> Error during existence check for collection '{project_name}': {e}"
            )  # noqa: E501
            return "FAILED"  # If we can't check, we can't safely determine existence or create

        # 2. If not found (and no error during check), try to create it
        create_api_url = f"{self.base_url}/api/collections.create"
        payload = {"name": project_name}

        logging.debug(
            f"Outline API >> Collection '{project_name}' not found. "
            f"Attempting to create with payload: {json.dumps(payload)}"
        )

        try:
            response = requests.post(create_api_url, headers=self.headers, json=payload)

            if response.status_code == 200:  # Outline typically returns 200 for successful creation
                response_data = response.json()
                data_content = response_data.get("data")
                if isinstance(data_content, dict) and data_content.get("id"):
                    collection_id = data_content.get("id")
                    logging.info(f"Outline collection '{project_name}' (ID: {collection_id}) created successfully.")
                    return "CREATED"
                else:
                    # Success status but unexpected data format
                    logging.warning(
                        f"Outline collection '{project_name}' creation reported success (200), "
                        f"but 'id' could not be retrieved from response data: {response.text}"  # noqa: E501
                    )
                    return "FAILED"  # Treat as failure if data is not as expected
            else:
                # Handle non-200 responses for collections.create
                error_details_msg = ""
                try:
                    error_json = response.json()
                    error_details_msg = f" (API Error: {error_json.get('message', 'No specific message')})"
                except json.JSONDecodeError:
                    error_details_msg = " (Could not parse JSON error response)"

                logging.error(
                    f"Error creating Outline collection '{project_name}': {response.status_code} - {response.text}{error_details_msg}"  # noqa: E501
                )
                return "FAILED"
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception during Outline collection creation for '{project_name}': {e}")
            return "FAILED"

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

    def get_collection_by_name(self, name: str) -> dict | None:
        """
        Retrieves an Outline collection by its exact name.
        Note: This might be inefficient if there are many collections, as it lists them and filters.
        :param name: The exact name of the collection to find.
        :return: A dictionary containing the collection data if found, None otherwise.
        """
        api_url = f"{self.base_url}/api/collections.list"
        limit = 100
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

                if not collections or len(collections) < limit:
                    break
                offset += limit

            logging.info(f"Outline collection named '{name}' not found after checking all collections.")
            return None
        except requests.exceptions.HTTPError as e:
            logging.error(
                f"HTTP error fetching Outline collections to find '{name}': {e.response.status_code} - {e.response.text}"  # noqa: E501
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed while fetching Outline collections to find '{name}': {e}")
            return None
        except json.JSONDecodeError as e:
            logging.error(
                f"Error decoding JSON from Outline collections.list response when searching for '{name}': {e}"  # noqa: E501
            )
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

            logging.info(
                f"Successfully fetched {len(member_user_ids)} member IDs for Outline collection ID "  # noqa: E501
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
        logging.debug(
            f"Outline API >> Adding user ID '{user_id}' to collection ID '{collection_id}' "
            f"with permission '{permission}'. Payload: {json.dumps(payload)}"  # noqa: E501
        )
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
