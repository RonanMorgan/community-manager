import unittest
from unittest.mock import patch, Mock
from app.outline_client import create_group
from app import config
import requests # Import for requests.exceptions.RequestException

class TestOutlineClient(unittest.TestCase):

    def setUp(self):
        self.original_outline_url = config.OUTLINE_URL
        self.original_outline_token = config.OUTLINE_TOKEN
        config.OUTLINE_URL = "http://fake-outline-url.com"
        config.OUTLINE_TOKEN = "fake_outline_token"

    def tearDown(self):
        config.OUTLINE_URL = self.original_outline_url
        config.OUTLINE_TOKEN = self.original_outline_token

    @patch('app.outline_client.requests.post')
    def test_create_group_success(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 200
        # Simulate Outline's successful response structure for collection creation
        mock_response.json.return_value = {
            "data": {
                "id": "collection_id_123",
                "name": "test_project"
            }
        }
        mock_post.return_value = mock_response

        project_name = "test_project"
        result = create_group(project_name)

        expected_url = f"{config.OUTLINE_URL}/api/collections.create"
        expected_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {config.OUTLINE_TOKEN}",
        }
        expected_payload = {
            "name": project_name,
        }
        mock_post.assert_called_once_with(expected_url, headers=expected_headers, json=expected_payload)

        self.assertTrue(result)

    @patch('app.outline_client.requests.post')
    def test_create_group_success_unexpected_response_data(self, mock_post):
        # Test scenario where API returns 200 but data is not as expected
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": None} # Missing 'id' or 'data' itself is missing
        mock_post.return_value = mock_response

        project_name = "test_project_malformed_success"
        result = create_group(project_name)
        self.assertFalse(result) # Should be false if critical data is missing

    @patch('app.outline_client.requests.post')
    def test_create_group_failure_api_error(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 403 # Forbidden, for example
        mock_response.text = "Forbidden error"
        # Simulate json() raising an error or returning error message
        mock_response.json.return_value = {"message": "API key has insufficient permissions."}
        mock_post.return_value = mock_response

        project_name = "test_project_fail_api"
        result = create_group(project_name)
        self.assertFalse(result)

    @patch('app.outline_client.requests.post')
    def test_create_group_failure_request_exception(self, mock_post):
        mock_post.side_effect = requests.exceptions.RequestException("Network error")

        project_name = "test_project_exception"
        result = create_group(project_name)
        self.assertFalse(result)

    def test_create_group_missing_config(self):
        original_url = config.OUTLINE_URL
        original_token = config.OUTLINE_TOKEN
        config.OUTLINE_URL = None
        config.OUTLINE_TOKEN = None

        result = create_group("test_project_no_config")
        self.assertFalse(result)

        config.OUTLINE_URL = original_url
        config.OUTLINE_TOKEN = original_token

if __name__ == '__main__':
    unittest.main()
