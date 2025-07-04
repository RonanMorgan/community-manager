import unittest
from unittest.mock import patch, MagicMock

# Ensure clients are importable by adding the project root to sys.path if necessary
# This might be needed if tests are run from a different directory context.
# However, with `python -m pytest`, this is often handled.
# import sys
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from clients.brevo_client import (
    BrevoClient,
)  # Direct import assuming PYTHONPATH is correct or tests are run with pytest

# Load environment variables for testing if not already set (e.g., by a CI/CD pipeline)
# from dotenv import load_dotenv
# load_dotenv()

# Mocked API responses
FAKE_API_URL = "https://api.brevo.example.com/v3"
FAKE_API_KEY = "fakeapikey123"


def mock_brevo_response(status_code, json_data=None, text_data=None, content=None):
    """Helper to create a mock requests.Response object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.text = text_data if text_data is not None else (str(json_data) if json_data else "")
    mock_resp.content = content if content is not None else bytes(mock_resp.text, "utf-8")

    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_resp)
    else:
        mock_resp.raise_for_status.return_value = None  # No error for success codes
    return mock_resp


# Need to import requests for requests.exceptions.HTTPError if not already imported above
import requests


class TestBrevoClient(unittest.TestCase):
    def setUp(self):
        """Set up for each test."""
        self.client = BrevoClient(api_url=FAKE_API_URL, api_key=FAKE_API_KEY)

    def test_initialization(self):
        """Test client initialization."""
        self.assertEqual(self.client.api_url, FAKE_API_URL)
        self.assertEqual(self.client.api_key, FAKE_API_KEY)
        self.assertIn("api-key", self.client.headers)
        self.assertEqual(self.client.headers["api-key"], FAKE_API_KEY)

    def test_initialization_missing_url(self):
        """Test client initialization with missing API URL."""
        with self.assertRaises(ValueError):
            BrevoClient(api_url="", api_key=FAKE_API_KEY)

    def test_initialization_missing_key(self):
        """Test client initialization with missing API key."""
        with self.assertRaises(ValueError):
            BrevoClient(api_url=FAKE_API_URL, api_key="")

    @patch("requests.request")
    def test_get_list_by_name_found(self, mock_request):
        """Test retrieving a list by name when it exists."""
        list_name = "Existing List"
        list_id = 123
        mock_response_data = {"lists": [{"id": list_id, "name": list_name}]}
        mock_request.return_value = mock_brevo_response(200, json_data=mock_response_data)

        result = self.client.get_list_by_name(list_name)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], list_id)
        self.assertEqual(result["name"], list_name)
        mock_request.assert_called_once_with(
            "GET", f"{FAKE_API_URL}/contacts/lists", headers=self.client.headers, json=None, params=None
        )

    @patch("requests.request")
    def test_get_list_by_name_not_found(self, mock_request):
        """Test retrieving a list by name when it does not exist."""
        list_name = "Non Existing List"
        mock_response_data = {"lists": [{"id": 1, "name": "Another List"}]}
        mock_request.return_value = mock_brevo_response(200, json_data=mock_response_data)

        result = self.client.get_list_by_name(list_name)
        self.assertIsNone(result)

    @patch("requests.request")
    def test_get_list_by_name_api_error(self, mock_request):
        """Test retrieving lists when API returns an error."""
        mock_request.return_value = mock_brevo_response(500, json_data={"error": "Server Error"})
        result = self.client.get_list_by_name("Any List")
        self.assertIsNone(result)

    @patch("requests.request")
    def test_create_list_success(self, mock_request):
        """Test creating a new list successfully."""
        list_name = "New List"
        created_list_id = 101
        folder_id = 2

        # Mock the POST request for creating the list
        mock_post_response = mock_brevo_response(201, json_data={"id": created_list_id})
        # Mock the GET request that follows in create_list to fetch the full list object
        mock_get_response = mock_brevo_response(
            200, json_data={"id": created_list_id, "name": list_name, "folderId": folder_id}
        )

        mock_request.side_effect = [mock_post_response, mock_get_response]

        result = self.client.create_list(list_name, folder_id=folder_id)

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], created_list_id)
        self.assertEqual(result["name"], list_name)

        # Check calls to requests.request
        self.assertEqual(mock_request.call_count, 2)
        # First call (POST to create)
        mock_request.assert_any_call(
            "POST",
            f"{FAKE_API_URL}/contacts/lists",
            headers=self.client.headers,
            json={"name": list_name, "folderId": folder_id},
            params=None,
        )
        # Second call (GET to fetch details)
        mock_request.assert_any_call(
            "GET",
            f"{FAKE_API_URL}/contacts/lists/{created_list_id}",
            headers=self.client.headers,
            json=None,
            params=None,
        )

    @patch("requests.request")
    def test_create_list_already_exists(self, mock_request):
        """Test creating a list that already exists (duplicate parameter error)."""
        list_name = "Existing List Name"
        existing_list_id = 202

        # Mock POST response for duplicate
        mock_post_duplicate_response = mock_brevo_response(
            400, json_data={"code": "duplicate_parameter", "message": "List already exists"}
        )
        # Mock GET response for fetching the existing list by name
        mock_get_existing_response = mock_brevo_response(
            200, json_data={"lists": [{"id": existing_list_id, "name": list_name}]}
        )
        # If get_list_by_name is called, it might call GET /contacts/lists, then we need another mock for get_list_by_id
        # The create_list method calls get_list_by_name if duplicate_parameter, which internally calls GET /contacts/lists.
        # Then, if get_list_by_name returns the list object directly, no further call.
        # Let's refine create_list to return the object from get_list_by_name directly if found.
        # Current implementation of create_list calls self.get_list_by_name, which should be fine.

        mock_request.side_effect = [mock_post_duplicate_response, mock_get_existing_response]

        result = self.client.create_list(list_name)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], existing_list_id)
        self.assertEqual(result["name"], list_name)

        self.assertEqual(mock_request.call_count, 2)
        url = f"{FAKE_API_URL}/contacts/lists"
        mock_request.assert_any_call(
            "POST",
            url,
            headers=self.client.headers,
            json={"name": list_name, "folderId": 1},
            params=None,
        )  # noqa: E501
        # This call is from get_list_by_name
        mock_request.assert_any_call("GET", url, headers=self.client.headers, json=None, params=None)  # noqa: E501

    @patch("requests.request")
    def test_get_list_by_id_success(self, mock_request):
        """Test retrieving a list by ID successfully."""
        list_id = 303
        list_name = "Specific List"
        mock_response_data = {"id": list_id, "name": list_name}
        mock_request.return_value = mock_brevo_response(200, json_data=mock_response_data)

        result = self.client.get_list_by_id(list_id)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], list_id)
        mock_request.assert_called_once_with(
            "GET", f"{FAKE_API_URL}/contacts/lists/{list_id}", headers=self.client.headers, json=None, params=None
        )

    @patch("requests.request")
    def test_add_contact_to_list_created(self, mock_request):
        """Test adding a new contact to a list (contact created)."""
        email = "new.contact@example.com"
        list_id = 404
        mock_request.return_value = mock_brevo_response(201)  # 201 Contact created

        success = self.client.add_contact_to_list(email, list_id)
        self.assertTrue(success)
        expected_payload = {"email": email, "listIds": [list_id], "updateEnabled": True}
        mock_request.assert_called_once_with(
            "POST", f"{FAKE_API_URL}/contacts", headers=self.client.headers, json=expected_payload, params=None
        )

    @patch("requests.request")
    def test_add_contact_to_list_updated(self, mock_request):
        """Test adding an existing contact to a list (contact updated)."""
        email = "existing.contact@example.com"
        list_id = 405
        mock_request.return_value = mock_brevo_response(204)  # 204 Contact updated

        success = self.client.add_contact_to_list(email, list_id, attributes={"FIRSTNAME": "Test"})
        self.assertTrue(success)
        expected_payload = {
            "email": email,
            "listIds": [list_id],
            "updateEnabled": True,
            "attributes": {"FIRSTNAME": "Test"},
        }
        mock_request.assert_called_once_with(
            "POST", f"{FAKE_API_URL}/contacts", headers=self.client.headers, json=expected_payload, params=None
        )

    @patch("requests.request")
    def test_add_contact_to_list_failure(self, mock_request):
        """Test failure when adding a contact to a list."""
        email = "fail.contact@example.com"
        list_id = 406
        mock_request.return_value = mock_brevo_response(
            400, json_data={"code": "invalid_parameter", "message": "Email is invalid"}
        )

        success = self.client.add_contact_to_list(email, list_id)
        self.assertFalse(success)

    @patch("requests.request")
    def test_remove_contact_from_list_success(self, mock_request):
        """Test removing a contact from a list successfully."""
        email = "remove.contact@example.com"
        list_id = 505
        encoded_email = requests.utils.quote(email)
        mock_request.return_value = mock_brevo_response(204)  # Successfully updated (unlinked)

        success = self.client.remove_contact_from_list(email, list_id)
        self.assertTrue(success)
        expected_payload = {"unlinkListIds": [list_id]}
        mock_request.assert_called_once_with(
            "PUT",
            f"{FAKE_API_URL}/contacts/{encoded_email}",
            headers=self.client.headers,
            json=expected_payload,
            params=None,
        )

    @patch("requests.request")
    def test_remove_contact_from_list_not_found(self, mock_request):
        """Test removing a contact that is not found."""
        email = "notfound.contact@example.com"
        list_id = 506
        # encoded_email = requests.utils.quote(email) # Removed as unused
        mock_request.return_value = mock_brevo_response(404, json_data={"code": "document_not_found"})

        success = self.client.remove_contact_from_list(email, list_id)
        self.assertFalse(success)  # Or True depending on desired outcome for "not found"

    @patch("requests.request")
    def test_get_contacts_from_list_success(self, mock_request):
        """Test retrieving contacts from a list successfully."""
        list_id = 606
        contacts_data = [{"email": "user1@example.com"}, {"email": "user2@example.com"}]
        mock_response_data = {"contacts": contacts_data, "count": len(contacts_data)}
        mock_request.return_value = mock_brevo_response(200, json_data=mock_response_data)

        result = self.client.get_contacts_from_list(list_id, limit=10, offset=0)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), len(contacts_data))
        self.assertEqual(result[0]["email"], contacts_data[0]["email"])
        mock_request.assert_called_once_with(
            "GET",
            f"{FAKE_API_URL}/contacts/lists/{list_id}/contacts",
            headers=self.client.headers,
            json=None,
            params={"limit": 10, "offset": 0},
        )

    @patch("requests.request")
    def test_get_contacts_from_list_empty(self, mock_request):
        """Test retrieving contacts from an empty list."""
        list_id = 607
        mock_response_data = {"contacts": [], "count": 0}
        mock_request.return_value = mock_brevo_response(200, json_data=mock_response_data)

        result = self.client.get_contacts_from_list(list_id)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 0)

    @patch("requests.request")
    def test_delete_list_success(self, mock_request):
        """Test deleting a list successfully."""
        list_id = 707
        mock_request.return_value = mock_brevo_response(204)  # No content, success

        success = self.client.delete_list(list_id)
        self.assertTrue(success)
        mock_request.assert_called_once_with(
            "DELETE", f"{FAKE_API_URL}/contacts/lists/{list_id}", headers=self.client.headers, json=None, params=None
        )

    @patch("requests.request")
    def test_delete_list_failure(self, mock_request):
        """Test failing to delete a list (e.g., not found or API error)."""
        list_id = 708
        mock_request.return_value = mock_brevo_response(404, json_data={"code": "document_not_found"})

        success = self.client.delete_list(list_id)
        self.assertFalse(success)


if __name__ == "__main__":
    # This allows running the tests directly with `python -m unittest path/to/test_brevo_client.py`
    # or `python path/to/test_brevo_client.py`
    # However, `python -m pytest` is generally preferred for test discovery and execution.
    unittest.main()
