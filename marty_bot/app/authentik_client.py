import requests
import json
from app.config import AUTHENTIK_URL, AUTHENTIK_TOKEN

def create_group(project_name: str) -> bool:
    """
    Creates a group in Authentik.
    """
    if not AUTHENTIK_URL or not AUTHENTIK_TOKEN:
        print("Authentik URL or Token not configured.")
        return False

    api_url = f"{AUTHENTIK_URL}/api/v3/core/groups/"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {AUTHENTIK_TOKEN}",
    }
    payload = {
        "name": project_name,
        "is_superuser": False,
        # "parent": None,  # Optional: Specify parent group UUID if needed
        # "users": [],     # Optional: List of user PKs to add to the group
        # "attributes": {},# Optional: Attributes for the group
        # "roles": [],     # Optional: List of role UUIDs to assign to the group
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        if response.status_code == 201:
            print(f"Authentik group '{project_name}' created successfully. Group ID: {response.json().get('pk')}")
            return True
        else:
            print(f"Error creating Authentik group '{project_name}': {response.status_code} - {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Request failed for Authentik group creation '{project_name}': {e}")
        return False

if __name__ == '__main__':
    # Example usage (requires .env to be set up and Authentik running)
    # Ensure you have AUTHENTIK_URL and AUTHENTIK_TOKEN in your .env
    from app.config import load_dotenv
    load_dotenv() # To load .env for direct script execution

    if not AUTHENTIK_URL or not AUTHENTIK_TOKEN:
         print("Please set AUTHENTIK_URL and AUTHENTIK_TOKEN in your .env file for testing.")
    else:
        print(f"Testing Authentik client with URL: {AUTHENTIK_URL}")
        success = create_group("test-project-from-client")
        print(f"Authentik group creation test successful: {success}")

        # Test with a group that might already exist (to see error handling)
        # success_existing = create_group("test-project-from-client")
        # print(f"Authentik existing group creation test (should ideally fail or be handled): {success_existing}")
