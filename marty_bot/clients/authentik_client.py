import json
import logging
from enum import Enum
from typing import Optional

import requests


class AuthentikAction(Enum):
    USER_ADDED_TO_GROUP = "USER_ADDED_TO_AUTHENTIK_GROUP"
    USER_ALREADY_IN_GROUP = "USER_ALREADY_IN_AUTHENTIK_GROUP"
    USER_REMOVED_FROM_GROUP = "USER_REMOVED_FROM_AUTHENTIK_GROUP"


class AuthentikClient:
    def __init__(self, base_url: str, token: str):
        """
        Initializes the AuthentikClient.
        :param base_url: The base URL of the Authentik instance (e.g., https://authentik.example.com)
        :param token: The API token for Authentik.
        """
        if not base_url or not token:
            raise ValueError("Authentik base_url and token must be provided.")
        self.base_url = base_url.rstrip("/")  # Ensure no trailing slash
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",  # Common for POST, harmless for GET
        }

    def create_group(self, project_name: str) -> bool:
        """
        Creates a group in Authentik.
        :param project_name: The name of the project/group to create.
        :return: True if successful, False otherwise.
        """
        # Note: Uses self.headers which now includes Content-Type by default
        api_url = f"{self.base_url}/api/v3/core/groups/"
        payload = {
            "name": project_name,
            "is_superuser": False,
        }

        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()  # Check for HTTP errors
            # If successful (201 Created), log and return True
            logging.info(
                f"Authentik group '{project_name}' created successfully. Group ID: {response.json().get('pk')}"
            )
            return response.json()  # Return the created group object
        except requests.exceptions.HTTPError as e:
            # Log specific HTTP errors, e.g. if group already exists (often a 400 or 409)
            error_msg = (  # noqa: E501
                f"HTTP error creating Authentik group '{project_name}': "
                f"{e.response.status_code} - {e.response.text}"  # noqa: E501
            )
            logging.error(error_msg)
            # Check if it's because group already exists - Authentik might return a specific error code/message
            # For example, if response.json().get('name') == ["group with this name already exists."]: logging.info(...) return True
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed for Authentik group creation '{project_name}': {e}")
            return False
        except json.JSONDecodeError as e:  # In case response.json() fails on success (unlikely for 201)
            logging.error(f"Error decoding JSON from Authentik group creation response for '{project_name}': {e}")
            return False

    def get_groups_with_users(self):
        """
        Fetches all groups from Authentik and their user objects, handling pagination.
        Returns a tuple: (list_of_group_objects, dict_email_to_user_pk).
        Each group object in the list should at least contain 'pk', 'name', and 'users' (list of user PKs).
        The dict_email_to_user_pk maps user email to their Authentik user PK.
        """
        if not self.base_url or not self.token:  # Should be caught by __init__ but good practice
            logging.error("Authentik client not configured (URL or Token missing).")
            return [], {}

        all_groups = []
        email_to_user_pk_map = {}

        current_url = (
            f"{self.base_url}/api/v3/core/groups/?include_users=true"  # Assuming include_users provides users_obj
        )
        logging.info(f"Fetching Authentik groups (with users) from initial URL: {current_url}")

        page_count = 0
        while current_url:
            page_count += 1
            logging.debug(f"Fetching group page {page_count} from {current_url}")
            try:
                response = requests.get(current_url, headers=self.headers)
                response.raise_for_status()
                data = response.json()

                page_groups = data.get("results", [])
                all_groups.extend(page_groups)

                # Process users from this page of groups
                for group in page_groups:
                    # Assuming users_obj is directly available or via an endpoint per group
                    # The prompt implies 'users_obj' is part of the group details when fetched correctly.
                    # If not, this part would need adjustment (e.g. fetch users per group)
                    users_obj = group.get("users_obj", [])
                    for user in users_obj:
                        email = user.get("email")
                        pk = user.get("pk")
                        if email and pk is not None:
                            if email in email_to_user_pk_map and email_to_user_pk_map[email] != pk:
                                logging.warning(
                                    f"User email {email} has conflicting PKs: "
                                    f"{email_to_user_pk_map[email]} vs {pk}. Using the latest one encountered."
                                )
                            email_to_user_pk_map[email] = pk

                current_url = data.get("pagination", {}).get("next")
                if current_url:
                    logging.debug(f"Next page for groups: {current_url}")

            except requests.exceptions.RequestException as e:
                logging.error(f"Error fetching Authentik groups from {current_url}: {e}")
                # Depending on desired behavior, could return partial results or empty
                return [], {}
            except json.JSONDecodeError as e:
                logging.error(f"Error decoding JSON from Authentik groups response ({current_url}): {e}")
                return [], {}

        logging.info(
            f"Fetched {len(all_groups)} groups, {len(email_to_user_pk_map)} user email-PK mappings "
            f"from Authentik over {page_count} pages."
        )
        return all_groups, email_to_user_pk_map

    def get_group_by_name(self, group_name: str) -> Optional[dict]:
        """
        Fetches a specific group by its name.
        Returns the group object (dict) if found, None otherwise.
        The group object should include 'users' (list of user PKs) and 'users_obj' (list of user dicts).
        """
        if not self.base_url or not self.token:
            logging.error("Authentik client not configured.")
            return None
        if not group_name:
            logging.error("Group name must be provided to fetch group by name.")
            return None

        # Step 1: Find group by name (without users initially for performance)
        # This part will use pagination to be safe, even if we expect one result.

        groups_found = []
        current_url = f"{self.base_url}/api/v3/core/groups/"
        params = {"name": group_name}

        logging.info(f"Fetching Authentik group(s) by name '{group_name}' from {current_url} with params {params}")
        page_count = 0
        while current_url:
            page_count += 1
            logging.debug(
                f"Fetching group search page {page_count} from {current_url} with params {params if page_count == 1 else None}"
            )
            try:
                response = requests.get(
                    current_url,
                    headers=self.headers,
                    params=params if page_count == 1 else None,
                )
                response.raise_for_status()
                data = response.json()
                page_results = data.get("results", [])
                groups_found.extend(page_results)
                current_url = data.get("pagination", {}).get("next")
                if current_url:
                    logging.debug(f"Next page for group search: {current_url}")
            except requests.exceptions.RequestException as e:
                logging.error(f"Error fetching Authentik groups by name '{group_name}': {e}")
                return None
            except json.JSONDecodeError as e:
                logging.error(f"Error decoding JSON for Authentik groups by name '{group_name}': {e}")
                return None

        if not groups_found:
            logging.info(f"No Authentik group found with name '{group_name}'.")
            return None

        if len(groups_found) > 1:
            logging.warning(
                f"Found multiple groups ({len(groups_found)}) with the name '{group_name}'. Returning the first one."
            )

        group_obj = groups_found[0]
        group_pk = group_obj.get("pk")

        if not group_pk:
            logging.error(f"Found group '{group_name}' but it has no PK: {group_obj}")
            return None

        # Step 2: Fetch users for this specific group, with pagination
        users_for_group_pks = []
        users_for_group_objs = []
        current_users_url = f"{self.base_url}/api/v3/core/groups/{group_pk}/users/"
        user_page_count = 0
        logging.info(f"Fetching users for group '{group_name}' (PK: {group_pk}) from {current_users_url}")

        while current_users_url:
            user_page_count += 1
            logging.debug(f"Fetching users page {user_page_count} for group {group_pk} from {current_users_url}")
            try:
                response = requests.get(current_users_url, headers=self.headers)
                response.raise_for_status()
                user_data = response.json()
                page_user_results = user_data.get("results", [])

                for user_detail in page_user_results:
                    users_for_group_pks.append(user_detail.get("pk"))
                    users_for_group_objs.append(user_detail)  # Assuming this is the user object structure

                current_users_url = user_data.get("pagination", {}).get("next")
                if current_users_url:
                    logging.debug(f"Next page for users of group {group_pk}: {current_users_url}")

            except requests.exceptions.RequestException as e:
                logging.error(f"Error fetching users for Authentik group PK {group_pk}: {e}")
                # Return group object with potentially partial user list or empty if preferred
                group_obj["users"] = users_for_group_pks
                group_obj["users_obj"] = users_for_group_objs
                return group_obj  # Or None if failure to get users is critical
            except json.JSONDecodeError as e:
                logging.error(f"Error decoding JSON for users of Authentik group PK {group_pk}: {e}")
                group_obj["users"] = users_for_group_pks
                group_obj["users_obj"] = users_for_group_objs
                return group_obj  # Or None

        group_obj["users"] = users_for_group_pks
        group_obj["users_obj"] = users_for_group_objs

        logging.info(
            f"Successfully fetched group '{group_name}' (PK: {group_pk}) with {len(users_for_group_pks)} users."
        )
        return group_obj

    def add_user_to_group(self, group_pk, user_pk):
        """Adds a user to an Authentik group."""
        if not self.base_url or not self.token:  # Should be caught by __init__
            logging.error("Authentik client not configured.")
            return False
        if not group_pk or user_pk is None:
            logging.error("Group PK and User PK must be provided to add user to group.")
            return False

        # Authentik API for adding user to group by patching the group with user_add_by_pk
        # This is an example, the actual endpoint might differ.
        # The prompt had /add_user/ which is often a POST with payload {"pk": user_pk}
        # Let's use the example from the prompt: POST to /api/v3/core/groups/{group_pk}/add_user/
        url = f"{self.base_url}/api/v3/core/groups/{group_pk}/add_user/"
        payload = {"pk": user_pk}

        # self.headers already includes Content-Type: application/json and Authorization
        logging.info(f"Adding user PK {user_pk} to Authentik group PK {group_pk} at {url}")
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()

            # Typically 204 No Content or 200 OK for this kind of operation
            if 200 <= response.status_code < 300:
                logging.info(f"Successfully added/ensured user PK {user_pk} in group PK {group_pk}.")
                return True
            else:
                # Should be caught by raise_for_status, but as a fallback
                logging.warning(
                    f"Adding user PK {user_pk} to group PK {group_pk} returned "
                    f"status {response.status_code}. Response: {response.text}"
                )
                return False
        except requests.exceptions.HTTPError as e:
            # Specific check for "User is already member of group" or similar
            # This depends on Authentik's exact error response structure
            try:
                error_data = e.response.json()
                if isinstance(error_data, dict) and any(
                    "already a member" in str(val).lower() for val in error_data.values()
                ):
                    logging.info(
                        f"User PK {user_pk} is already a member of group PK {group_pk}. Considered successful."
                    )
                    return True
            except json.JSONDecodeError:
                pass  # Not a JSON error response, or not the one we're looking for

            logging.error(
                f"HTTP error adding user PK {user_pk} to group PK {group_pk}: "
                f"{e.response.status_code} - {e.response.text}"
            )
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception adding user PK {user_pk} to group PK {group_pk}: {e}")
            return False

    def remove_user_from_group(self, group_pk: str, user_pk: int) -> bool:
        """Removes a user from an Authentik group."""
        if not self.base_url or not self.token:
            logging.error("Authentik client not configured.")
            return False
        if not group_pk or user_pk is None:  # user_pk can be 0, so check for None explicitly
            logging.error("Group PK and User PK must be provided to remove user from group.")
            return False

        url = f"{self.base_url}/api/v3/core/groups/{group_pk}/remove_user/"
        payload = {"pk": user_pk}

        logging.info(f"Removing user PK {user_pk} from Authentik group PK {group_pk} at {url}")
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()  # Raises for 4xx/5xx responses

            # Typically 204 No Content or 200 OK for this kind of operation
            if 200 <= response.status_code < 300:
                logging.info(f"Successfully removed user PK {user_pk} from group PK {group_pk}.")
                return True
            else:
                # This case might be redundant if raise_for_status() is effective
                logging.warning(
                    f"Removing user PK {user_pk} from group PK {group_pk} returned "
                    f"status {response.status_code}. Response: {response.text}"
                )
                return False
        except requests.exceptions.HTTPError as e:
            # Check if the user was already not a member (Authentik might return 400 or specific error)
            # This depends on Authentik's exact error response structure for "user not in group"
            # For example, a 400 response with a specific message.
            # if e.response.status_code == 400 and "user not in group" in e.response.text.lower():
            #     logging.info(f"User PK {user_pk} was not a member of group PK {group_pk}. Considered successful removal.")
            #     return True
            logging.error(
                f"HTTP error removing user PK {user_pk} from group PK {group_pk}: "
                f"{e.response.status_code} - {e.response.text}"
            )
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception removing user PK {user_pk} from group PK {group_pk}: {e}")
            return False

    def get_all_users_data(self) -> list[dict]:
        """
        Fetches all users from Authentik, handling pagination.
        Returns a list of dictionaries, each containing user's 'email' and 'attributes'.
        Example: [{'email': 'user@example.com', 'attributes': {'attr1': 'value1'}}]
        Returns an empty list if an error occurs or no users are found.
        """
        if not self.base_url or not self.token:
            logging.error("Authentik client not configured (URL or Token missing).")
            return []

        all_users_data = []
        current_url = f"{self.base_url}/api/v3/core/users/"
        logging.info(f"Fetching Authentik users data from initial URL: {current_url}")

        page_count = 0
        while current_url:
            page_count += 1
            logging.debug(f"Fetching user data page {page_count} from {current_url}")
            try:
                response = requests.get(current_url, headers=self.headers)
                response.raise_for_status()
                data = response.json()

                page_users = data.get("results", [])
                for user in page_users:
                    email = user.get("email")
                    attributes = user.get("attributes", {})  # Default to empty dict if no attributes
                    if email:  # Only include users with an email
                        all_users_data.append({"email": email, "attributes": attributes})

                current_url = data.get("pagination", {}).get("next")
                if current_url:
                    logging.debug(f"Next page for users data: {current_url}")

            except requests.exceptions.RequestException as e:
                logging.error(f"Error fetching Authentik users data from {current_url}: {e}")
                return []  # Return empty list on error
            except json.JSONDecodeError as e:
                logging.error(f"Error decoding JSON from Authentik users data response ({current_url}): {e}")
                return []  # Return empty list on error

        logging.info(f"Fetched data for {len(all_users_data)} users from Authentik over {page_count} pages.")
        return all_users_data


