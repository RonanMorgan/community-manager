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
    def test_get_groups_with_users_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        groups, email_map = self.client.get_groups_with_users()
        self.assertEqual(groups, [])
        self.assertEqual(email_map, {})



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
    def test_add_user_to_group_failure_http_error(self, mock_post):
        mock_err_response = Mock(status_code=500)
        mock_err_response.text = "Server Error"
        mock_err_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_err_response)
        mock_post.return_value = mock_err_response
        result = self.client.add_user_to_group("group_pk_1", 123)
        self.assertFalse(result)



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
    def test_remove_user_from_group_failure_http_error(self, mock_post):
        mock_err_response = Mock(status_code=500)
        mock_err_response.text = "Server Error"
        mock_err_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_err_response)
        mock_post.return_value = mock_err_response
        result = self.client.remove_user_from_group("group_pk_1", 123)
        self.assertFalse(result)



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
    def test_get_all_users_data_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        users_data = self.client.get_all_users_data()
        self.assertEqual(users_data, [])




    # Tests for get_all_users_pk_by_email
    @patch("requests.get")
    def test_get_all_users_pk_by_email_success(self, mock_get):
        mock_response_data = {
            "results": [
                {"email": "user1@example.com", "pk": 1},
                {"email": "USER2@example.com", "pk": 2},
                {"username": "user3_no_email", "pk": 3},
            ],
            "pagination": {"next": None},
        }
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = mock_response_data
        mock_get.return_value = mock_response

        pk_map = self.client.get_all_users_pk_by_email()

        self.assertEqual(len(pk_map), 2)
        self.assertEqual(pk_map["user1@example.com"], 1)
        self.assertEqual(pk_map["user2@example.com"], 2)  # Check lowercasing
        self.assertNotIn("user3_no_email", pk_map)

    @patch("requests.get")
    def test_get_all_users_pk_by_email_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        pk_map = self.client.get_all_users_pk_by_email()
        self.assertEqual(pk_map, {})


if __name__ == "__main__":
    unittest.main()
