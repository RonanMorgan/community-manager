import unittest
from unittest.mock import patch, Mock
import requests

from clients.mattermost_client import MattermostClient, slugify


class TestMattermostClient(unittest.TestCase):

    def setUp(self):
        self.mock_url = "http://fake-mattermost-url.com"
        self.mock_token = "fake_mm_admin_token"
        self.mock_team_id = "fake_team_id"
        try:
            self.client = MattermostClient(base_url=self.mock_url, token=self.mock_token, team_id=self.mock_team_id)
        except ValueError:
            self.fail("Client instantiation failed in setUp")
        # Suppress client logging during most tests
        # logging.getLogger('app.mattermost_client').setLevel(logging.CRITICAL)

    def test_constructor_success(self):
        self.assertEqual(self.client.base_url, self.mock_url)
        self.assertEqual(self.client.token, self.mock_token)
        self.assertEqual(self.client.team_id, self.mock_team_id)
        self.assertIn(f"Bearer {self.mock_token}", self.client.headers["Authorization"])

    def test_constructor_value_error(self):
        with self.assertRaisesRegex(ValueError, "Mattermost base_url, token, and team_id must be provided."):
            MattermostClient(base_url=None, token="fake", team_id="fake_team")
        with self.assertRaisesRegex(ValueError, "Mattermost base_url, token, and team_id must be provided."):
            MattermostClient(base_url="fake", token=None, team_id="fake_team")
        with self.assertRaisesRegex(ValueError, "Mattermost base_url, token, and team_id must be provided."):
            MattermostClient(base_url="fake", token="fake", team_id=None)

    def test_constructor_url_trailing_slash(self):
        client_with_slash = MattermostClient(
            base_url="http://fake-mm.com/", token=self.mock_token, team_id=self.mock_team_id
        )
        self.assertEqual(client_with_slash.base_url, "http://fake-mm.com")

    @patch("requests.post")
    def test_create_channel_success_default_team_id(self, mock_post_request):
        mock_response = Mock(status_code=201)
        mock_response.json.return_value = {
            "id": "channel_id_123",
            "display_name": "Test Project",
            "name": "test-project",
        }
        mock_post_request.return_value = mock_response
        project_name = "Test Project"
        result = self.client.create_channel(project_name)
        expected_api_url = f"{self.mock_url}/api/v4/channels"
        channel_name_slug = slugify(project_name)
        expected_payload = {
            "team_id": self.mock_team_id,
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
        mock_response = Mock(status_code=201)
        mock_response.json.return_value = {"id": "channel_id_456"}
        mock_post_request.return_value = mock_response
        project_name = "Another Project"
        override_team_id = "override_fake_team_id"
        result = self.client.create_channel(project_name, team_id=override_team_id)
        self.assertTrue(result)
        _, kwargs = mock_post_request.call_args
        self.assertEqual(kwargs["json"]["team_id"], override_team_id)

    @patch("requests.post")
    def test_create_channel_failure_http_error(self, mock_post_request):  # Renamed from api_error
        mock_response = Mock(status_code=400)
        mock_response.json.return_value = {
            "id": "store.sql_channel.save_channel.exists.app_error",
            "message": "Channel exists",
        }
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
        mock_post_request.return_value = mock_response
        result = self.client.create_channel("Test Project Fail")
        self.assertFalse(result)

    @patch("requests.post")
    def test_create_channel_failure_request_exception(self, mock_post_request):
        mock_post_request.side_effect = requests.exceptions.RequestException("Connection timeout")
        result = self.client.create_channel("Test Project Exception")
        self.assertFalse(result)

    # Tests for get_channel_by_name
    @patch("requests.get")
    def test_get_channel_by_name_success(self, mock_get):
        channel_name = "test-channel"
        expected_channel_data = {
            "id": "chan_id_1",
            "name": channel_name,
            "display_name": "Test Channel",
            "team_id": self.mock_team_id,
        }
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = expected_channel_data
        mock_get.return_value = mock_response

        channel = self.client.get_channel_by_name(self.mock_team_id, channel_name)
        self.assertEqual(channel, expected_channel_data)
        expected_url = f"{self.mock_url}/api/v4/teams/{self.mock_team_id}/channels/name/{channel_name}"
        mock_get.assert_called_once_with(expected_url, headers=self.client.headers)

    @patch("requests.get")
    def test_get_channel_by_name_not_found(self, mock_get):
        channel_name = "non-existent-channel"
        mock_response = Mock(status_code=404)
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
        mock_get.return_value = mock_response

        channel = self.client.get_channel_by_name(self.mock_team_id, channel_name)
        self.assertIsNone(channel)

    @patch("requests.get")
    def test_get_channel_by_name_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        channel = self.client.get_channel_by_name(self.mock_team_id, "any-channel")
        self.assertIsNone(channel)

    # Tests for get_users_in_channel
    @patch("requests.get")
    def test_get_users_in_channel_success_no_pagination(self, mock_get):
        channel_id = "chan_id_1"
        mock_users_data = [{"id": "user1", "email": "user1@test.com"}, {"id": "user2", "email": "user2@test.com"}]
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = mock_users_data
        mock_get.return_value = mock_response

        users = self.client.get_users_in_channel(channel_id)
        self.assertEqual(users, mock_users_data)
        expected_url = f"{self.mock_url}/api/v4/users?in_channel={channel_id}&page=0&per_page=200"
        mock_get.assert_called_once_with(expected_url, headers=self.client.headers)

    @patch("requests.get")
    def test_get_users_in_channel_success_with_pagination(self, mock_get):
        channel_id = "chan_id_paginated"
        page1_users = [{"id": f"user{i}", "email": f"user{i}@test.com"} for i in range(200)]
        page2_users = [{"id": "user200", "email": "user200@test.com"}]

        mock_response1 = Mock(status_code=200)
        mock_response1.json.return_value = page1_users
        mock_response2 = Mock(status_code=200)
        mock_response2.json.return_value = page2_users

        mock_get.side_effect = [mock_response1, mock_response2]

        users = self.client.get_users_in_channel(channel_id)
        self.assertEqual(len(users), 201)
        self.assertEqual(users[-1]["id"], "user200")
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_any_call(
            f"{self.mock_url}/api/v4/users?in_channel={channel_id}&page=0&per_page=200", headers=self.client.headers
        )
        mock_get.assert_any_call(
            f"{self.mock_url}/api/v4/users?in_channel={channel_id}&page=1&per_page=200", headers=self.client.headers
        )

    @patch("requests.get")
    def test_get_users_in_channel_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        users = self.client.get_users_in_channel("chan_id_err")
        self.assertEqual(users, [])

    @patch("requests.get")
    def test_get_users_in_channel_empty(self, mock_get):
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = []  # Empty list for first page
        mock_get.return_value = mock_response
        users = self.client.get_users_in_channel("chan_id_empty")
        self.assertEqual(users, [])

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
        self.assertEqual(
            slugify("Test Project with really really long name that will be cut off at sixty four characters"),
            "test-project-with-really-really-long-name-that-will-be-cut-off-a",
        )


if __name__ == "__main__":
    unittest.main()
