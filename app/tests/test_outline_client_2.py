import unittest
from unittest.mock import Mock, patch

import requests  # For requests.exceptions.RequestException
from clients.outline_client import OutlineClient  # Import the class


class TestOutlineClient2(unittest.TestCase):
    def setUp(self):
        self.mock_url = "http://fake-outline-url.com"
        self.mock_token = "fake_outline_token"
        try:
            self.client = OutlineClient(base_url=self.mock_url, token=self.mock_token)
        except ValueError:
            self.fail("Client instantiation failed in setUp")

    @patch("requests.post")
    def test_create_group_failure_during_list_check(self, mock_post_request):
        mock_post_request.side_effect = requests.exceptions.RequestException("Network error during list")

        project_name = "project_list_fail"
        result = self.client.create_group(project_name)
        self.assertIsNone(result)
        self.assertEqual(mock_post_request.call_count, 1)

    @patch("requests.post")
    def test_list_collections_success_find_by_name(self, mock_post):
        # Test finding a single collection by name
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "data": [{"id": "coll-2", "name": "Test Collection"}],
                "pagination": {"limit": 100, "offset": 0, "total": 1},
            },
        )
        collection = self.client.list_collections(name="Test Collection")
        self.assertIsNotNone(collection)
        self.assertEqual(collection["id"], "coll-2")
        self.assertEqual(mock_post.call_count, 1)

    @patch("requests.post")
    def test_list_collections_success_get_all(self, mock_post):
        # Test listing all collections with pagination
        mock_post.side_effect = [
            Mock(
                status_code=200,
                json=lambda: {
                    "data": [
                        {"id": "coll-1", "name": "First"},
                        {"id": "coll-2", "name": "Second"},
                    ],
                    "pagination": {"limit": 2, "offset": 0, "total": 3},
                },
            ),
            Mock(
                status_code=200,
                json=lambda: {
                    "data": [{"id": "coll-3", "name": "Third"}],
                    "pagination": {"limit": 2, "offset": 2, "total": 3},
                },
            ),
        ]
        collections = self.client.list_collections()
        self.assertIsInstance(collections, list)
        self.assertEqual(len(collections), 3)
        self.assertEqual(collections[2]["name"], "Third")
        self.assertEqual(mock_post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