if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv()
    auth_url = os.getenv("AUTHENTIK_URL")
    auth_token = os.getenv("AUTHENTIK_TOKEN")

    if not auth_url or not auth_token:
        print("Please set AUTHENTIK_URL and AUTHENTIK_TOKEN environment variables for this example.")
    else:
        log_format = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"  # noqa: E501
        logging.basicConfig(level=logging.DEBUG, format=log_format)
        print(f"Attempting to connect to Authentik at {auth_url}")
        try:
            client = AuthentikClient(base_url=auth_url, token=auth_token)

            # Test create_group (optional, can be commented out)
            # project_to_create = "Test Sync Script Group"
            # print(f"\nAttempting to create group: '{project_to_create}'")
            # success_create = client.create_group(project_to_create)
            # print(f"Group creation success: {success_create}")

            # Test get_groups_with_users
            print("\nFetching groups and users...")
            groups, user_map = client.get_groups_with_users()
            if groups:
                print(f"Found {len(groups)} groups.")
                # print(f"First group: {json.dumps(groups[0], indent=2)}")
                # print(f"User map sample: {list(user_map.items())[:5]}")

                # Example: Add a user to the first group (if users and groups exist)
                # This part is highly dependent on having actual user/group PKs from your Authentik.
                # Be cautious running this against a live system without knowing valid PKs.
                # if groups and user_map:
                #     first_group_pk = groups[0].get('pk')
                #     if user_map:
                #         first_user_email = list(user_map.keys())[0]
                #         first_user_pk = user_map[first_user_email]

                #         print(f"\nAttempting to add user PK {first_user_pk} ({first_user_email}) to group PK {first_group_pk} ({groups[0].get('name')})...")
                #         add_success = client.add_user_to_group(first_group_pk, first_user_pk)
                #         print(f"Add user to group success: {add_success}")

                #         # Try adding again (should be handled as already member)
                #         print(f"\nAttempting to add user PK {first_user_pk} to group PK {first_group_pk} AGAIN...")
                #         add_success_again = client.add_user_to_group(first_group_pk, first_user_pk)
                #         print(f"Add user to group again success: {add_success_again}")

            else:
                print("No groups found or error during fetch.")

        except ValueError as ve:
            print(f"Configuration error: {ve}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            logging.error("Unexpected error in __main__ example", exc_info=True)
