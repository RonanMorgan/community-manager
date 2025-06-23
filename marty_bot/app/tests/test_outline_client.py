import unittest
from unittest.mock import patch, Mock
from clients.outline_client import OutlineClient  # Import the class
import requests  # For requests.exceptions.RequestException


class TestOutlineClient(unittest.TestCase):

    def setUp(self):
        self.mock_url = "http://fake-outline-url.com"
        self.mock_token = "fake_outline_token"
        try:
            self.client = OutlineClient(base_url=self.mock_url, token=self.mock_token)
        except ValueError:
            self.fail("Client instantiation failed in setUp")

    def test_constructor_success(self):
        self.assertEqual(self.client.base_url, self.mock_url)
        self.assertEqual(self.client.token, self.mock_token)
        self.assertIn(f"Bearer {self.mock_token}", self.client.headers["Authorization"])

    def test_constructor_value_error(self):
        with self.assertRaises(ValueError) as cm:
            OutlineClient(base_url=None, token="fake")
        self.assertEqual(str(cm.exception), "Outline base_url and token must be provided.")

        with self.assertRaises(ValueError) as cm:
            OutlineClient(base_url="fake", token=None)
        self.assertEqual(str(cm.exception), "Outline base_url and token must be provided.")

    @patch("requests.post")  # Patch requests.post used by the client instance
    def test_create_group_success(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"id": "collection_id_123", "name": "test_project"}}
        mock_post_request.return_value = mock_response

        project_name = "test_project"
        result = self.client.create_group(project_name)

        expected_api_url = f"{self.mock_url}/api/collections.create"
        expected_payload = {
            "name": project_name,
        }
        mock_post_request.assert_called_once_with(expected_api_url, headers=self.client.headers, json=expected_payload)
        self.assertTrue(result)

    @patch("requests.post")
    def test_create_group_success_unexpected_response_data(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": None}  # Malformed success response
        mock_post_request.return_value = mock_response

        project_name = "test_project_malformed_success"
        result = self.client.create_group(project_name)
        self.assertFalse(result)

    @patch("requests.post")
    def test_create_group_failure_api_error(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden error"
        mock_response.json.return_value = {"message": "API key has insufficient permissions."}
        mock_post_request.return_value = mock_response

        project_name = "test_project_fail_api"
        result = self.client.create_group(project_name)
        self.assertFalse(result)

    @patch("requests.post")
    def test_create_group_failure_request_exception(self, mock_post_request):
        mock_post_request.side_effect = requests.exceptions.RequestException("Network error")

        project_name = "test_project_exception"
        result = self.client.create_group(project_name)
        self.assertFalse(result)

    def test_constructor_url_trailing_slash(self):
        client_with_slash = OutlineClient(base_url="http://fake-outline-url.com/", token=self.mock_token)
        self.assertEqual(client_with_slash.base_url, "http://fake-outline-url.com")

    @patch("requests.post")
    def test_get_collection_details_success(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 200
        expected_details = {"id": "coll_id_1", "name": "Test Collection", "urlId": "test-coll"}
        mock_response.json.return_value = {"data": expected_details}
        mock_post_request.return_value = mock_response

        collection_id = "coll_id_1"
        details = self.client.get_collection_details(collection_id)

        self.assertEqual(details, expected_details)
        expected_api_url = f"{self.mock_url}/api/collections.info"
        expected_payload = {"id": collection_id}
        mock_post_request.assert_called_once_with(expected_api_url, headers=self.client.headers, json=expected_payload)

    @patch("requests.post")
    def test_get_collection_details_failure_http_error(self, mock_post_request):
        mock_http_error_response = Mock()
        mock_http_error_response.status_code = 500
        mock_http_error_response.text = "Internal Server Error"

        mock_response = Mock(response=mock_http_error_response) # Main mock response for requests.post
        mock_response.status_code = 500 # Status code on the main response
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Server Error", response=mock_http_error_response)
        mock_post_request.return_value = mock_response

        details = self.client.get_collection_details("coll_id_fail")
        self.assertIsNone(details)

    def test_get_collection_details_no_id(self):
        details = self.client.get_collection_details(None) # type: ignore
        self.assertIsNone(details)
        details = self.client.get_collection_details("")
        self.assertIsNone(details)

    @patch("requests.post")
    def test_get_collection_members_success_no_pagination(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 200
        expected_memberships = [{"userId": "user_id_1"}, {"userId": "user_id_2"}]
        mock_response.json.return_value = {
            "data": {"memberships": expected_memberships, "users": []}, # users part also exists in example
            "pagination": {"offset": 0, "limit": 25} # Mock pagination info
        }
        mock_post_request.return_value = mock_response

        collection_id = "coll_id_members_1"
        member_ids = self.client.get_collection_members(collection_id)

        self.assertEqual(member_ids, ["user_id_1", "user_id_2"])
        expected_api_url = f"{self.mock_url}/api/collections.memberships"
        expected_payload = {"id": collection_id, "offset": 0, "limit": 100}
        mock_post_request.assert_called_once_with(expected_api_url, headers=self.client.headers, json=expected_payload)

    @patch("requests.post")
    def test_get_collection_members_success_with_pagination(self, mock_post_request):
        collection_id = "coll_id_members_paged"
        # Page 1
        mock_response_page1 = Mock()
        mock_response_page1.status_code = 200
        memberships_page1 = [{"userId": f"user_id_{i}"} for i in range(2)] # Max limit is 100, using 2 for test
        mock_response_page1.json.return_value = {
            "data": {"memberships": memberships_page1, "users": []},
            "pagination": {"offset": 0, "limit": 2} # Simulate limit was 2
        }
        # Page 2
        mock_response_page2 = Mock()
        mock_response_page2.status_code = 200
        memberships_page2 = [{"userId": "user_id_2"}] # One user on page 2
        mock_response_page2.json.return_value = {
            "data": {"memberships": memberships_page2, "users": []},
            "pagination": {"offset": 2, "limit": 2}
        }
        mock_post_request.side_effect = [mock_response_page1, mock_response_page2]

        member_ids = self.client.get_collection_members(collection_id, limit=2) # Use limit 2 for test

        self.assertEqual(member_ids, ["user_id_0", "user_id_1", "user_id_2"])
        self.assertEqual(mock_post_request.call_count, 2)

        expected_api_url = f"{self.mock_url}/api/collections.memberships"
        # Check call 1
        mock_post_request.assert_any_call(expected_api_url, headers=self.client.headers, json={"id": collection_id, "offset": 0, "limit": 2})
        # Check call 2 (offset is advanced by number of items returned in page 1)
        mock_post_request.assert_any_call(expected_api_url, headers=self.client.headers, json={"id": collection_id, "offset": 2, "limit": 2})


    @patch("requests.post")
    def test_get_collection_members_empty(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"memberships": [], "users": []}, "pagination": {"offset": 0, "limit": 25}}
        mock_post_request.return_value = mock_response
        member_ids = self.client.get_collection_members("coll_id_empty")
        self.assertEqual(member_ids, [])

    @patch("requests.post")
    def test_get_collection_members_failure_http_error(self, mock_post_request):
        mock_http_error_response = Mock()
        mock_http_error_response.status_code = 403
        mock_http_error_response.text = "Client error: Forbidden"

        mock_response = Mock(response=mock_http_error_response)
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Forbidden", response=mock_http_error_response)
        mock_post_request.return_value = mock_response

        member_ids = self.client.get_collection_members("coll_id_fail_perm")
        self.assertIsNone(member_ids)

    def test_get_collection_members_no_id(self):
        members = self.client.get_collection_members(None) # type: ignore
        self.assertIsNone(members)
        members = self.client.get_collection_members("")
        self.assertIsNone(members)


if __name__ == "__main__":
    unittest.main()
