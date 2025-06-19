import requests
import json
from app.config import OUTLINE_URL, OUTLINE_TOKEN

def create_group(project_name: str) -> bool:
    """
    Creates a collection (space) in Outline.
    Note: Outline uses "collections" for what might be termed "groups" or "spaces".
    The API endpoint for creating a user group is different from creating a collection.
    This function assumes we want to create a new collection for the project.
    """
    if not OUTLINE_URL or not OUTLINE_TOKEN:
        print("Outline URL or Token not configured.")
        return False

    # Assuming OUTLINE_URL is the base URL like https://app.getoutline.com
    # The endpoint for creating collections is typically /api/collections.create
    api_url = f"{OUTLINE_URL}/api/collections.create"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {OUTLINE_TOKEN}",
    }
    payload = {
        "name": project_name,
        # "description": f"Collection for project {project_name}", # Optional
        # "permission": "read_write", # Optional: "read", "read_write", None (private)
        # "private": False # Optional: if true, only invited members can access
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        if response.status_code == 200: # Outline API often returns 200 on successful creation
            response_data = response.json()
            if response_data.get("data") and response_data.get("data").get("id"):
                print(f"Outline collection '{project_name}' created successfully. Collection ID: {response_data['data']['id']}")
                return True
            else:
                # Success status but unexpected response structure
                print(f"Outline collection '{project_name}' creation reported success, but response data is not as expected: {response.text}")
                return False
        else:
            print(f"Error creating Outline collection '{project_name}': {response.status_code} - {response.text}")
            # Attempt to parse error if JSON
            try:
                error_details = response.json()
                print(f"Error details: {error_details.get('message')}")
            except json.JSONDecodeError:
                pass # No JSON error details
            return False
    except requests.exceptions.RequestException as e:
        print(f"Request failed for Outline collection creation '{project_name}': {e}")
        return False

if __name__ == '__main__':
    # Example usage (requires .env to be set up and Outline accessible)
    from app.config import load_dotenv
    load_dotenv()

    if not OUTLINE_URL or not OUTLINE_TOKEN:
        print("Please set OUTLINE_URL and OUTLINE_TOKEN in your .env file for testing.")
    else:
        print(f"Testing Outline client with URL: {OUTLINE_URL}")
        success = create_group("Test Project Collection")
        print(f"Outline collection creation test successful: {success}")

        # Test with a collection that might already exist (to see error handling)
        # success_existing = create_group("Test Project Collection")
        # print(f"Outline existing collection test (should ideally fail or be handled): {success_existing}")
