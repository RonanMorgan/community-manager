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


if __name__ == "__main__":
    unittest.main()
