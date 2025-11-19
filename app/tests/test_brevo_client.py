from unittest.mock import MagicMock, patch

from clients.brevo_client import (  # Direct import assuming PYTHONPATH is correct or tests are run with pytest
    BrevoClient,
)
import unittest
import requests

# Ensure clients are importable by adding the project root to sys.path if necessary
# This might be needed if tests are run from a different directory context.
# However, with `python -m pytest`, this is often handled.
# import sys
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))


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
    def test_get_lists_by_name_found(self, mock_request):
        """Test retrieving a list by name when it exists."""
        list_name = "Existing List"
        list_id = 123
        mock_response_data = {"lists": [{"id": list_id, "name": list_name}]}
        mock_request.return_value = mock_brevo_response(200, json_data=mock_response_data)

        result = self.client.get_lists(name=list_name)
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["id"], list_id)
        self.assertEqual(result[0]["name"], list_name)
        mock_request.assert_called_once_with(
            "GET",
            f"{FAKE_API_URL}/contacts/lists",
            headers=self.client.headers,
            json=None,
            params={"limit": 50, "offset": 0},
        )

    @patch("requests.request")
    def test_get_lists_by_name_not_found(self, mock_request):
        """Test retrieving a list by name when it does not exist."""
        list_name = "Non Existing List"
        # Simulate pagination where the list is not on the first page
        mock_request.side_effect = [
            mock_brevo_response(200, json_data={"lists": [{"id": 1, "name": "Another List"}] * 50}),
            mock_brevo_response(200, json_data={"lists": []}),  # End of lists
        ]

        result = self.client.get_lists(name=list_name)
        self.assertEqual(result, [])
        self.assertEqual(mock_request.call_count, 2)

    @patch("requests.request")
    def test_get_lists_by_name_api_error(self, mock_request):
        """Test retrieving lists when API returns an error."""
        mock_request.return_value = mock_brevo_response(500, json_data={"error": "Server Error"})
        result = self.client.get_lists(name="Any List")
        self.assertIsNone(result)

    @patch.object(BrevoClient, "get_lists")
    def test_get_list_by_name_found(self, mock_get_lists):
        """Test get_list_by_name when the list is found."""
        list_name = "My List"
        mock_get_lists.return_value = [{"id": 123, "name": list_name}]

        result = self.client.get_list_by_name(list_name)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], list_name)
        mock_get_lists.assert_called_once_with(name=list_name)

    @patch.object(BrevoClient, "get_lists")
    def test_get_list_by_name_not_found(self, mock_get_lists):
        """Test get_list_by_name when the list is not found."""
        mock_get_lists.return_value = []

        result = self.client.get_list_by_name("Unknown List")
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
            200,
            json_data={"id": created_list_id, "name": list_name, "folderId": folder_id},
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
            400,
            json_data={"code": "duplicate_parameter", "message": "List already exists"},
        )
        # Mock GET response for fetching the existing list by name
        mock_get_existing_response = mock_brevo_response(
            200, json_data={"lists": [{"id": existing_list_id, "name": list_name}]}
        )
        # If get_lists is called, it might call GET /contacts/lists, then we need another mock for get_list_by_id
        # The create_list method calls get_lists if duplicate_parameter, which internally calls GET /contacts/lists.
        # Then, if get_lists returns the list object directly, no further call.
        # Let's refine create_list to return the object from get_lists directly if found.
        # Current implementation of create_list calls self.get_lists, which should be fine.

        mock_request.side_effect = [
            mock_post_duplicate_response,
            mock_get_existing_response,
        ]

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
        )
        # This call is from get_list_by_name
        mock_request.assert_any_call(
            "GET",
            url,
            headers=self.client.headers,
            json=None,
            params={"limit": 50, "offset": 0},
        )

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
            "GET",
            f"{FAKE_API_URL}/contacts/lists/{list_id}",
            headers=self.client.headers,
            json=None,
            params=None,
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
            "POST",
            f"{FAKE_API_URL}/contacts",
            headers=self.client.headers,
            json=expected_payload,
            params=None,
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
            "POST",
            f"{FAKE_API_URL}/contacts",
            headers=self.client.headers,
            json=expected_payload,
            params=None,
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

        # The method now returns list of emails and handles all pagination internally
        result_contacts = self.client.get_contacts_from_list(list_id)
        self.assertIsNotNone(result_contacts)
        self.assertEqual(len(result_contacts), len(contacts_data))
        self.assertEqual(result_contacts[0]["email"], contacts_data[0]["email"])
        mock_request.assert_called_once_with(
            "GET",
            f"{FAKE_API_URL}/contacts/lists/{list_id}/contacts",
            headers=self.client.headers,
            json=None,
            # Default params for the new implementation (limit 500, offset 0, sort desc)
            params={"limit": 500, "offset": 0, "sort": "desc"},
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
            "DELETE",
            f"{FAKE_API_URL}/contacts/lists/{list_id}",
            headers=self.client.headers,
            json=None,
            params=None,
        )

    @patch("requests.request")
    def test_delete_list_failure(self, mock_request):
        """Test failing to delete a list (e.g., not found or API error)."""
        list_id = 708
        mock_request.return_value = mock_brevo_response(404, json_data={"code": "document_not_found"})

        success = self.client.delete_list(list_id)
        self.assertFalse(success)

    @patch("requests.request")
    def test_send_transactional_email_success(self, mock_request):
        """Test sending a transactional email successfully."""
        subject = "Test Subject"
        text_content = "Hello, this is a test email."
        sender_email = "sender@example.com"
        sender_name = "Test Sender"
        to_contacts = [
            {"email": "recipient1@example.com"},
            {"email": "recipient2@example.com"},
        ]

        mock_response_data = {"messageId": "some-message-id-123"}
        mock_request.return_value = mock_brevo_response(201, json_data=mock_response_data)

        html_content_example = "<p>Hello, this is a test email.</p>"
        success = self.client.send_transactional_email(
            subject,
            text_content,
            sender_email,
            sender_name,
            to_contacts,
            html_content=html_content_example,
        )
        self.assertTrue(success)

        expected_payload = {
            "sender": {"email": sender_email, "name": sender_name},
            "to": to_contacts,
            "subject": subject,
            "textContent": text_content,
            "htmlContent": html_content_example,
        }
        mock_request.assert_called_once_with(
            "POST",
            f"{FAKE_API_URL}/smtp/email",
            headers=self.client.headers,
            json=expected_payload,
            params=None,
        )

    @patch("requests.request")
    def test_send_transactional_email_success_no_html(self, mock_request):
        """Test sending a transactional email successfully without HTML content."""
        subject = "Test Subject No HTML"
        text_content = "Hello, this is a plain text test email."
        sender_email = "sender.nohtml@example.com"
        sender_name = "Test Sender No HTML"
        to_contacts = [{"email": "recipient.nohtml@example.com"}]

        mock_response_data = {"messageId": "some-message-id-nohtml"}
        mock_request.return_value = mock_brevo_response(
            201, json_data=mock_response_data
        )  # Changed to 201 for explicit success handling in client

        success = self.client.send_transactional_email(
            subject,
            text_content,
            sender_email,
            sender_name,
            to_contacts,
            html_content=None,
        )  # Explicitly None
        self.assertTrue(success)

        expected_payload = {
            "sender": {"email": sender_email, "name": sender_name},
            "to": to_contacts,
            "subject": subject,
            "textContent": text_content,
            # No htmlContent key
        }
        mock_request.assert_called_once_with(
            "POST",
            f"{FAKE_API_URL}/smtp/email",
            headers=self.client.headers,
            json=expected_payload,
            params=None,
        )

    @patch("requests.request")
    def test_send_transactional_email_failure_api_error(self, mock_request):
        """Test failure when sending a transactional email due to API error."""
        mock_request.return_value = mock_brevo_response(400, json_data={"code": "api_error", "message": "Bad request"})

        success = self.client.send_transactional_email(
            "Subject", "Content", "s@e.com", "Sender", [{"email": "r@e.com"}]
        )
        self.assertFalse(success)

    @patch("requests.request")
    def test_send_transactional_email_missing_params(self, mock_request):
        """Test that sending fails if essential parameters are missing."""
        self.assertFalse(
            self.client.send_transactional_email("", "Content", "s@e.com", "Sender", [{"email": "r@e.com"}])
        )
        self.assertFalse(
            self.client.send_transactional_email("Subject", "", "s@e.com", "Sender", [{"email": "r@e.com"}])
        )
        self.assertFalse(
            self.client.send_transactional_email("Subject", "Content", "", "Sender", [{"email": "r@e.com"}])
        )
        self.assertFalse(self.client.send_transactional_email("Subject", "Content", "s@e.com", "Sender", []))
        mock_request.assert_not_called()

    @patch("requests.request")
    def test_get_folder_id_by_name_found(self, mock_request):
        """Test retrieving a folder ID by name when it exists."""
        folder_name = "My Test Folder"
        folder_id = 123
        mock_response_data = {
            "folders": [{"id": folder_id, "name": folder_name}],
            "count": 1,
        }
        mock_request.return_value = mock_brevo_response(200, json_data=mock_response_data)

        result = self.client.get_folder_id_by_name(folder_name)
        self.assertEqual(result, folder_id)
        mock_request.assert_called_once_with(
            "GET",
            f"{FAKE_API_URL}/contacts/folders",
            headers=self.client.headers,
            json=None,
            params={"limit": 50, "offset": 0, "sort": "desc"},
        )

    @patch("requests.request")
    def test_get_folder_id_by_name_not_found(self, mock_request):
        """Test retrieving a folder ID by name when it does not exist."""
        folder_name = "Non Existent Folder"
        mock_response_data = {
            "folders": [{"id": 1, "name": "Another Folder"}],
            "count": 1,
        }
        mock_request.return_value = mock_brevo_response(200, json_data=mock_response_data)

        result = self.client.get_folder_id_by_name(folder_name)
        self.assertIsNone(result)

    @patch("requests.request")
    def test_get_folder_id_by_name_pagination(self, mock_request):
        """Test retrieving a folder ID by name with pagination."""
        folder_name = "Target Folder Page 2"
        folder_id = 789

        # Simulate two pages of responses
        mock_response_page1_data = {
            "folders": [{"id": i, "name": f"Folder {i}"} for i in range(1, 51)],
            "count": 51,  # Total count indicates more pages
        }
        mock_response_page2_data = {
            "folders": [{"id": folder_id, "name": folder_name}],
            "count": 51,
        }

        mock_request.side_effect = [
            mock_brevo_response(200, json_data=mock_response_page1_data),
            mock_brevo_response(200, json_data=mock_response_page2_data),
        ]

        result = self.client.get_folder_id_by_name(folder_name)
        self.assertEqual(result, folder_id)
        self.assertEqual(mock_request.call_count, 2)
        mock_request.assert_any_call(
            "GET",
            f"{FAKE_API_URL}/contacts/folders",
            headers=self.client.headers,
            json=None,
            params={"limit": 50, "offset": 0, "sort": "desc"},
        )
        mock_request.assert_any_call(
            "GET",
            f"{FAKE_API_URL}/contacts/folders",
            headers=self.client.headers,
            json=None,
            params={
                "limit": 50,
                "offset": 50,
                "sort": "desc",
            },  # Offset for second page
        )

    @patch("requests.request")
    def test_get_folder_id_by_name_api_error(self, mock_request):
        """Test retrieving folder ID when API returns an error."""
        mock_request.return_value = mock_brevo_response(500, json_data={"error": "Server Error"})
        result = self.client.get_folder_id_by_name("Any Folder")
        self.assertIsNone(result)

    @patch("requests.request")
    # Removed the patch.object as it was not the correct approach here. We are testing the global requests.request.
    def test_get_contacts_from_list_success_all_pages(self, mock_request_global):
        """Test retrieving all contacts from a list with pagination, reflecting internal limit."""
        list_id = 700
        internal_limit = 500  # As defined in get_contacts_from_list

        # Page 1: 'internal_limit' contacts
        mock_response_page1_data = {
            "contacts": [{"email": f"user{i}@example.com", "id": i} for i in range(internal_limit)],
        }
        # Page 2: 1 contact, this will be less than internal_limit, so stop after this.
        mock_response_page2_data = {
            "contacts": [{"email": "finaluser@example.com", "id": internal_limit}],
        }
        # Page 3: 0 contacts, signifies the end after page 2 was processed (as page 2 was not full)
        # This mock will be hit because page 2 had len(contacts) < internal_limit, so the next call will fetch an empty page.
        # Actually, the loop breaks when len(page_contacts) < limit. So page 3 is not strictly needed if page 2 is the last with data.
        # The logic is: fetch page1 (full), fetch page2 (not full), loop terminates.
        # Let's adjust mock_request_global.side_effect to 2 calls if page 2 is the last one with data and is not full.
        # If page 2 *was* full, then page 3 (empty) would be fetched.

        mock_request_global.side_effect = [
            mock_brevo_response(200, json_data=mock_response_page1_data),  # Page 1 (full)
            mock_brevo_response(200, json_data=mock_response_page2_data),  # Page 2 (partial, last data page)
            # mock_brevo_response(200, json_data={"contacts": []}), # This would be the 3rd call if page 2 was full
        ]

        # Expected: all contacts from page 1 and page 2
        expected_contacts = [{"email": f"user{i}@example.com", "id": i} for i in range(internal_limit)] + [
            {"email": "finaluser@example.com", "id": internal_limit}
        ]

        # Use self.client which is already set up
        result_contacts = self.client.get_contacts_from_list(list_id)

        self.assertIsNotNone(result_contacts)
        self.assertEqual(len(result_contacts), internal_limit + 1)
        self.assertListEqual(result_contacts, expected_contacts)

        # Since page 2 is not full (1 contact < 500 limit), the loop terminates after processing page 2.
        # So, only 2 calls to the API are expected.
        self.assertEqual(mock_request_global.call_count, 2)
        mock_request_global.assert_any_call(
            "GET",
            f"{FAKE_API_URL}/contacts/lists/{list_id}/contacts",
            headers=self.client.headers,  # self.client.headers is fine
            json=None,
            params={"limit": internal_limit, "offset": 0, "sort": "desc"},
        )
        mock_request_global.assert_any_call(
            "GET",
            f"{FAKE_API_URL}/contacts/lists/{list_id}/contacts",
            headers=self.client.headers,
            json=None,
            params={"limit": internal_limit, "offset": internal_limit, "sort": "desc"},
        )
        # The third call for offset: internal_limit + 1 should not happen with this data.

    @patch("requests.request")
    def test_get_contacts_from_list_single_page_less_than_limit(self, mock_request):
        """Test retrieving contacts when total is less than one page limit."""
        list_id = 701
        contacts_data = [{"email": "alpha@example.com"}, {"email": "beta@example.com"}]
        mock_response_data = {"contacts": contacts_data}  # No 'count' or pagination needed
        mock_request.return_value = mock_brevo_response(200, json_data=mock_response_data)

        result_contacts = self.client.get_contacts_from_list(list_id)
        self.assertIsNotNone(result_contacts)
        self.assertEqual(len(result_contacts), 2)
        self.assertEqual(result_contacts[0]["email"], "alpha@example.com")
        mock_request.assert_called_once_with(
            "GET",
            f"{FAKE_API_URL}/contacts/lists/{list_id}/contacts",
            headers=self.client.headers,
            json=None,
            params={"limit": 500, "offset": 0, "sort": "desc"},
        )

    @patch("requests.request")
    def test_get_contacts_from_list_empty_list_from_start(self, mock_request):
        """Test retrieving contacts from an initially empty list."""
        list_id = 702
        mock_response_data = {"contacts": []}  # Empty list
        mock_request.return_value = mock_brevo_response(200, json_data=mock_response_data)

        result_emails = self.client.get_contacts_from_list(list_id)
        self.assertIsNotNone(result_emails)
        self.assertEqual(len(result_emails), 0)
        mock_request.assert_called_once()

    @patch("requests.request")
    def test_get_contacts_from_list_api_error_during_pagination(self, mock_request):
        """Test API error during pagination when retrieving contacts."""
        list_id = 703
        mock_response_page1_data = {"contacts": [{"email": "user1@example.com"} for _ in range(500)]}  # Full page
        mock_request.side_effect = [
            mock_brevo_response(200, json_data=mock_response_page1_data),
            mock_brevo_response(500, json_data={"error": "Server Error"}),  # Error on second page
        ]

        result_emails = self.client.get_contacts_from_list(list_id)
        self.assertIsNone(result_emails)  # Should return None on error
        self.assertEqual(mock_request.call_count, 2)

    @patch("requests.request")
    def test_get_contacts_from_list_contact_without_email(self, mock_request):
        """Test that contacts without an email are skipped."""
        list_id = 704
        contacts_data = [
            {"id": 1, "email": "user1@example.com"},
            {"id": 2},  # Contact without email
            {"id": 3, "email": "user3@example.com"},
        ]
        mock_response_data = {"contacts": contacts_data}
        mock_request.return_value = mock_brevo_response(200, json_data=mock_response_data)

        result_contacts = self.client.get_contacts_from_list(list_id)
        self.assertIsNotNone(result_contacts)
        self.assertEqual(len(result_contacts), 3)
        self.assertEqual(result_contacts[0]["email"], "user1@example.com")
        self.assertEqual(result_contacts[2]["email"], "user3@example.com")

    @patch("requests.request")
    def test_get_contacts_from_list_with_limit_and_offset(self, mock_request):
        mock_response = mock_brevo_response(200, json_data={"contacts": [{"id": 1, "email": "test@example.com"}]})
        mock_request.return_value = mock_response
        contacts = self.client.get_contacts_from_list(1)
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["email"], "test@example.com")
        mock_request.assert_called_with(
            "GET",
            f"{FAKE_API_URL}/contacts/lists/1/contacts",
            headers=self.client.headers,
            json=None,
            params={"limit": 500, "offset": 0, "sort": "desc"},
        )


if __name__ == "__main__":
    # This allows running the tests directly with `python -m unittest path/to/test_brevo_client.py`
    # or `python path/to/test_brevo_client.py`
    # However, `python -m pytest` is generally preferred for test discovery and execution.
    unittest.main()
