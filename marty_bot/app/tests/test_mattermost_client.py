import unittest
from unittest.mock import patch, Mock
from app.mattermost_client import MattermostClient, slugify  # Import class and slugify
import requests  # For requests.exceptions.RequestException


class TestMattermostClient(unittest.TestCase):

    def setUp(self):
        self.mock_url = "http://fake-mattermost-url.com"
        self.mock_token = "fake_mm_admin_token"
        self.mock_team_id = "fake_team_id"
        try:
            self.client = MattermostClient(base_url=self.mock_url, token=self.mock_token, team_id=self.mock_team_id)
        except ValueError:
            self.fail("Client instantiation failed in setUp")

    def test_constructor_success(self):
        self.assertEqual(self.client.base_url, self.mock_url)
        self.assertEqual(self.client.token, self.mock_token)
        self.assertEqual(self.client.team_id, self.mock_team_id)
        self.assertIn(f"Bearer {self.mock_token}", self.client.headers["Authorization"])

    def test_constructor_value_error(self):
        with self.assertRaises(ValueError) as cm:
            MattermostClient(base_url=None, token="fake", team_id="fake_team")
        self.assertEqual(str(cm.exception), "Mattermost base_url, token, and team_id must be provided.")

        with self.assertRaises(ValueError) as cm:
            MattermostClient(base_url="fake", token=None, team_id="fake_team")
        self.assertEqual(str(cm.exception), "Mattermost base_url, token, and team_id must be provided.")

        with self.assertRaises(ValueError) as cm:
            MattermostClient(base_url="fake", token="fake", team_id=None)
        self.assertEqual(str(cm.exception), "Mattermost base_url, token, and team_id must be provided.")

    def test_constructor_url_trailing_slash(self):
        client_with_slash = MattermostClient(
            base_url="http://fake-mm.com/", token=self.mock_token, team_id=self.mock_team_id
        )
        self.assertEqual(client_with_slash.base_url, "http://fake-mm.com")

    @patch("requests.post")  # Patch requests.post used by the client instance
    def test_create_channel_success_default_team_id(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "channel_id_123",
            "display_name": "Test Project",
            "name": "test-project",
        }
        mock_post_request.return_value = mock_response

        project_name = "Test Project"
        result = self.client.create_channel(project_name)  # Uses default team_id from client

        expected_api_url = f"{self.mock_url}/api/v4/channels"
        channel_name_slug = slugify(project_name)
        expected_payload = {
            "team_id": self.mock_team_id,  # Default team_id
            "name": channel_name_slug,
            "display_name": project_name,
            "type": "O",
            "purpose": f"Channel for project {project_name}",
            "header": f"Project {project_name}",
        }
        mock_post_request.assert_called_once_with(expected_api_url, headers=self.client.headers, json=expected_payload)
        self.assertTrue(result)

    @patch("requests.post")
    def test_create_channel_success_override_team_id(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "channel_id_456"}
        mock_post_request.return_value = mock_response

        project_name = "Another Project"
        override_team_id = "override_fake_team_id"
        result = self.client.create_channel(project_name, team_id=override_team_id)

        self.assertTrue(result)
        args, kwargs = mock_post_request.call_args
        self.assertEqual(kwargs["json"]["team_id"], override_team_id)

    @patch("requests.post")
    def test_create_channel_failure_api_error(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Error creating channel"
        mock_response.json.return_value = {
            "id": "store.sql_channel.save_channel.exists.app_error",
            "message": "Channel exists",
        }
        mock_post_request.return_value = mock_response

        result = self.client.create_channel("Test Project Fail")
        self.assertFalse(result)

    @patch("requests.post")
    def test_create_channel_failure_request_exception(self, mock_post_request):
        mock_post_request.side_effect = requests.exceptions.RequestException("Connection timeout")

        result = self.client.create_channel("Test Project Exception")
        self.assertFalse(result)

    # test_slugify remains unchanged as it's a module-level function
    def test_slugify(self):
        self.assertEqual(slugify("Test Project 123"), "test-project-123")
        self.assertEqual(slugify("  Leading Spaces"), "leading-spaces")
        self.assertEqual(slugify("Trailing Spaces  "), "trailing-spaces")
        self.assertEqual(slugify("Special!@#Chars"), "special-chars")
        self.assertEqual(slugify("Multiple---Hyphens"), "multiple-hyphens")
        self.assertEqual(slugify("Underscores_and_Spaces"), "underscores-and-spaces")
        self.assertEqual(slugify(""), "default-channel-name")
        self.assertEqual(slugify("!@#$"), "default-channel-name")
        long_name = "a" * 70
        expected_long_slug = "a" * 64
        self.assertEqual(slugify(long_name), expected_long_slug)
        self.assertEqual(slugify(" Ends-with-hyphen-"), "ends-with-hyphen")
        self.assertEqual(slugify("-Starts-with-hyphen"), "starts-with-hyphen")
        # Corrected expected output to match slugify's actual behavior (truncate to 64 chars)
        self.assertEqual(
            slugify("Test Project with really really long name that will be cut off at sixty four characters"),
            "test-project-with-really-really-long-name-that-will-be-cut-off-a",
        )


if __name__ == "__main__":
    unittest.main()
