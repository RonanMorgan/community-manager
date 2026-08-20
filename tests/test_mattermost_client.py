import json  # Added import for json
import unittest
from unittest.mock import Mock, patch, MagicMock

import requests
from clients.mattermost_client import MattermostClient
from clients.mattermost_client import slugify


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
    def test_get_users_in_channel_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        users = self.client.get_users_in_channel("chan_id_err")
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

    def test_slugify_preserve_underscores_variant(self):
        """Real-world regression: on the same Mattermost instance, some
        channels' actual slugs keep underscores instead of turning them
        into hyphens (e.g. "Projet 14_RelaxesPourVivant" ->
        "projet-14_relaxespourvivant"). find_channel_by_name() tries both
        variants as a fallback — this tests the variant itself."""
        self.assertEqual(
            slugify("Projet 14_RelaxesPourVivant", preserve_underscores=True),
            "projet-14_relaxespourvivant",
        )
        self.assertEqual(
            slugify("Underscores_and_Spaces", preserve_underscores=True),
            "underscores_and_spaces",
        )
        # Still lowercases and still turns spaces into hyphens.
        self.assertEqual(slugify("Test Project 123", preserve_underscores=True), "test-project-123")

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
    def test_add_user_to_channel_failure_request_exception(self, mock_post_request):
        channel_id = "channel_id_for_add"
        user_id = "user_id_req_ex"
        mock_post_request.side_effect = requests.exceptions.RequestException("Network issue")
        result = self.client.add_user_to_channel(channel_id, user_id)
        self.assertFalse(result)


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
            f"{self.mock_url}/api/v4/teams/{team_id}/channels/private?page=0&per_page=200",
            headers=self.client.headers,
        )
        mock_get_request.assert_any_call(
            f"{self.mock_url}/api/v4/teams/{team_id}/channels?page=0&per_page=200",
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
    def test_get_channels_for_team_paginates_across_multiple_pages(self, mock_get_request):
        """Regression test: get_channels_for_team() used to only fetch the first
        page (up to per_page=200) of public/private channels. A team with more
        than per_page channels of one type must have every page fetched."""
        team_id = "team_many_channels"

        # 200 private channels on page 0 (== per_page, so a page 1 fetch must follow),
        # then a shorter page 1 (2 channels) signaling the end.
        private_page0 = [{"id": f"priv_{i}", "type": "P", "team_id": team_id} for i in range(200)]
        private_page1 = [{"id": "priv_200", "type": "P", "team_id": team_id},
                          {"id": "priv_201", "type": "P", "team_id": team_id}]
        # No public channels at all.
        public_page0 = []

        mock_get_request.side_effect = [
            self._json_response(private_page0),
            self._json_response(private_page1),
            self._json_response(public_page0),
        ]

        channels = self.client.get_channels_for_team(team_id)

        self.assertEqual(mock_get_request.call_count, 3)
        called_urls = [call.args[0] for call in mock_get_request.call_args_list]
        self.assertIn(f"{self.mock_url}/api/v4/teams/{team_id}/channels/private?page=0&per_page=200", called_urls)
        self.assertIn(f"{self.mock_url}/api/v4/teams/{team_id}/channels/private?page=1&per_page=200", called_urls)
        self.assertEqual(len(channels), 202)  # all private channels across both pages

    @staticmethod
    def _json_response(payload):
        resp = Mock(status_code=200)
        resp.json.return_value = payload
        return resp





        # Check logs (optional, requires log capture setup if you want to assert specific log messages)
        # For now, just ensuring the function doesn't crash and returns what it can.


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
    def test_get_user_roles_api_error(self, mock_get_request):
        user_id = "user_id_api_error"
        mock_get_request.side_effect = requests.exceptions.RequestException("API connection error")
        roles = self.client.get_user_roles(user_id)
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

    @patch("requests.post")
    def test_search_channels_for_team_success(self, mock_post):
        mock_post.return_value = mock_mattermost_response(
            200, json_data=[{"id": "chan-1", "display_name": "Projet 14_IFP"}]
        )

        results = self.client.search_channels_for_team("team_id", "Projet 14")

        self.assertEqual(len(results), 1)
        mock_post.assert_called_once_with(
            f"{self.mock_url}/api/v4/teams/team_id/channels/search",
            headers=self.client.headers,
            json={"term": "Projet 14"},
        )

    @patch("requests.post")
    def test_search_channels_for_team_empty_term_returns_empty_list_without_request(self, mock_post):
        results = self.client.search_channels_for_team("team_id", "")
        self.assertEqual(results, [])
        mock_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
