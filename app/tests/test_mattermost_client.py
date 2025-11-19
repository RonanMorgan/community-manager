import json  # Added import for json
import unittest
from unittest.mock import Mock, patch, MagicMock

import requests
from clients.mattermost_client import MattermostClient
from libraries.services.mattermost import slugify


def mock_mattermost_response(status_code, json_data=None, text_data=None, content=None, cookies=None):
    """Helper to create a mock requests.Response object for Mattermost tests."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.text = text_data if text_data is not None else (str(json_data) if json_data else "")
    mock_resp.content = content if content is not None else bytes(mock_resp.text, "utf-8")
    mock_resp.cookies = cookies or {}

    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_resp)
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


class TestMattermostClient(unittest.TestCase):
    # Patch requests.get at the class level to affect setUp
    @patch("requests.get")
    def setUp(self, mock_requests_get_for_setup: Mock):  # Renamed arg
        self.mock_url = "http://fake-mattermost-url.com"
        self.mock_token = "fake_mm_admin_token"
        self.mock_team_id = "fake_team_id"

        # Configure the mock for the get_me call within MattermostClient.__init__
        mock_setup_response = Mock(status_code=200)
        mock_setup_response.json.return_value = {
            "id": "bot_user_id_setup",
            "username": "testbot_setup",
        }
        mock_requests_get_for_setup.return_value = mock_setup_response

        try:
            self.client = MattermostClient(base_url=self.mock_url, token=self.mock_token, team_id=self.mock_team_id)
        except ValueError:
            self.fail("Client instantiation failed in setUp")

        # Verify bot_user_id was set during init
        self.assertEqual(self.client.bot_user_id, "bot_user_id_setup")
        # Ensure the mock was called for /users/me
        mock_requests_get_for_setup.assert_called_once_with(
            f"{self.mock_url}/api/v4/users/me", headers=self.client.headers
        )
        # Reset for other tests that might patch requests.get themselves or want a fresh mock
        mock_requests_get_for_setup.reset_mock()

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
            base_url="http://fake-mm.com/",
            token=self.mock_token,
            team_id=self.mock_team_id,
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
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "channel_id_123")

    @patch("requests.post")
    def test_create_channel_success_override_team_id(self, mock_post_request):
        mock_response_data = {"id": "channel_id_456", "name": "another-project"}
        mock_response = Mock(status_code=201)
        mock_response.json.return_value = mock_response_data
        mock_post_request.return_value = mock_response
        project_name = "Another Project"
        override_team_id = "override_fake_team_id"
        result = self.client.create_channel(project_name, team_id=override_team_id)
        self.assertEqual(result, mock_response_data)
        _, kwargs = mock_post_request.call_args
        self.assertEqual(kwargs["json"]["team_id"], override_team_id)

    @patch("requests.post")
    @patch.object(MattermostClient, "get_channel_by_name")  # Mock get_channel_by_name for exists case
    def test_create_channel_failure_http_error_exists(self, mock_get_channel_by_name, mock_post_request):
        project_name = "Existing Project"
        channel_name_slug = slugify(project_name)
        mock_error_response = Mock(status_code=400)  # Typically 400 for "exists" if not handled as 200/201
        mock_error_details = {
            "id": "store.sql_channel.save_channel.exists.app_error",
            "message": "Channel exists",
        }
        mock_error_response.json.return_value = mock_error_details
        mock_error_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_error_response)
        mock_post_request.return_value = mock_error_response

        # Simulate get_channel_by_name returning the existing channel
        existing_channel_data = {
            "id": "existing_channel_id",
            "name": channel_name_slug,
            "display_name": project_name,
        }
        mock_get_channel_by_name.return_value = existing_channel_data

        result = self.client.create_channel(project_name)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "existing_channel_id")
        mock_get_channel_by_name.assert_called_once_with(self.mock_team_id, channel_name_slug)

    @patch("requests.post")
    def test_create_channel_failure_http_error_other(self, mock_post_request):
        mock_response = Mock(status_code=500)  # Some other server error
        mock_response.json.return_value = {
            "id": "internal.server.error",
            "message": "Server blew up",
        }
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
        mock_post_request.return_value = mock_response
        result = self.client.create_channel("Test Project Fail Other")
        self.assertIsNone(result)

    @patch("requests.post")
    def test_create_channel_failure_request_exception(self, mock_post_request):
        mock_post_request.side_effect = requests.exceptions.RequestException("Connection timeout")
        result = self.client.create_channel("Test Project Exception")
        self.assertIsNone(result)

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
        mock_users_data = [
            {"id": "user1", "email": "user1@test.com"},
            {"id": "user2", "email": "user2@test.com"},
        ]
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
            f"{self.mock_url}/api/v4/users?in_channel={channel_id}&page=0&per_page=200",
            headers=self.client.headers,
        )
        mock_get.assert_any_call(
            f"{self.mock_url}/api/v4/users?in_channel={channel_id}&page=1&per_page=200",
            headers=self.client.headers,
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

    @patch("requests.get")
    def test_get_me_success_initialization(self, mock_get_request):
        mock_response = Mock(status_code=200)
        expected_bot_details = {"id": "bot_user_id_123", "username": "mybot"}
        mock_response.json.return_value = expected_bot_details
        mock_get_request.return_value = mock_response

        # Re-initialize client to trigger _initialize_bot_user_id which calls get_me
        # This client's __init__ will call get_me
        client = MattermostClient(base_url=self.mock_url, token=self.mock_token, team_id=self.mock_team_id)

        self.assertEqual(client.bot_user_id, "bot_user_id_123")
        expected_api_url = f"{self.mock_url}/api/v4/users/me"
        mock_get_request.assert_called_once_with(expected_api_url, headers=client.headers)

        # Test direct call to get_me as well (will be second call)
        details = client.get_me()
        self.assertEqual(details, expected_bot_details)
        self.assertEqual(mock_get_request.call_count, 2)

    @patch("requests.get")
    def test_get_me_failure_initialization(self, mock_get_request):
        mock_http_error_response = Mock()
        mock_http_error_response.status_code = 401
        mock_http_error_response.text = "Client error: Unauthorized"

        mock_response = Mock(status_code=401, response=mock_http_error_response)
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "Unauthorized", response=mock_http_error_response
        )
        mock_get_request.return_value = mock_response

        # Re-initialize client; _initialize_bot_user_id should handle failure gracefully
        client = MattermostClient(base_url=self.mock_url, token=self.mock_token, team_id=self.mock_team_id)
        self.assertIsNone(client.bot_user_id)  # Bot ID should be None after failed fetch

        # Direct call should also fail
        details = client.get_me()
        self.assertIsNone(details)
        self.assertEqual(mock_get_request.call_count, 2)  # Once in init, once direct

    @patch("requests.post")
    def test_create_direct_channel_success(self, mock_post_request):
        # Ensure bot_user_id is set on the existing client for this test
        # In real usage, it's set during __init__
        with patch.object(
            self.client,
            "get_me",
            return_value={"id": "bot_id_for_test", "username": "testbot"},
        ):
            self.client._initialize_bot_user_id()  # Manually call to set bot_user_id based on new mock
        self.assertEqual(self.client.bot_user_id, "bot_id_for_test")

        mock_response = Mock(status_code=201)
        expected_dm_channel = {"id": "dm_channel_id_456", "type": "D"}
        mock_response.json.return_value = expected_dm_channel
        mock_post_request.return_value = mock_response

        other_user_id = "other_user_id_789"
        dm_channel_id = self.client.create_direct_channel(other_user_id)

        self.assertEqual(dm_channel_id, "dm_channel_id_456")
        expected_api_url = f"{self.mock_url}/api/v4/channels/direct"
        expected_payload = [self.client.bot_user_id, other_user_id]
        mock_post_request.assert_called_once_with(expected_api_url, headers=self.client.headers, json=expected_payload)

    def test_create_direct_channel_fail_no_bot_id(self):
        original_bot_id = self.client.bot_user_id
        self.client.bot_user_id = None  # Simulate bot_id not initialized
        with patch("requests.post") as mock_post:  # ensure no API call is made
            dm_channel_id = self.client.create_direct_channel("other_user_id_789")
            self.assertIsNone(dm_channel_id)
            mock_post.assert_not_called()
        self.client.bot_user_id = original_bot_id  # Restore

    @patch("clients.mattermost_client.MattermostClient.post_message")
    @patch("clients.mattermost_client.MattermostClient.create_direct_channel")
    def test_send_dm_success(self, mock_create_direct_channel_class, mock_post_message_class):
        self.client.bot_user_id = "bot_for_dm_test"

        target_user_id = "target_user_1"
        dm_message = "Hello there!"
        mock_dm_channel_id = "dm_channel_for_target_1"

        mock_create_direct_channel_class.return_value = mock_dm_channel_id
        mock_post_message_class.return_value = True

        success = self.client.send_dm(target_user_id, dm_message)

        self.assertTrue(success)
        mock_create_direct_channel_class.assert_called_once_with(target_user_id)
        mock_post_message_class.assert_called_once_with(channel_id=mock_dm_channel_id, message=dm_message)

    @patch("clients.mattermost_client.MattermostClient.post_message")
    @patch("clients.mattermost_client.MattermostClient.create_direct_channel")
    def test_send_dm_fail_channel_creation(self, mock_create_direct_channel_class, mock_post_message_class):
        self.client.bot_user_id = "bot_for_dm_test"

        target_user_id = "target_user_2"
        dm_message = "Test DM"
        mock_create_direct_channel_class.return_value = None  # Simulate DM channel creation failure

        success = self.client.send_dm(target_user_id, dm_message)
        self.assertFalse(success)
        mock_create_direct_channel_class.assert_called_once_with(target_user_id)
        mock_post_message_class.assert_not_called()

    @patch("clients.mattermost_client.MattermostClient.post_message")
    @patch("clients.mattermost_client.MattermostClient.create_direct_channel")
    def test_send_dm_fail_post_message(self, mock_create_direct_channel_class, mock_post_message_class):
        self.client.bot_user_id = "bot_for_dm_test"

        target_user_id = "target_user_3"
        dm_message = "Another Test DM"
        mock_dm_channel_id = "dm_channel_for_target_3"

        mock_create_direct_channel_class.return_value = mock_dm_channel_id
        mock_post_message_class.return_value = False  # Simulate post_message failure

        success = self.client.send_dm(target_user_id, dm_message)

        self.assertFalse(success)
        mock_create_direct_channel_class.assert_called_once_with(target_user_id)
        mock_post_message_class.assert_called_once_with(channel_id=mock_dm_channel_id, message=dm_message)

    # Tests for add_user_to_channel
    @patch("requests.post")
    def test_add_user_to_channel_success(self, mock_post_request):
        channel_id = "channel_id_for_add"
        user_id = "user_id_to_add"
        mock_response = Mock(status_code=201)  # 201 Created is success
        mock_response.json.return_value = {"channel_id": channel_id, "user_id": user_id}
        mock_post_request.return_value = mock_response

        result = self.client.add_user_to_channel(channel_id, user_id)
        self.assertTrue(result)
        expected_api_url = f"{self.mock_url}/api/v4/channels/{channel_id}/members"
        expected_payload = {"user_id": user_id}
        mock_post_request.assert_called_once_with(expected_api_url, headers=self.client.headers, json=expected_payload)

    @patch("requests.post")
    def test_add_user_to_channel_already_member(self, mock_post_request):
        channel_id = "channel_id_for_add"
        user_id = "user_id_already_member"

        mock_error_response_content = {
            "id": "api.channel.add_user.already_member.app_error",
            "message": f"User {user_id} is already a member of channel {channel_id}",
            "status_code": 500,  # Mattermost sometimes returns 500 for this
        }
        mock_http_error_response = Mock(status_code=500)  # Or 400, depending on MM version / specific case
        mock_http_error_response.json.return_value = mock_error_response_content
        mock_http_error_response.text = json.dumps(mock_error_response_content)

        mock_post_request.return_value = mock_http_error_response  # Simulate the response object directly
        # Simulate raise_for_status for this specific error
        mock_post_request.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_http_error_response
        )

        result = self.client.add_user_to_channel(channel_id, user_id)
        self.assertTrue(result)  # Should be considered success
        expected_api_url = f"{self.mock_url}/api/v4/channels/{channel_id}/members"
        expected_payload = {"user_id": user_id}
        mock_post_request.assert_called_once_with(expected_api_url, headers=self.client.headers, json=expected_payload)

    @patch("requests.post")
    def test_add_user_to_channel_failure_other_http_error(self, mock_post_request):
        channel_id = "channel_id_for_add"
        user_id = "user_id_http_fail"

        mock_error_response_content = {
            "id": "api.some.other.error",
            "message": "Another error",
        }
        mock_http_error_response = Mock(status_code=403)  # e.g. Forbidden
        mock_http_error_response.json.return_value = mock_error_response_content
        mock_http_error_response.text = json.dumps(mock_error_response_content)

        mock_post_request.return_value = mock_http_error_response
        mock_post_request.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_http_error_response
        )

        result = self.client.add_user_to_channel(channel_id, user_id)
        self.assertFalse(result)

    @patch("requests.post")
    def test_add_user_to_channel_failure_request_exception(self, mock_post_request):
        channel_id = "channel_id_for_add"
        user_id = "user_id_req_ex"
        mock_post_request.side_effect = requests.exceptions.RequestException("Network issue")
        result = self.client.add_user_to_channel(channel_id, user_id)
        self.assertFalse(result)

    def test_add_user_to_channel_missing_ids(self):
        self.assertFalse(self.client.add_user_to_channel("", "user_id"))
        self.assertFalse(self.client.add_user_to_channel("channel_id", ""))
        self.assertFalse(self.client.add_user_to_channel("", ""))

    # Tests for get_channels_for_team
    @patch("requests.get")
    def test_get_channels_for_team_success_mixed_public_private(self, mock_get_request):
        team_id = "team_with_mixed_channels"
        private_channels_data = [
            {
                "id": "private_chan_1",
                "name": "private-1",
                "type": "P",
                "team_id": team_id,
            },
            {
                "id": "shared_chan_A",
                "name": "shared-A",
                "type": "P",
                "team_id": team_id,
            },  # Test deduplication
        ]
        public_channels_data = [
            {
                "id": "public_chan_1",
                "name": "public-1",
                "type": "O",
                "team_id": team_id,
            },
            {
                "id": "public_chan_2",
                "name": "public-2",
                "type": "O",
                "team_id": team_id,
            },
            {
                "id": "shared_chan_A",
                "name": "shared-A",
                "type": "O",
                "team_id": team_id,
            },  # Test deduplication
        ]

        mock_response_private = Mock(status_code=200)
        mock_response_private.json.return_value = private_channels_data
        mock_response_public = Mock(status_code=200)
        mock_response_public.json.return_value = public_channels_data

        # The order of side_effect matters: private first, then public
        mock_get_request.side_effect = [mock_response_private, mock_response_public]

        channels = self.client.get_channels_for_team(team_id)

        self.assertEqual(mock_get_request.call_count, 2)
        mock_get_request.assert_any_call(
            f"{self.mock_url}/api/v4/teams/{team_id}/channels/private",
            headers=self.client.headers,
        )
        mock_get_request.assert_any_call(
            f"{self.mock_url}/api/v4/teams/{team_id}/channels",
            headers=self.client.headers,
        )

        # Expected: p_chan_1, pub_chan_1, pub_chan_2, shared_A (deduplicated)  # noqa: E501
        self.assertEqual(len(channels), 4)
        channel_ids = {c["id"] for c in channels}
        self.assertIn("private_chan_1", channel_ids)
        self.assertIn("public_chan_1", channel_ids)
        self.assertIn("public_chan_2", channel_ids)
        self.assertIn("shared_chan_A", channel_ids)  # Check the shared one is present

    @patch("requests.get")
    def test_get_channels_for_team_only_public(self, mock_get_request):
        team_id = "team_only_public"
        public_channels_data = [
            {"id": "pub_A", "name": "pub-a", "type": "O"},
            {"id": "pub_B", "name": "pub-b", "type": "O"},
        ]
        # Private channels endpoint returns empty list or 404
        mock_response_private_empty = Mock(status_code=200)
        mock_response_private_empty.json.return_value = []
        # mock_response_private_404 = Mock(status_code=404) # Alternative: private channels not found
        # mock_response_private_404.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response_private_404)

        mock_response_public = Mock(status_code=200)
        mock_response_public.json.return_value = public_channels_data

        mock_get_request.side_effect = [
            mock_response_private_empty,
            mock_response_public,
        ]
        # mock_get_request.side_effect = [mock_response_private_404, mock_response_public] # Test with 404 for private

        channels = self.client.get_channels_for_team(team_id)
        self.assertEqual(len(channels), 2)
        channel_ids = {c["id"] for c in channels}
        self.assertIn("pub_A", channel_ids)
        self.assertIn("pub_B", channel_ids)

    @patch("requests.get")
    def test_get_channels_for_team_only_private(self, mock_get_request):
        team_id = "team_only_private"
        private_channels_data = [
            {"id": "priv_X", "name": "priv-x", "type": "P"},
            {"id": "priv_Y", "name": "priv-y", "type": "P"},
        ]
        mock_response_private = Mock(status_code=200)
        mock_response_private.json.return_value = private_channels_data

        mock_response_public_empty = Mock(status_code=200)
        mock_response_public_empty.json.return_value = []

        mock_get_request.side_effect = [
            mock_response_private,
            mock_response_public_empty,
        ]

        channels = self.client.get_channels_for_team(team_id)
        self.assertEqual(len(channels), 2)
        channel_ids = {c["id"] for c in channels}
        self.assertIn("priv_X", channel_ids)
        self.assertIn("priv_Y", channel_ids)

    @patch("requests.get")
    def test_get_channels_for_team_no_channels(self, mock_get_request):
        team_id = "team_no_channels"
        mock_response_empty1 = Mock(status_code=200)
        mock_response_empty1.json.return_value = []
        mock_response_empty2 = Mock(status_code=200)
        mock_response_empty2.json.return_value = []

        mock_get_request.side_effect = [mock_response_empty1, mock_response_empty2]
        channels = self.client.get_channels_for_team(team_id)
        self.assertEqual(len(channels), 0)

    @patch("requests.get")
    def test_get_channels_for_team_api_error_on_private(self, mock_get_request):
        team_id = "team_err_private"
        public_channels_data = [{"id": "pub_C", "name": "pub-c", "type": "O"}]

        mock_private_error = Mock(status_code=500)
        mock_private_error.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_private_error)

        mock_response_public = Mock(status_code=200)
        mock_response_public.json.return_value = public_channels_data

        mock_get_request.side_effect = [mock_private_error, mock_response_public]

        channels = self.client.get_channels_for_team(team_id)
        self.assertEqual(len(channels), 1)  # Should still return public channels
        self.assertEqual(channels[0]["id"], "pub_C")

    @patch("requests.get")
    def test_get_channels_for_team_api_error_on_public(self, mock_get_request):
        team_id = "team_err_public"
        private_channels_data = [{"id": "priv_Z", "name": "priv-z", "type": "P"}]

        mock_response_private = Mock(status_code=200)
        mock_response_private.json.return_value = private_channels_data

        mock_public_error = Mock(status_code=500)
        mock_public_error.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_public_error)

        mock_get_request.side_effect = [mock_response_private, mock_public_error]

        channels = self.client.get_channels_for_team(team_id)
        self.assertEqual(len(channels), 1)  # Should still return private channels
        self.assertEqual(channels[0]["id"], "priv_Z")

    @patch("requests.get")
    def test_get_channels_for_team_api_error_on_both(self, mock_get_request):
        team_id = "team_err_both"

        mock_private_error = Mock(status_code=500)
        mock_private_error.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_private_error)
        mock_public_error = Mock(status_code=500)
        mock_public_error.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_public_error)

        mock_get_request.side_effect = [mock_private_error, mock_public_error]
        channels = self.client.get_channels_for_team(team_id)
        self.assertEqual(len(channels), 0)  # No channels should be returned

    def test_get_channels_for_team_no_team_id(self):
        original_team_id = self.client.team_id
        self.client.team_id = None  # Simulate client not having a default team_id
        # And we don't pass one to the function
        channels = self.client.get_channels_for_team()
        self.assertEqual(channels, [])
        self.client.team_id = original_team_id  # Restore

    @patch("requests.get")
    def test_get_channels_for_team_permission_denied_private(self, mock_get_request):
        team_id = "team_permission_denied_private"
        public_channels_data = [{"id": "pub_D", "name": "pub-d", "type": "O"}]

        # Simulate 403 Forbidden for private channels
        mock_private_forbidden = Mock(status_code=403)
        mock_private_forbidden.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_private_forbidden
        )

        mock_response_public = Mock(status_code=200)
        mock_response_public.json.return_value = public_channels_data

        mock_get_request.side_effect = [mock_private_forbidden, mock_response_public]

        channels = self.client.get_channels_for_team(team_id)
        self.assertEqual(len(channels), 1)  # Should still return public channels
        self.assertEqual(channels[0]["id"], "pub_D")
        # Check logs (optional, requires log capture setup if you want to assert specific log messages)
        # For now, just ensuring the function doesn't crash and returns what it can.

    @patch("requests.get")
    def test_get_channels_for_team_permission_denied_public(self, mock_get_request):
        team_id = "team_permission_denied_public"
        private_channels_data = [{"id": "priv_E", "name": "priv-e", "type": "P"}]

        mock_response_private = Mock(status_code=200)
        mock_response_private.json.return_value = private_channels_data

        # Simulate 403 Forbidden for public channels
        mock_public_forbidden = Mock(status_code=403)
        mock_public_forbidden.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_public_forbidden
        )

        mock_get_request.side_effect = [mock_response_private, mock_public_forbidden]

        channels = self.client.get_channels_for_team(team_id)
        self.assertEqual(len(channels), 1)  # Should still return private channels
        self.assertEqual(channels[0]["id"], "priv_E")

    # Tests for get_user_roles
    @patch("requests.get")
    def test_get_user_roles_success_admin(self, mock_get_request):
        user_id = "admin_user_id"
        expected_roles_data = {"id": user_id, "roles": "system_user system_admin"}
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = expected_roles_data
        mock_get_request.return_value = mock_response

        roles = self.client.get_user_roles(user_id)
        self.assertEqual(roles, ["system_user", "system_admin"])
        expected_url = f"{self.mock_url}/api/v4/users/{user_id}"
        mock_get_request.assert_called_once_with(expected_url, headers=self.client.headers)

    @patch("requests.get")
    def test_get_user_roles_success_user_only(self, mock_get_request):
        user_id = "normal_user_id"
        expected_roles_data = {"id": user_id, "roles": "system_user"}
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = expected_roles_data
        mock_get_request.return_value = mock_response

        roles = self.client.get_user_roles(user_id)
        self.assertEqual(roles, ["system_user"])

    @patch("requests.get")
    def test_get_user_roles_success_no_roles_string(self, mock_get_request):
        user_id = "user_with_no_roles_field"
        # Simulate response where 'roles' field is missing or null
        expected_roles_data = {
            "id": user_id,
            "username": "norolesuser",
        }  # No 'roles' key
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = expected_roles_data
        mock_get_request.return_value = mock_response
        roles = self.client.get_user_roles(user_id)
        self.assertEqual(roles, [])

    @patch("requests.get")
    def test_get_user_roles_success_empty_roles_string(self, mock_get_request):
        user_id = "user_with_empty_roles_field"
        expected_roles_data = {"id": user_id, "roles": ""}  # Empty 'roles' string
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = expected_roles_data
        mock_get_request.return_value = mock_response
        roles = self.client.get_user_roles(user_id)
        self.assertEqual(roles, [])  # Should return empty list, not list with one empty string

    @patch("requests.get")
    def test_get_user_roles_user_not_found(self, mock_get_request):
        user_id = "non_existent_user_id"
        mock_response = Mock(status_code=404)
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
        mock_get_request.return_value = mock_response

        roles = self.client.get_user_roles(user_id)
        self.assertEqual(roles, [])

    @patch("requests.get")
    def test_get_user_roles_api_error(self, mock_get_request):
        user_id = "user_id_api_error"
        mock_get_request.side_effect = requests.exceptions.RequestException("API connection error")
        roles = self.client.get_user_roles(user_id)
        self.assertEqual(roles, [])

    @patch("requests.get")
    def test_get_user_roles_json_decode_error(self, mock_get_request):
        user_id = "user_id_json_error"
        mock_response = Mock(status_code=200)
        mock_response.json.side_effect = json.JSONDecodeError("Syntax error", "doc", 0)
        mock_get_request.return_value = mock_response
        roles = self.client.get_user_roles(user_id)
        self.assertEqual(roles, [])

    def test_get_user_roles_no_user_id(self):
        roles = self.client.get_user_roles("")
        self.assertEqual(roles, [])

    @patch("requests.get")
    def test_list_users_success(self, mock_get):
        page1_users = [{"id": f"user{i}", "email": f"user{i}@test.com"} for i in range(200)]
        page2_users = [{"id": "user200", "email": "user200@test.com"}]

        mock_response1 = Mock(status_code=200)
        mock_response1.json.return_value = page1_users
        mock_response2 = Mock(status_code=200)
        mock_response2.json.return_value = page2_users

        mock_get.side_effect = [mock_response1, mock_response2]

        users = self.client.list_users()
        self.assertEqual(len(users), 201)
        self.assertEqual(users[-1]["id"], "user200")
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_any_call(
            f"{self.mock_url}/api/v4/users?page=0&per_page=200",
            headers=self.client.headers,
        )
        mock_get.assert_any_call(
            f"{self.mock_url}/api/v4/users?page=1&per_page=200",
            headers=self.client.headers,
        )

    @patch("requests.get")
    def test_list_users_http_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.HTTPError(response=Mock(status_code=500, text="Server Error"))
        users = self.client.list_users()
        self.assertIsNone(users)

    @patch("requests.delete")
    def test_delete_user_success(self, mock_delete):
        user_id = "user_to_delete"
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {"status": "ok"}
        mock_delete.return_value = mock_response

        success = self.client.delete_user(user_id)
        self.assertTrue(success)
        expected_url = f"{self.mock_url}/api/v4/users/{user_id}"
        mock_delete.assert_called_once_with(expected_url, headers=self.client.headers)

    @patch("requests.delete")
    def test_delete_user_failure(self, mock_delete):
        user_id = "user_to_delete_fail"
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {"status": "fail"}
        mock_delete.return_value = mock_response

        success = self.client.delete_user(user_id)
        self.assertFalse(success)

    @patch("requests.delete")
    def test_delete_user_http_error(self, mock_delete):
        user_id = "user_to_delete_http_error"
        mock_response = Mock(status_code=403)
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
        mock_delete.return_value = mock_response

        success = self.client.delete_user(user_id)
        self.assertFalse(success)

    def test_delete_user_missing_id(self):
        self.assertFalse(self.client.delete_user(""))


class TestMattermostClientFocalboard(unittest.TestCase):
    @patch("requests.post")
    @patch("requests.get")
    def setUp(self, mock_get, mock_post):
        # Mock get_me for __init__
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"id": "bot_user_id"}

        # Mock login for __init__
        self.mock_user_auth_token = "fake_user_auth_token"
        self.mock_csrf_token = "fake_csrf_token"
        mock_post.return_value.status_code = 200
        mock_post.return_value.cookies = {"MMAUTHTOKEN": self.mock_user_auth_token, "MMCSRF": self.mock_csrf_token}
        mock_post.return_value.raise_for_status.return_value = None

        self.mock_url = "http://fake-mattermost-url.com"
        self.mock_token = "fake_mm_admin_token"
        self.mock_team_id = "fake_team_id"
        self.mock_login_id = "testuser"
        self.mock_password = "testpassword"
        self.mock_template_id = "template_board_id"
        self.mock_new_board_name = "New Project Board"

        self.client = MattermostClient(
            base_url=self.mock_url,
            token=self.mock_token,
            team_id=self.mock_team_id,
            login_id=self.mock_login_id,
            password=self.mock_password,
        )

        mock_get.reset_mock()
        mock_post.reset_mock()

    @patch("requests.get")
    @patch("requests.patch")
    @patch("requests.post")
    def test_create_board_from_template_success(self, mock_post, mock_patch, mock_get):
        # Mock duplicate board call
        mock_post.return_value = mock_mattermost_response(
            201, json_data={"boards": [{"id": "new_board_id", "title": "Copy of template"}]}
        )

        # Mock rename board call
        mock_patch.return_value = mock_mattermost_response(200)

        # Mock get board call
        mock_get.return_value = mock_mattermost_response(
            200, json_data={"id": "new_board_id", "title": self.mock_new_board_name}
        )

        result = self.client.create_board_from_template(
            self.mock_template_id, self.mock_new_board_name, "user_id", "channel_id"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "new_board_id")
        self.assertEqual(result["title"], self.mock_new_board_name)
        mock_patch.assert_called_once_with(
            f"{self.client.base_url}/plugins/focalboard/api/v2/boards/new_board_id",
            headers=self.client._get_focalboard_headers(),
            json={"title": self.mock_new_board_name, "channelId": "channel_id"},
        )

    @patch("requests.post")
    def test_create_board_from_template_duplicate_fails(self, mock_post):
        mock_post.side_effect = requests.exceptions.RequestException("API Error")

        result = self.client.create_board_from_template(
            self.mock_template_id, self.mock_new_board_name, "user_id", "channel_id"
        )
        self.assertIsNone(result)

    @patch("requests.patch")
    @patch("requests.post")
    def test_create_board_from_template_rename_fails(self, mock_post, mock_patch):
        # Mock duplicate board call
        mock_post.return_value = mock_mattermost_response(
            201, json_data={"boards": [{"id": "new_board_id", "title": "Copy of template"}]}
        )

        # Mock rename board call to fail
        mock_patch.side_effect = requests.exceptions.RequestException("API Error")

        result = self.client.create_board_from_template(
            self.mock_template_id, self.mock_new_board_name, "user_id", "channel_id"
        )
        self.assertIsNone(result)

    def test_create_board_from_template_no_tokens(self):
        self.client.user_auth_token = None
        self.client.csrf_token = None
        result = self.client.create_board_from_template(
            self.mock_template_id, self.mock_new_board_name, "user_id", "channel_id"
        )
        self.assertIsNone(result)

    @patch("requests.post")
    def test_add_user_to_board_success(self, mock_post):
        mock_post.return_value = mock_mattermost_response(200)

        success = self.client.add_user_to_board("board_id", "user_id")
        self.assertTrue(success)
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["userId"], "user_id")


if __name__ == "__main__":
    unittest.main()
