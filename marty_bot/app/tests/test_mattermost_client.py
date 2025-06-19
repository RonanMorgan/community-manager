import unittest
from unittest.mock import patch, Mock
from app.mattermost_client import create_channel, slugify
from app import config
import requests # Import for requests.exceptions.RequestException

class TestMattermostClient(unittest.TestCase):

    def setUp(self):
        self.original_mm_url = config.MATTERMOST_URL
        self.original_mm_token = config.MATTERMOST_TOKEN
        self.original_mm_team_id = config.MATTERMOST_TEAM_ID

        config.MATTERMOST_URL = "http://fake-mattermost-url.com"
        config.MATTERMOST_TOKEN = "fake_mm_admin_token"
        config.MATTERMOST_TEAM_ID = "fake_team_id"

    def tearDown(self):
        config.MATTERMOST_URL = self.original_mm_url
        config.MATTERMOST_TOKEN = self.original_mm_token
        config.MATTERMOST_TEAM_ID = self.original_mm_team_id

    @patch('app.mattermost_client.requests.post')
    def test_create_channel_success(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "channel_id_123",
            "display_name": "Test Project",
            "name": "test-project"
        }
        mock_post.return_value = mock_response

        project_name = "Test Project"
        team_id = "test_team_id_override" # Test passing team_id directly

        result = create_channel(project_name, team_id=team_id)

        expected_url = f"{config.MATTERMOST_URL}/api/v4/channels"
        expected_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {config.MATTERMOST_TOKEN}",
        }
        channel_name_slug = slugify(project_name)
        expected_payload = {
            "team_id": team_id,
            "name": channel_name_slug,
            "display_name": project_name,
            "type": "O",
            "purpose": f"Channel for project {project_name}",
            "header": f"Project {project_name}",
        }
        mock_post.assert_called_once_with(expected_url, headers=expected_headers, json=expected_payload)
        self.assertTrue(result)

    @patch('app.mattermost_client.requests.post')
    def test_create_channel_success_uses_config_team_id(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "channel_id_123"}
        mock_post.return_value = mock_response

        project_name = "Test Project Config Team"
        # Not passing team_id, so it should use config.MATTERMOST_TEAM_ID
        result = create_channel(project_name)

        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['json']['team_id'], config.MATTERMOST_TEAM_ID)
        self.assertTrue(result)


    @patch('app.mattermost_client.requests.post')
    def test_create_channel_failure_api_error(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 400 # Bad Request
        mock_response.text = "Error creating channel"
        mock_response.json.return_value = {"id": "store.sql_channel.save_channel.exists.app_error", "message": "Channel exists"}
        mock_post.return_value = mock_response

        project_name = "Test Project Fail"
        result = create_channel(project_name, team_id="any_team_id")
        self.assertFalse(result)

    @patch('app.mattermost_client.requests.post')
    def test_create_channel_failure_request_exception(self, mock_post):
        mock_post.side_effect = requests.exceptions.RequestException("Connection timeout")

        project_name = "Test Project Exception"
        result = create_channel(project_name, team_id="any_team_id")
        self.assertFalse(result)

    def test_create_channel_missing_config_token_url(self):
        original_url = config.MATTERMOST_URL
        original_token = config.MATTERMOST_TOKEN
        config.MATTERMOST_URL = None
        result_no_url = create_channel("Test No URL", team_id="any_team_id")
        self.assertFalse(result_no_url)
        config.MATTERMOST_URL = original_url # restore for next check

        config.MATTERMOST_TOKEN = None
        result_no_token = create_channel("Test No Token", team_id="any_team_id")
        self.assertFalse(result_no_token)

        config.MATTERMOST_TOKEN = original_token # restore fully

    def test_create_channel_missing_team_id(self):
        original_team_id = config.MATTERMOST_TEAM_ID
        config.MATTERMOST_TEAM_ID = None # Unset from config

        # And not passing it as argument
        result = create_channel("Test No TeamID")
        self.assertFalse(result)

        config.MATTERMOST_TEAM_ID = original_team_id # restore

    def test_slugify(self):
        self.assertEqual(slugify("Test Project 123"), "test-project-123")
        self.assertEqual(slugify("  Leading Spaces"), "leading-spaces")
        self.assertEqual(slugify("Trailing Spaces  "), "trailing-spaces")
        self.assertEqual(slugify("Special!@#Chars"), "special-chars")
        self.assertEqual(slugify("Multiple---Hyphens"), "multiple-hyphens")
        self.assertEqual(slugify("Underscores_and_Spaces"), "underscores-and-spaces")
        self.assertEqual(slugify(""), "default-channel-name") # Empty string case
        self.assertEqual(slugify("!@#$"), "default-channel-name") # Only special chars
        long_name = "a" * 70
        expected_long_slug = "a" * 64
        self.assertEqual(slugify(long_name), expected_long_slug)
        self.assertEqual(slugify(" Ends-with-hyphen-"), "ends-with-hyphen")
        self.assertEqual(slugify("-Starts-with-hyphen"), "starts-with-hyphen")

if __name__ == '__main__':
    unittest.main()
