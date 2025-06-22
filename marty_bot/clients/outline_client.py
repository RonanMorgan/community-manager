import requests
import json

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

        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            if response.status_code == 200:  # Outline API often returns 200 on successful creation
                response_data = response.json()
                if response_data.get("data") and response_data.get("data").get("id"):
                    print(
                        f"Outline collection '{project_name}' created successfully. Collection ID: {response_data['data']['id']}"  # noqa: E501
                    )
                    return True
                else:
                    print(
                        f"Outline collection '{project_name}' creation reported success (200), but response data is not as expected: {response.text}"  # noqa: E501
                    )
                    return False
            else:
                error_message = (
                    f"Error creating Outline collection '{project_name}': {response.status_code} - {response.text}"
                )
                try:
                    error_details = response.json()
                    error_message += f" (Details: {error_details.get('message')})"  # noqa: E501
                except json.JSONDecodeError:
                    pass  # No JSON error details
                print(error_message)
                return False
        except requests.exceptions.RequestException as e:
            print(f"Request failed for Outline collection creation '{project_name}': {e}")
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
