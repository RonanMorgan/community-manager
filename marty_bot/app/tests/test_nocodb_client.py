import unittest
from unittest.mock import MagicMock, patch

# import os # Removed as it's unused in test logic, only in example main
import requests
from clients.nocodb_client import NocoDBClient

# Helper to load .env for local testing if NocoDBClient's main example is run
# from dotenv import load_dotenv
# load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))


class TestNocoDBClient(unittest.TestCase):
    def setUp(self):
        self.nocodb_url = "http://fake-nocodb.com"
        self.token = "fake-token"
        self.client = NocoDBClient(nocodb_url=self.nocodb_url, token=self.token)
        self.base_id_test = "p_testbaseid"
        self.user_id_test = "us_testuserid"
        self.email_test = "test@example.com"

    def test_initialization(self):
        self.assertEqual(self.client.base_url, self.nocodb_url)
        self.assertIn("xc-token", self.client.headers)
        self.assertEqual(self.client.headers["xc-token"], self.token)

    def test_initialization_failure(self):
        with self.assertRaises(ValueError):
            NocoDBClient(nocodb_url="", token="fake-token")
        with self.assertRaises(ValueError):
            NocoDBClient(nocodb_url="http://fake.com", token="")

    @patch("clients.nocodb_client.requests.request")
    def test_make_request_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "success"}
        mock_response.content = True  # Ensure content is not falsey for json() call
        mock_request.return_value = mock_response

        response = self.client._make_request("get", "test_endpoint")
        self.assertEqual(response, {"data": "success"})
        mock_request.assert_called_once()

    @patch("clients.nocodb_client.requests.request")
    def test_make_request_http_error(self, mock_request):
        mock_http_error = requests.exceptions.HTTPError("HTTP Error")
        # Ensure the mock error has a response attribute for the logger
        mock_http_error.response = MagicMock()
        mock_http_error.response.status_code = 400
        mock_http_error.response.text = "Bad Request from mock"

        mock_response_obj = MagicMock()  # This is what requests.request would return
        mock_response_obj.raise_for_status.side_effect = mock_http_error
        # We don't need to set status_code or text on mock_response_obj itself if raise_for_status is the one throwing
        mock_request.return_value = mock_response_obj

        response = self.client._make_request("get", "test_endpoint")
        self.assertIsNone(response)

    @patch("clients.nocodb_client.requests.request")
    def test_make_request_request_exception(self, mock_request):
        mock_request.side_effect = requests.exceptions.RequestException("Request Failed")
        response = self.client._make_request("get", "test_endpoint")
        self.assertIsNone(response)

    @patch("clients.nocodb_client.requests.request")
    def test_make_request_json_decode_error(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = True
        mock_response.json.side_effect = ValueError("JSON Decode Error")  # ValueError is base for JSONDecodeError
        mock_request.return_value = mock_response

        response = self.client._make_request("get", "test_endpoint")
        self.assertIsNone(response)

    @patch.object(NocoDBClient, "_make_request")
    def test_create_base_success(self, mock_make_request):
        mock_make_request.return_value = {"id": "p_newbase", "title": "New Test Base"}
        base_title = "New Test Base"
        response = self.client.create_base(base_title, "Test Description")
        self.assertIsNotNone(response)
        self.assertEqual(response["title"], base_title)
        mock_make_request.assert_called_once_with(
            "post",
            "projects/",
            json={"title": base_title, "description": "Test Description"},
        )

    @patch.object(NocoDBClient, "_make_request")
    def test_create_base_failure(self, mock_make_request):
        mock_make_request.return_value = None  # Simulate API failure
        response = self.client.create_base("Fail Base")
        self.assertIsNone(response)

    @patch.object(NocoDBClient, "_make_request")
    def test_get_base_by_title_found(self, mock_make_request):
        base_title_to_find = "Existing Base"
        mock_make_request.return_value = {
            "list": [
                {"id": "p_other", "title": "Other Base"},
                {"id": self.base_id_test, "title": base_title_to_find},
            ]
        }
        response = self.client.get_base_by_title(base_title_to_find)
        self.assertIsNotNone(response)
        self.assertEqual(response["title"], base_title_to_find)
        mock_make_request.assert_called_once_with("get", "projects/")

    @patch.object(NocoDBClient, "_make_request")
    def test_get_base_by_title_not_found(self, mock_make_request):
        mock_make_request.return_value = {"list": [{"id": "p_other", "title": "Other Base"}]}
        response = self.client.get_base_by_title("Non Existent Base")
        self.assertIsNone(response)

    @patch.object(NocoDBClient, "_make_request")
    def test_get_base_by_title_api_failure(self, mock_make_request):
        mock_make_request.return_value = None  # Simulate API failure returning list
        response = self.client.get_base_by_title("Any Base")
        self.assertIsNone(response)

    @patch.object(NocoDBClient, "_make_request")
    def test_invite_user_to_base_success(self, mock_make_request):
        mock_make_request.return_value = {"msg": "The user has been invited successfully"}
        success = self.client.invite_user_to_base(self.base_id_test, self.email_test, "viewer")
        self.assertTrue(success)
        mock_make_request.assert_called_once_with(
            "post",
            f"projects/{self.base_id_test}/users",
            json={"email": self.email_test, "roles": "viewer"},
        )

    @patch.object(NocoDBClient, "_make_request")
    def test_invite_user_to_base_failure(self, mock_make_request):
        mock_make_request.return_value = None  # Simulate API failure
        success = self.client.invite_user_to_base(self.base_id_test, self.email_test, "viewer")
        self.assertFalse(success)

    @patch.object(NocoDBClient, "_make_request")
    def test_update_base_user_success(self, mock_make_request):
        mock_make_request.return_value = {"msg": "The user has been updated successfully"}
        success = self.client.update_base_user(self.base_id_test, self.user_id_test, "editor")
        self.assertTrue(success)
        mock_make_request.assert_called_once_with(
            "patch",
            f"projects/{self.base_id_test}/users/{self.user_id_test}",
            json={"roles": "editor"},
        )

    @patch.object(NocoDBClient, "_make_request")
    def test_update_base_user_failure(self, mock_make_request):
        mock_make_request.return_value = None
        success = self.client.update_base_user(self.base_id_test, self.user_id_test, "editor")
        self.assertFalse(success)

    @patch.object(NocoDBClient, "_make_request")
    def test_list_base_users_success(self, mock_make_request):
        expected_users = [{"id": self.user_id_test, "email": self.email_test, "roles": "viewer"}]
        mock_make_request.return_value = {"users": {"list": expected_users, "pageInfo": {}}}
        users = self.client.list_base_users(self.base_id_test)
        self.assertEqual(users, expected_users)
        mock_make_request.assert_called_once_with("get", f"projects/{self.base_id_test}/users")

    @patch.object(NocoDBClient, "_make_request")
    def test_list_base_users_empty(self, mock_make_request):
        mock_make_request.return_value = {"users": {"list": [], "pageInfo": {}}}
        users = self.client.list_base_users(self.base_id_test)
        self.assertEqual(users, [])

    @patch.object(NocoDBClient, "_make_request")
    def test_list_base_users_failure(self, mock_make_request):
        mock_make_request.return_value = None
        users = self.client.list_base_users(self.base_id_test)
        self.assertEqual(users, [])

    @patch.object(NocoDBClient, "update_base_user")  # delete_base_user calls update_base_user
    def test_delete_base_user_success(self, mock_update_base_user):
        mock_update_base_user.return_value = True
        success = self.client.delete_base_user(self.base_id_test, self.user_id_test)
        self.assertTrue(success)
        mock_update_base_user.assert_called_once_with(self.base_id_test, self.user_id_test, role="no-access")

    @patch.object(NocoDBClient, "update_base_user")
    def test_delete_base_user_failure(self, mock_update_base_user):
        mock_update_base_user.return_value = False
        success = self.client.delete_base_user(self.base_id_test, self.user_id_test)
        self.assertFalse(success)

    @patch.object(NocoDBClient, "list_base_users")
    def test_get_user_by_email_in_base_found(self, mock_list_base_users):
        user_obj = {
            "id": self.user_id_test,
            "email": self.email_test,
            "roles": "viewer",
        }
        mock_list_base_users.return_value = [
            user_obj,
            {"id": "other_id", "email": "other@example.com"},
        ]

        found_user = self.client.get_user_by_email_in_base(self.base_id_test, self.email_test)
        self.assertEqual(found_user, user_obj)
        mock_list_base_users.assert_called_once_with(self.base_id_test)

    @patch.object(NocoDBClient, "list_base_users")
    def test_get_user_by_email_in_base_not_found(self, mock_list_base_users):
        mock_list_base_users.return_value = [{"id": "other_id", "email": "other@example.com"}]
        found_user = self.client.get_user_by_email_in_base(self.base_id_test, self.email_test)
        self.assertIsNone(found_user)

    @patch.object(NocoDBClient, "list_base_users")
    def test_get_user_by_email_in_base_case_insensitive(self, mock_list_base_users):
        user_obj = {
            "id": self.user_id_test,
            "email": "Test@Example.com",
            "roles": "viewer",
        }  # Email with different case
        mock_list_base_users.return_value = [user_obj]

        found_user = self.client.get_user_by_email_in_base(
            self.base_id_test, self.email_test.lower()
        )  # Search with lowercase
        self.assertEqual(found_user, user_obj)

    @patch.object(NocoDBClient, "list_bases")
    @patch.object(NocoDBClient, "list_base_users")
    def test_list_users_success(self, mock_list_base_users, mock_list_bases):
        mock_list_bases.return_value = {"list": [{"id": "base1"}, {"id": "base2"}]}
        mock_list_base_users.side_effect = [
            [{"id": "user1", "email": "user1@test.com"}, {"id": "user2", "email": "user2@test.com"}],
            [{"id": "user2", "email": "user2@test.com"}, {"id": "user3", "email": "user3@test.com"}],
        ]

        users = self.client.list_users()
        self.assertIsNotNone(users)
        self.assertEqual(len(users), 3)
        emails = {user["email"] for user in users}
        self.assertIn("user1@test.com", emails)
        self.assertIn("user2@test.com", emails)
        self.assertIn("user3@test.com", emails)

    @patch.object(NocoDBClient, "list_bases")
    def test_list_users_no_bases(self, mock_list_bases):
        mock_list_bases.return_value = {"list": []}
        users = self.client.list_users()
        self.assertEqual(users, [])

    @patch.object(NocoDBClient, "list_bases")
    @patch.object(NocoDBClient, "list_base_users")
    def test_list_users_one_base_no_users(self, mock_list_base_users, mock_list_bases):
        mock_list_bases.return_value = {"list": [{"id": "base1"}]}
        mock_list_base_users.return_value = []
        users = self.client.list_users()
        self.assertEqual(users, [])

    @patch.object(NocoDBClient, "_make_request")
    def test_delete_user_success(self, mock_make_request):
        mock_make_request.return_value = {"msg": "The user has been deleted successfully"}
        success = self.client.delete_user(self.base_id_test, self.user_id_test)
        self.assertTrue(success)
        mock_make_request.assert_called_once_with("delete", f"projects/{self.base_id_test}/users/{self.user_id_test}")

    @patch.object(NocoDBClient, "_make_request")
    def test_delete_user_failure(self, mock_make_request):
        mock_make_request.return_value = {"msg": "Some error"}
        success = self.client.delete_user(self.base_id_test, self.user_id_test)
        self.assertFalse(success)

    def test_delete_user_missing_ids(self):
        self.assertFalse(self.client.delete_user(None, self.user_id_test))
        self.assertFalse(self.client.delete_user(self.base_id_test, None))
        self.assertFalse(self.client.delete_user("", self.user_id_test))
        self.assertFalse(self.client.delete_user(self.base_id_test, ""))


if __name__ == "__main__":
    unittest.main()
