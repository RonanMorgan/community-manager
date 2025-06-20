import requests

# import json # No longer used directly in this file
# Removed direct import of config, will be passed during instantiation


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
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def create_group(self, project_name: str) -> bool:
        """
        Creates a group in Authentik.
        :param project_name: The name of the project/group to create.
        :return: True if successful, False otherwise.
        """
        api_url = f"{self.base_url}/api/v3/core/groups/"
        payload = {
            "name": project_name,
            "is_superuser": False,
            # "parent": None,
            # "users": [],
            # "attributes": {},
            # "roles": [],
        }

        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            if response.status_code == 201:
                print(f"Authentik group '{project_name}' created successfully. Group ID: {response.json().get('pk')}")
                return True
            else:
                print(f"Error creating Authentik group '{project_name}': {response.status_code} - {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Request failed for Authentik group creation '{project_name}': {e}")
            return False


if __name__ == "__main__":
    # Example usage:
    # This requires environment variables AUTHENTIK_URL and AUTHENTIK_TOKEN to be set
    # for the example to run.
    from dotenv import load_dotenv
    import os

    load_dotenv()

    auth_url = os.getenv("AUTHENTIK_URL")
    auth_token = os.getenv("AUTHENTIK_TOKEN")

    if not auth_url or not auth_token:
        print("Please set AUTHENTIK_URL and AUTHENTIK_TOKEN environment variables for this example.")
    else:
        print(f"Attempting to connect to Authentik at {auth_url}")
        try:
            client = AuthentikClient(base_url=auth_url, token=auth_token)

            # Test 1: Create a new group
            project_to_create = "Test Project Client OOP"
            print(f"\nAttempting to create group: '{project_to_create}'")
            success = client.create_group(project_to_create)
            print(f"Group creation success: {success}")

            # Test 2: Attempt to create it again (should fail or be handled by Authentik)
            if success:  # Only if first one was successful
                print(f"\nAttempting to create group AGAIN: '{project_to_create}'")
                success_again = client.create_group(project_to_create)
                print(f"Second group creation success: {success_again} (expected False if already exists)")

        except ValueError as ve:
            print(f"Configuration error: {ve}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
