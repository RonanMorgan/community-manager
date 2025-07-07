import unittest
from unittest.mock import patch, MagicMock  # noqa: F401 - MagicMock is used in setUp
import logging
import os
import sys

# Adjust path to import client
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from clients.nocodb_client import NocoDBClient

# Suppress logging for tests
logging.disable(logging.CRITICAL)


class TestNocoDBClient(unittest.TestCase):

    def setUp(self):
        self.base_url = "http://fake-nocodb.com"
        self.token = "fake-token"
        # NocoDBClient no longer takes default_project_id
        self.client = NocoDBClient(base_url=self.base_url, token=self.token)
        self.project_id_fixture = "p_test_project"

    def test_init_success(self):
        self.assertEqual(self.client.base_url, self.base_url)
        self.assertEqual(self.client.headers["xc-token"], self.token)
        self.assertFalse(hasattr(self.client, "default_project_id"))

    def test_init_missing_url(self):
        with self.assertRaisesRegex(ValueError, "NocoDB URL .* required"):
            NocoDBClient(base_url="", token=self.token)

    def test_init_missing_token(self):
        with self.assertRaisesRegex(ValueError, "NocoDB Token .* required"):
            NocoDBClient(base_url=self.base_url, token="")

    @patch.object(NocoDBClient, "_make_request")
    def test_list_projects_success(self, mock_make_request):
        expected_response = {"list": [{"id": "p1", "title": "Project 1"}]}
        mock_make_request.return_value = expected_response
        projects = self.client.list_projects()
        self.assertEqual(projects, expected_response)
        mock_make_request.assert_called_once_with("get", "projects/", params=None)

    @patch.object(NocoDBClient, "_make_request")
    def test_get_base_by_title_found(self, mock_make_request):  # Renamed from get_project_by_title
        mock_make_request.return_value = {"list": [{"id": "p1", "title": "Alpha"}, {"id": "p2", "title": "Beta"}]}
        project = self.client.get_base_by_title("Beta")
        self.assertIsNotNone(project)
        self.assertEqual(project["id"], "p2")
        mock_make_request.assert_called_once_with("get", "projects/")

    @patch.object(NocoDBClient, "_make_request")
    def test_get_base_by_title_not_found(self, mock_make_request):
        mock_make_request.return_value = {"list": [{"id": "p1", "title": "Alpha"}]}
        project = self.client.get_base_by_title("Gamma")
        self.assertIsNone(project)

    @patch.object(NocoDBClient, "_make_request")
    def test_create_base_success(self, mock_make_request):  # Renamed from create_project
        payload = {"title": "New Base", "description": "Desc"}
        expected_response = {"id": "p_new", **payload}
        mock_make_request.return_value = expected_response
        project = self.client.create_base("New Base", "Desc")
        self.assertEqual(project, expected_response)
        mock_make_request.assert_called_once_with("post", "projects/", json=payload)

    @patch.object(NocoDBClient, "_make_request")
    def test_list_base_users_success(self, mock_make_request):
        expected_users = [{"id": "u1", "email": "user1@test.com", "roles": "owner"}]
        mock_make_request.return_value = {"users": {"list": expected_users, "pageInfo": {}}}
        users = self.client.list_base_users(self.project_id_fixture)
        self.assertEqual(users, expected_users)
        mock_make_request.assert_called_once_with("get", f"projects/{self.project_id_fixture}/users")

    @patch.object(NocoDBClient, "_make_request")
    def test_list_base_users_no_project_id_arg_logs_error(self, mock_make_request):
        with self.assertLogs(logger="clients.nocodb_client", level="ERROR") as cm:
            users = self.client.list_base_users(base_id=None)
        self.assertEqual(users, [])
        self.assertIn("base_id is required to list users", cm.output[0])
        mock_make_request.assert_not_called()

    @patch.object(NocoDBClient, "_make_request")
    def test_invite_user_to_base_success(self, mock_make_request):
        mock_make_request.return_value = {"msg": "Invited."}
        success = self.client.invite_user_to_base(base_id=self.project_id_fixture, email="new@test.com", role="viewer")
        self.assertTrue(success)
        mock_make_request.assert_called_once_with(
            "post", f"projects/{self.project_id_fixture}/users", json={"email": "new@test.com", "roles": "viewer"}
        )

    @patch.object(NocoDBClient, "_make_request")
    def test_invite_user_to_base_no_project_id_arg_logs_error(self, mock_make_request):
        with self.assertLogs(logger="clients.nocodb_client", level="ERROR") as cm:
            success = self.client.invite_user_to_base(base_id=None, email="new@test.com", role="viewer")
        self.assertFalse(success)
        self.assertIn("base_id is required to invite user", cm.output[0])
        mock_make_request.assert_not_called()

    @patch.object(NocoDBClient, "_make_request")
    def test_update_base_user_success(self, mock_make_request):
        mock_make_request.return_value = {"msg": "Updated."}
        success = self.client.update_base_user(base_id=self.project_id_fixture, user_id="u1", role="editor")
        self.assertTrue(success)
        mock_make_request.assert_called_once_with(
            "patch", f"projects/{self.project_id_fixture}/users/u1", json={"roles": "editor"}
        )

    @patch.object(NocoDBClient, "_make_request")
    def test_update_base_user_no_project_id_arg_logs_error(self, mock_make_request):
        with self.assertLogs(logger="clients.nocodb_client", level="ERROR") as cm:
            success = self.client.update_base_user(base_id=None, user_id="u1", role="editor")
        self.assertFalse(success)
        self.assertIn("base_id is required to update user role", cm.output[0])
        mock_make_request.assert_not_called()

    @patch.object(NocoDBClient, "update_base_user")
    def test_delete_base_user(self, mock_update_base_user):
        self.client.delete_base_user(base_id=self.project_id_fixture, user_id="u1")
        mock_update_base_user.assert_called_once_with(self.project_id_fixture, "u1", role="no-access")

    @patch.object(NocoDBClient, "list_base_users")
    def test_get_user_by_email_in_base_found(self, mock_list_users):
        mock_list_users.return_value = [
            {"id": "u1", "email": "user1@test.com"},
            {"id": "u2", "email": "USER2@TEST.COM"},
        ]
        user = self.client.get_user_by_email_in_base(base_id=self.project_id_fixture, email="user2@test.com")
        self.assertIsNotNone(user)
        self.assertEqual(user["id"], "u2")
        mock_list_users.assert_called_once_with(self.project_id_fixture)

    @patch.object(NocoDBClient, "list_base_users")
    def test_get_user_by_email_in_base_not_found(self, mock_list_users):
        mock_list_users.return_value = [{"id": "u1", "email": "user1@test.com"}]
        user = self.client.get_user_by_email_in_base(base_id=self.project_id_fixture, email="nonexistent@test.com")
        self.assertIsNone(user)

    @patch.object(NocoDBClient, "list_base_users")
    def test_get_user_by_email_in_base_no_project_id_arg_logs_error(self, mock_list_users):
        with self.assertLogs(logger="clients.nocodb_client", level="ERROR") as cm:
            user = self.client.get_user_by_email_in_base(base_id=None, email="user@test.com")
        self.assertIsNone(user)
        self.assertIn("base_id is required to get user by email", cm.output[0])
        mock_list_users.assert_not_called()

    @patch.object(NocoDBClient, "_make_request")
    def test_create_table_in_project_success(self, mock_make_request):
        table_name = "NewAntenneTable"
        expected_response = {"id": "tbl_123", "title": table_name}
        mock_make_request.return_value = expected_response

        result = self.client.create_table_in_project(project_id=self.project_id_fixture, table_name=table_name)
        self.assertEqual(result, expected_response)

        mock_make_request.assert_called_once()
        args, kwargs = mock_make_request.call_args
        self.assertEqual(args[0], "post")
        self.assertEqual(args[1], f"projects/{self.project_id_fixture}/tables")
        payload = kwargs["json"]
        self.assertEqual(payload["table_name"], table_name)
        self.assertEqual(payload["title"], table_name)
        self.assertTrue(len(payload["columns"]) >= 4)
        # Basic check for one of the default columns
        self.assertTrue(any(col["column_name"] == "id" and col["pk"] for col in payload["columns"]))

    @patch.object(NocoDBClient, "_make_request")
    def test_create_table_in_project_api_error(self, mock_make_request):
        mock_make_request.return_value = None
        result = self.client.create_table_in_project(project_id=self.project_id_fixture, table_name="ErrorTable")
        self.assertIsNone(result)

    def test_create_table_in_project_no_project_id_arg(self):
        with self.assertLogs(logger="clients.nocodb_client", level="ERROR") as cm:
            result = self.client.create_table_in_project(project_id=None, table_name="NoProjectTable")
        self.assertIsNone(result)
        self.assertIn("project_id is required to create a table", cm.output[0])

    def test_create_table_in_project_no_table_name_arg(self):
        with self.assertLogs(logger="clients.nocodb_client", level="ERROR") as cm:
            result = self.client.create_table_in_project(project_id=self.project_id_fixture, table_name=None)
        self.assertIsNone(result)
        self.assertIn("table_name is required to create a table", cm.output[0])


if __name__ == "__main__":
    unittest.main()
