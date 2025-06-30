import unittest
from unittest.mock import patch, Mock
from clients.outline_client import OutlineClient  # Import the class
import requests  # For requests.exceptions.RequestException


class TestOutlineClient(unittest.TestCase):

    def setUp(self):
        self.mock_url = "http://fake-outline-url.com"
        self.mock_token = "fake_outline_token"
        try:
            self.client = OutlineClient(base_url=self.mock_url, token=self.mock_token)
        except ValueError:
            self.fail("Client instantiation failed in setUp")

    def test_constructor_success(self):
        self.assertEqual(self.client.base_url, self.mock_url)
        self.assertEqual(self.client.token, self.mock_token)
        self.assertIn(f"Bearer {self.mock_token}", self.client.headers["Authorization"])

    def test_constructor_value_error(self):
        with self.assertRaises(ValueError) as cm:
            OutlineClient(base_url=None, token="fake")
        self.assertEqual(str(cm.exception), "Outline base_url and token must be provided.")

        with self.assertRaises(ValueError) as cm:
            OutlineClient(base_url="fake", token=None)
        self.assertEqual(str(cm.exception), "Outline base_url and token must be provided.")

    @patch("requests.post")
    def test_create_group_success_collection_does_not_exist(self, mock_post_request):
        # Mock for get_collection_by_name (first call to collections.list)
        mock_list_response = Mock()
        mock_list_response.status_code = 200
        mock_list_response.json.return_value = {"data": [], "pagination": {"offset": 0, "limit": 25}}

        # Mock for collections.create (second call)
        mock_create_response = Mock()
        mock_create_response.status_code = 200
        mock_create_response.json.return_value = {"data": {"id": "collection_id_123", "name": "new_project"}}

        mock_post_request.side_effect = [mock_list_response, mock_create_response]

        project_name = "new_project"
        result = self.client.create_group(project_name)
        self.assertEqual(result, "CREATED")  # Expect "CREATED" status

        self.assertEqual(mock_post_request.call_count, 2)

        list_call_args = mock_post_request.call_args_list[0]
        self.assertEqual(list_call_args[0][0], f"{self.mock_url}/api/collections.list")

        create_call_args = mock_post_request.call_args_list[1]
        self.assertEqual(create_call_args[0][0], f"{self.mock_url}/api/collections.create")
        self.assertEqual(create_call_args[1]["json"], {"name": project_name})

    @patch("requests.post")
    def test_create_group_success_collection_already_exists(self, mock_post_request):
        project_name = "existing_project"
        mock_list_response = Mock()
        mock_list_response.status_code = 200
        mock_list_response.json.return_value = {
            "data": [{"id": "existing_id_456", "name": project_name}],
            "pagination": {"offset": 0, "limit": 25},
        }
        mock_post_request.return_value = mock_list_response

        result = self.client.create_group(project_name)
        self.assertEqual(result, "EXISTS")  # Expect "EXISTS" status

        mock_post_request.assert_called_once()
        list_call_args = mock_post_request.call_args_list[0]
        self.assertEqual(list_call_args[0][0], f"{self.mock_url}/api/collections.list")

    @patch("requests.post")
    def test_create_group_failure_during_list_check(self, mock_post_request):
        mock_post_request.side_effect = requests.exceptions.RequestException("Network error during list")

        project_name = "project_list_fail"
        result = self.client.create_group(project_name)
        self.assertEqual(result, "FAILED")  # Expect "FAILED" status
        self.assertEqual(mock_post_request.call_count, 2)

    @patch("requests.post")
    def test_create_group_failure_during_actual_creation(self, mock_post_request):
        mock_list_response = Mock()
        mock_list_response.status_code = 200
        mock_list_response.json.return_value = {"data": [], "pagination": {"offset": 0, "limit": 25}}

        mock_create_response = Mock()
        mock_create_response.status_code = 403
        mock_create_response.json.return_value = {"message": "Cannot create"}

        mock_post_request.side_effect = [mock_list_response, mock_create_response]

        project_name = "project_create_fail"
        result = self.client.create_group(project_name)
        self.assertEqual(result, "FAILED")  # Expect "FAILED" status
        self.assertEqual(mock_post_request.call_count, 2)

    @patch("requests.post")
    def test_create_group_failure_unexpected_response_data_in_create(self, mock_post_request):
        mock_list_response = Mock()
        mock_list_response.status_code = 200
        mock_list_response.json.return_value = {"data": [], "pagination": {"offset": 0, "limit": 25}}

        mock_create_response = Mock()
        mock_create_response.status_code = 200
        mock_create_response.json.return_value = {"data": None}

        mock_post_request.side_effect = [mock_list_response, mock_create_response]

        project_name = "test_project_malformed_success_create"
        result = self.client.create_group(project_name)
        self.assertEqual(result, "FAILED")  # Expect "FAILED"
        self.assertEqual(mock_post_request.call_count, 2)

    @patch("requests.post")
    def test_get_collection_by_name_found(self, mock_post_request):
        project_name = "find_me"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "found_id", "name": project_name}]}
        mock_post_request.return_value = mock_response

        collection = self.client.get_collection_by_name(project_name)
        self.assertIsNotNone(collection)
        self.assertEqual(collection["name"], project_name)

    @patch("requests.post")
    def test_get_collection_by_name_not_found(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "other_id", "name": "other_project"}]}
        mock_post_request.return_value = mock_response

        collection = self.client.get_collection_by_name("project_not_there")
        self.assertIsNone(collection)

    @patch("requests.post")
    def test_get_collection_by_name_request_exception(self, mock_post_request):
        mock_post_request.side_effect = requests.exceptions.RequestException("Network error")
        self.assertIsNone(self.client.get_collection_by_name("any_project"))

    def test_constructor_url_trailing_slash(self):
        client_with_slash = OutlineClient(base_url="http://fake-outline-url.com/", token=self.mock_token)
        self.assertEqual(client_with_slash.base_url, "http://fake-outline-url.com")

    @patch("requests.post")
    def test_get_collection_details_success(self, mock_post_request):
        mock_response = Mock()
        mock_response.status_code = 200
        expected_details = {"id": "coll_id_1", "name": "Test Collection", "urlId": "test-coll"}
        mock_response.json.return_value = {"data": expected_details}
        mock_post_request.return_value = mock_response

        collection_id = "coll_id_1"
        details = self.client.get_collection_details(collection_id)

        self.assertEqual(details, expected_details)
        expected_api_url = f"{self.mock_url}/api/collections.info"
        expected_payload = {"id": collection_id}
        mock_post_request.assert_called_once_with(expected_api_url, headers=self.client.headers, json=expected_payload)

    # Tests for remove_user_from_collection
    @patch("requests.post")
    def test_remove_user_from_collection_success_true(self, mock_post):
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {"success": True}
        mock_post.return_value = mock_response

        result = self.client.remove_user_from_collection("coll_id_1", "user_id_1")
        self.assertTrue(result)
        expected_url = f"{self.mock_url}/api/collections.remove_user"
        expected_payload = {"collectionId": "coll_id_1", "userId": "user_id_1"}
        mock_post.assert_called_once_with(expected_url, headers=self.client.headers, json=expected_payload)

    @patch("requests.post")
    def test_remove_user_from_collection_success_204_no_content(self, mock_post):
        mock_response = Mock(status_code=204)
        # For 204, .json() would typically not be called or would raise an error if called.
        # The client logic should handle this (e.g., by not calling .json()).
        mock_post.return_value = mock_response

        result = self.client.remove_user_from_collection("coll_id_1", "user_id_1")
        self.assertTrue(result)
        expected_url = f"{self.mock_url}/api/collections.remove_user"
        expected_payload = {"collectionId": "coll_id_1", "userId": "user_id_1"}
        mock_post.assert_called_once_with(expected_url, headers=self.client.headers, json=expected_payload)

    @patch("requests.post")
    def test_remove_user_from_collection_failure_false(self, mock_post):
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {"success": False}  # API reports not successful
        mock_post.return_value = mock_response

        result = self.client.remove_user_from_collection("coll_id_1", "user_id_1")
        self.assertFalse(result)

    @patch("requests.post")
    def test_remove_user_from_collection_failure_http_error(self, mock_post):
        mock_err_response = Mock(status_code=403)  # Forbidden
        mock_err_response.text = "Forbidden action"
        mock_err_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_err_response)
        mock_post.return_value = mock_err_response

        result = self.client.remove_user_from_collection("coll_id_1", "user_id_1")
        self.assertFalse(result)

    @patch("requests.post")
    def test_remove_user_from_collection_failure_request_exception(self, mock_post):
        mock_post.side_effect = requests.exceptions.RequestException("Network issue")
        result = self.client.remove_user_from_collection("coll_id_1", "user_id_1")
        self.assertFalse(result)

    def test_remove_user_from_collection_missing_ids(self):
        self.assertFalse(self.client.remove_user_from_collection(None, "user_id_1"))
        self.assertFalse(self.client.remove_user_from_collection("coll_id_1", None))
        self.assertFalse(self.client.remove_user_from_collection("", "user_id_1"))
        self.assertFalse(self.client.remove_user_from_collection("coll_id_1", ""))


if __name__ == "__main__":
    unittest.main()
