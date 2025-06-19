import unittest
from unittest.mock import patch, Mock
from app.authentik_client import create_group
# Ensure config is loaded or mocked if client relies on it at module level
from app import config

class TestAuthentikClient(unittest.TestCase):

    def setUp(self):
        # Mock config values if they are accessed directly by the client functions
        # and not passed as arguments.
        self.original_auth_url = config.AUTHENTIK_URL
        self.original_auth_token = config.AUTHENTIK_TOKEN
        config.AUTHENTIK_URL = "http://fake-authentik-url.com"
        config.AUTHENTIK_TOKEN = "fake_auth_token"

    def tearDown(self):
        # Restore original config values
        config.AUTHENTIK_URL = self.original_auth_url
        config.AUTHENTIK_TOKEN = self.original_auth_token

    @patch('app.authentik_client.requests.post')
    def test_create_group_success(self, mock_post):
        # Configure the mock to return a successful response
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"pk": "group_id_123", "name": "test_project"}
        mock_post.return_value = mock_response

        project_name = "test_project"
        result = create_group(project_name)

        # Assert that requests.post was called correctly
        expected_url = f"{config.AUTHENTIK_URL}/api/v3/core/groups/"
        expected_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {config.AUTHENTIK_TOKEN}",
        }
        expected_payload = {
            "name": project_name,
            "is_superuser": False,
        }
        mock_post.assert_called_once_with(expected_url, headers=expected_headers, json=expected_payload)

        self.assertTrue(result)

    @patch('app.authentik_client.requests.post')
    def test_create_group_failure_api_error(self, mock_post):
        # Configure the mock to return an error response
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        project_name = "test_project_fail"
        result = create_group(project_name)

        self.assertFalse(result)
        # Optionally, check logs or how the error is handled if more specific behavior is defined
        # For example, if it logs the error status code

    @patch('app.authentik_client.requests.post')
    def test_create_group_failure_request_exception(self, mock_post):
        # Configure the mock to raise a requests.exceptions.RequestException
        mock_post.side_effect = requests.exceptions.RequestException("Connection error")

        project_name = "test_project_exception"
        result = create_group(project_name)

        self.assertFalse(result)

    def test_create_group_missing_config(self):
        # Temporarily unset config for this test
        original_url = config.AUTHENTIK_URL
        original_token = config.AUTHENTIK_TOKEN
        config.AUTHENTIK_URL = None
        config.AUTHENTIK_TOKEN = None

        result = create_group("test_project_no_config")
        self.assertFalse(result)

        # Restore config
        config.AUTHENTIK_URL = original_url
        config.AUTHENTIK_TOKEN = original_token

if __name__ == '__main__':
    # This allows running the tests directly
    # `python -m app.tests.test_authentik_client` from marty_bot directory
    # Or more commonly `python -m unittest discover -s app/tests`

    # Need to make requests available in the scope for the test to run
    import requests
    unittest.main()
