import unittest
from unittest.mock import patch, Mock
from app.authentik_client import AuthentikClient # Import the class
import requests # For requests.exceptions.RequestException

# No need to mock app.config globally here anymore,
# as URL/token are passed to constructor.

class TestAuthentikClient(unittest.TestCase):

    def setUp(self):
        self.mock_url = "http://fake-authentik-url.com"
        self.mock_token = "fake_auth_token"
        # It's good practice to create a new client for each test if tests might modify its state,
        # or if the client itself is not stateful after init, one instance in setUp is fine.
        # For these clients, they are largely stateless after init.
        try:
            self.client = AuthentikClient(base_url=self.mock_url, token=self.mock_token)
        except ValueError:
            # This shouldn't happen with valid mock_url and mock_token
            self.fail("Client instantiation failed in setUp")


    def test_constructor_success(self):
        self.assertEqual(self.client.base_url, self.mock_url)
        self.assertEqual(self.client.token, self.mock_token)
        self.assertIn(f"Bearer {self.mock_token}", self.client.headers["Authorization"])

    def test_constructor_value_error(self):
        with self.assertRaises(ValueError) as cm:
            AuthentikClient(base_url=None, token="fake")
        self.assertEqual(str(cm.exception), "Authentik base_url and token must be provided.")

        with self.assertRaises(ValueError) as cm:
            AuthentikClient(base_url="fake", token=None)
        self.assertEqual(str(cm.exception), "Authentik base_url and token must be provided.")

        with self.assertRaises(ValueError) as cm:
            AuthentikClient(base_url="", token="fake") # Empty string also an issue
        self.assertEqual(str(cm.exception), "Authentik base_url and token must be provided.")

        with self.assertRaises(ValueError) as cm:
            AuthentikClient(base_url="fake", token="")
        self.assertEqual(str(cm.exception), "Authentik base_url and token must be provided.")


    @patch('requests.post') # Patch requests.post directly as it's used by the client instance
    def test_create_group_success(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"pk": "group_id_123", "name": "test_project"}
        mock_post_request.return_value = mock_response

        project_name = "test_project"
        result = self.client.create_group(project_name)

        expected_api_url = f"{self.mock_url}/api/v3/core/groups/"
        expected_payload = {
            "name": project_name,
            "is_superuser": False,
        }
        # Headers are now part of self.client.headers
        mock_post_request.assert_called_once_with(expected_api_url, headers=self.client.headers, json=expected_payload)
        self.assertTrue(result)

    @patch('requests.post')
    def test_create_group_failure_api_error(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post_request.return_value = mock_response

        project_name = "test_project_fail"
        result = self.client.create_group(project_name)
        self.assertFalse(result)

    @patch('requests.post')
    def test_create_group_failure_request_exception(self, mock_post_request):
        mock_post_request.side_effect = requests.exceptions.RequestException("Connection error")

        project_name = "test_project_exception"
        result = self.client.create_group(project_name)
        self.assertFalse(result)

    # Test for base_url with trailing slash removal by constructor
    def test_constructor_url_trailing_slash(self):
        client_with_slash = AuthentikClient(base_url="http://fake-authentik-url.com/", token=self.mock_token)
        self.assertEqual(client_with_slash.base_url, "http://fake-authentik-url.com")


if __name__ == '__main__':
    unittest.main()
