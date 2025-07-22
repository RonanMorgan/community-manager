import logging  # Added for client logging visibility if needed during tests
import unittest
from unittest.mock import Mock, patch

import requests
from clients.authentik_client import AuthentikClient


class TestAuthentikClient(unittest.TestCase):
    def setUp(self):
        self.mock_url = "http://fake-authentik-url.com"
        self.mock_token = "fake_auth_token"
        try:
            self.client = AuthentikClient(base_url=self.mock_url, token=self.mock_token)
        except ValueError:
            self.fail("Client instantiation failed in setUp")

        # Suppress client logging during most tests unless explicitly needed
        # logging.getLogger('app.authentik_client').setLevel(logging.CRITICAL)

    def test_constructor_success(self):
        self.assertEqual(self.client.base_url, self.mock_url)
        self.assertEqual(self.client.token, self.mock_token)
        self.assertIn(f"Bearer {self.mock_token}", self.client.headers["Authorization"])
        self.assertEqual(self.client.headers["Accept"], "application/json")
        self.assertEqual(self.client.headers["Content-Type"], "application/json")

    def test_constructor_value_error(self):
        with self.assertRaisesRegex(ValueError, "Authentik base_url and token must be provided."):
            AuthentikClient(base_url=None, token="fake")
        with self.assertRaisesRegex(ValueError, "Authentik base_url and token must be provided."):
            AuthentikClient(base_url="fake", token=None)
        with self.assertRaisesRegex(ValueError, "Authentik base_url and token must be provided."):
            AuthentikClient(base_url="", token="fake")
        with self.assertRaisesRegex(ValueError, "Authentik base_url and token must be provided."):
            AuthentikClient(base_url="fake", token="")

    @patch("requests.post")
    def test_create_group_success(self, mock_post):
        mock_response = Mock(status_code=201)
        mock_response.json.return_value = {"pk": "group_id_123", "name": "test_project"}
        mock_post.return_value = mock_response
        result = self.client.create_group("test_project")
        expected_url = f"{self.mock_url}/api/v3/core/groups/"
        expected_payload = {"name": "test_project", "is_superuser": False}
        mock_post.assert_called_once_with(expected_url, headers=self.client.headers, json=expected_payload)
        self.assertTrue(result)

    @patch("requests.post")
    def test_create_group_failure_http_error(self, mock_post):  # Renamed from api_error
        mock_response = Mock(status_code=400)  # Example: Bad Request
        mock_response.json.return_value = {"name": ["group with this name already exists."]}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
        mock_post.return_value = mock_response
        result = self.client.create_group("test_project_fail")
        self.assertFalse(result)

    @patch("requests.post")
    def test_create_group_failure_request_exception(self, mock_post):
        mock_post.side_effect = requests.exceptions.RequestException("Connection error")
        result = self.client.create_group("test_project_exception")
        self.assertFalse(result)

    def test_constructor_url_trailing_slash(self):
        client_with_slash = AuthentikClient(base_url="http://fake-authentik-url.com/", token=self.mock_token)
        self.assertEqual(client_with_slash.base_url, "http://fake-authentik-url.com")

    # Tests for get_groups_with_users
    @patch("requests.get")
    def test_get_groups_with_users_success_no_pagination(self, mock_get):
        mock_response_data = {
            "results": [
                {
                    "pk": "g1",
                    "name": "Group 1",
                    "users_obj": [
                        {"email": "a@a.com", "pk": 1},
                        {"email": "b@b.com", "pk": 2},
                    ],
                },
                {
                    "pk": "g2",
                    "name": "Group 2",
                    "users_obj": [{"email": "c@c.com", "pk": 3}],
                },
            ],
            "pagination": {"next": None},
        }
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        groups, email_map = self.client.get_groups_with_users()

        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["name"], "Group 1")
        self.assertEqual(len(email_map), 3)
        self.assertEqual(email_map["a@a.com"], 1)
        self.assertEqual(email_map["b@b.com"], 2)
        self.assertEqual(email_map["c@c.com"], 3)
        mock_get.assert_called_once_with(
            f"{self.mock_url}/api/v3/core/groups/?include_users=true",
            headers=self.client.headers,
        )

    @patch("requests.get")
    def test_get_groups_with_users_success_with_pagination(self, mock_get):
        mock_response_page1_data = {
            "results": [
                {
                    "pk": "g1",
                    "name": "Group 1",
                    "users_obj": [{"email": "a@a.com", "pk": 1}],
                }
            ],
            "pagination": {"next": f"{self.mock_url}/api/v3/core/groups/?page=2&include_users=true"},
        }
        mock_response_page2_data = {
            "results": [
                {
                    "pk": "g2",
                    "name": "Group 2",
                    "users_obj": [{"email": "b@b.com", "pk": 2}],
                }
            ],
            "pagination": {"next": None},
        }
        mock_response_page1 = Mock(status_code=200)
        mock_response_page1.json.return_value = mock_response_page1_data
        mock_response_page2 = Mock(status_code=200)
        mock_response_page2.json.return_value = mock_response_page2_data

        mock_get.side_effect = [mock_response_page1, mock_response_page2]

        groups, email_map = self.client.get_groups_with_users()

        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[1]["name"], "Group 2")
        self.assertEqual(len(email_map), 2)
        self.assertEqual(email_map["a@a.com"], 1)
        self.assertEqual(email_map["b@b.com"], 2)
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_any_call(
            f"{self.mock_url}/api/v3/core/groups/?include_users=true",
            headers=self.client.headers,
        )
        mock_get.assert_any_call(
            f"{self.mock_url}/api/v3/core/groups/?page=2&include_users=true",
            headers=self.client.headers,
        )

    @patch("requests.get")
    def test_get_groups_with_users_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        groups, email_map = self.client.get_groups_with_users()
        self.assertEqual(groups, [])
        self.assertEqual(email_map, {})

    @patch("requests.get")
    def test_get_groups_with_users_empty_response(self, mock_get):
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {"results": [], "pagination": {"next": None}}
        mock_get.return_value = mock_response
        groups, email_map = self.client.get_groups_with_users()
        self.assertEqual(groups, [])
        self.assertEqual(email_map, {})

    @patch("requests.get")
    def test_get_groups_with_users_conflicting_email_pk(self, mock_get):
        mock_response_data = {
            "results": [
                {
                    "pk": "g1",
                    "name": "Group 1",
                    "users_obj": [
                        {"email": "a@a.com", "pk": 1},
                        {"email": "a@a.com", "pk": 2},
                    ],
                },
            ],
            "pagination": {"next": None},
        }
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        with patch.object(logging, "warning") as mock_log_warning:
            _, email_map = self.client.get_groups_with_users()
            self.assertEqual(email_map["a@a.com"], 2)  # Uses the latest one
            mock_log_warning.assert_called_once()  # Check if warning was logged

    # Tests for add_user_to_group
    @patch("requests.post")
    def test_add_user_to_group_success(self, mock_post):
        mock_response = Mock(status_code=204)  # Or 200, depending on API
        mock_post.return_value = mock_response
        result = self.client.add_user_to_group("group_pk_1", 123)
        self.assertTrue(result)
        expected_url = f"{self.mock_url}/api/v3/core/groups/group_pk_1/add_user/"
        expected_payload = {"pk": 123}
        mock_post.assert_called_once_with(expected_url, headers=self.client.headers, json=expected_payload)

    @patch("requests.post")
    def test_add_user_to_group_already_member(self, mock_post):
        # Simulate user already member error (e.g., Authentik returns 400 with specific message)
        mock_err_response = Mock(status_code=400)
        mock_err_response.json.return_value = {
            "non_field_errors": ["User is already a member of this group."]
        }  # Example error
        mock_err_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_err_response)
        mock_post.return_value = mock_err_response

        result = self.client.add_user_to_group("group_pk_1", 123)
        self.assertTrue(result)  # Should still be true if "already member" is handled as success

    @patch("requests.post")
    def test_add_user_to_group_failure_http_error(self, mock_post):
        mock_err_response = Mock(status_code=500)
        mock_err_response.text = "Server Error"
        mock_err_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_err_response)
        mock_post.return_value = mock_err_response
        result = self.client.add_user_to_group("group_pk_1", 123)
        self.assertFalse(result)

    @patch("requests.post")
    def test_add_user_to_group_failure_request_exception(self, mock_post):
        mock_post.side_effect = requests.exceptions.RequestException("Network error")
        result = self.client.add_user_to_group("group_pk_1", 123)
        self.assertFalse(result)

    def test_add_user_to_group_missing_pks(self):
        self.assertFalse(self.client.add_user_to_group(None, 123))
        self.assertFalse(self.client.add_user_to_group("group_pk_1", None))

    # Tests for remove_user_from_group
    @patch("requests.post")
    def test_remove_user_from_group_success(self, mock_post):
        mock_response = Mock(status_code=204)  # Or 200, typically 204 for successful removal
        mock_post.return_value = mock_response
        result = self.client.remove_user_from_group("group_pk_1", 123)
        self.assertTrue(result)
        expected_url = f"{self.mock_url}/api/v3/core/groups/group_pk_1/remove_user/"
        expected_payload = {"pk": 123}
        mock_post.assert_called_once_with(expected_url, headers=self.client.headers, json=expected_payload)

    @patch("requests.post")
    def test_remove_user_from_group_user_not_in_group(self, mock_post):
        # Simulate user not in group error (e.g., Authentik returns 400 or specific error)
        # For this test, we'll assume the client doesn't specifically handle "not in group" as success
        # but simply returns False on HTTPError if not caught for a specific "not member" message.
        # If the client were updated to treat "not in group" as a successful removal, this test would change.
        mock_err_response = Mock(status_code=400)
        mock_err_response.text = "User not found in group"  # Example error text
        mock_err_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_err_response)
        mock_post.return_value = mock_err_response

        result = self.client.remove_user_from_group("group_pk_1", 123)
        self.assertFalse(result)  # Default behavior for unhandled HTTPError

    @patch("requests.post")
    def test_remove_user_from_group_failure_http_error(self, mock_post):
        mock_err_response = Mock(status_code=500)
        mock_err_response.text = "Server Error"
        mock_err_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_err_response)
        mock_post.return_value = mock_err_response
        result = self.client.remove_user_from_group("group_pk_1", 123)
        self.assertFalse(result)

    @patch("requests.post")
    def test_remove_user_from_group_failure_request_exception(self, mock_post):
        mock_post.side_effect = requests.exceptions.RequestException("Network error")
        result = self.client.remove_user_from_group("group_pk_1", 123)
        self.assertFalse(result)

    def test_remove_user_from_group_missing_pks(self):
        with patch.object(logging, "error") as mock_log_error:
            self.assertFalse(self.client.remove_user_from_group(None, 123))
            mock_log_error.assert_called_with("Group PK and User PK must be provided to remove user from group.")
        with patch.object(logging, "error") as mock_log_error:
            self.assertFalse(self.client.remove_user_from_group("group_pk_1", None))
            mock_log_error.assert_called_with("Group PK and User PK must be provided to remove user from group.")

    # Tests for get_all_users_data (previously get_all_users_emails)
    @patch("requests.get")
    def test_get_all_users_data_success_no_pagination(self, mock_get):
        mock_response_data = {
            "results": [
                {
                    "email": "user1@example.com",
                    "username": "user1",
                    "attributes": {"ville": "Paris", "exp": 5},
                },
                {
                    "email": "user2@example.com",
                    "username": "user2",
                    "attributes": {"ville": "Lyon"},
                },
                {
                    "email": "user3@example.com",
                    "username": "user3",
                },  # No attributes field
            ],
            "pagination": {"next": None},
        }
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        users_data = self.client.get_all_users_data()

        self.assertEqual(len(users_data), 3)

        expected_user1_data = {
            "email": "user1@example.com",
            "attributes": {"ville": "Paris", "exp": 5},
        }
        expected_user2_data = {
            "email": "user2@example.com",
            "attributes": {"ville": "Lyon"},
        }
        expected_user3_data = {
            "email": "user3@example.com",
            "attributes": {},
        }  # Default to empty dict

        self.assertIn(expected_user1_data, users_data)
        self.assertIn(expected_user2_data, users_data)
        self.assertIn(expected_user3_data, users_data)

        expected_url = f"{self.mock_url}/api/v3/core/users/"
        mock_get.assert_called_once_with(expected_url, headers=self.client.headers)

    @patch("requests.get")
    def test_get_all_users_data_success_with_pagination(self, mock_get):
        mock_response_page1_data = {
            "results": [
                {
                    "email": "user1@example.com",
                    "username": "user1",
                    "attributes": {"framework": "React"},
                }
            ],
            "pagination": {"next": f"{self.mock_url}/api/v3/core/users/?page=2"},
        }
        mock_response_page2_data = {
            "results": [
                {
                    "email": "user2@example.com",
                    "username": "user2",
                    "attributes": {"totem": "Lion"},
                }
            ],
            "pagination": {"next": None},
        }
        mock_response_page1 = Mock(status_code=200)
        mock_response_page1.json.return_value = mock_response_page1_data
        mock_response_page2 = Mock(status_code=200)
        mock_response_page2.json.return_value = mock_response_page2_data

        mock_get.side_effect = [mock_response_page1, mock_response_page2]

        users_data = self.client.get_all_users_data()

        self.assertEqual(len(users_data), 2)
        expected_user1_data = {
            "email": "user1@example.com",
            "attributes": {"framework": "React"},
        }
        expected_user2_data = {
            "email": "user2@example.com",
            "attributes": {"totem": "Lion"},
        }
        self.assertIn(expected_user1_data, users_data)
        self.assertIn(expected_user2_data, users_data)

        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_any_call(f"{self.mock_url}/api/v3/core/users/", headers=self.client.headers)
        mock_get.assert_any_call(f"{self.mock_url}/api/v3/core/users/?page=2", headers=self.client.headers)

    @patch("requests.get")
    def test_get_all_users_data_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        users_data = self.client.get_all_users_data()
        self.assertEqual(users_data, [])

    @patch("requests.get")
    def test_get_all_users_data_json_decode_error(self, mock_get):
        mock_response = Mock(status_code=200)
        import json  # Ensure json is imported for JSONDecodeError

        mock_response.json.side_effect = json.JSONDecodeError("JSON decode error", "doc", 0)
        mock_get.return_value = mock_response
        users_data = self.client.get_all_users_data()
        self.assertEqual(users_data, [])

    @patch("requests.get")
    def test_get_all_users_data_empty_response(self, mock_get):
        mock_response_data = {"results": [], "pagination": {"next": None}}
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response
        users_data = self.client.get_all_users_data()
        self.assertEqual(users_data, [])

    @patch("requests.get")
    def test_get_all_users_data_user_without_email(self, mock_get):
        mock_response_data = {
            "results": [
                {
                    "username": "user1_no_email",
                    "attributes": {"ville": "Inconnue"},
                },  # User without email field
                {"email": "user2@example.com", "username": "user2", "attributes": {}},
            ],
            "pagination": {"next": None},
        }
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        users_data = self.client.get_all_users_data()

        self.assertEqual(len(users_data), 1)  # Only user2 should be included
        expected_user2_data = {"email": "user2@example.com", "attributes": {}}
        self.assertIn(expected_user2_data, users_data)
        # Verify that user1_no_email is not in the results
        for user_data_dict in users_data:
            self.assertNotEqual(user_data_dict.get("attributes", {}).get("ville"), "Inconnue")


if __name__ == "__main__":
    unittest.main()
