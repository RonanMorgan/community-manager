import unittest
from unittest.mock import patch

from libraries.user_management import remove_inactive_users


class TestUserManagement(unittest.TestCase):

    @patch("libraries.user_management.remove_inactive_outline_users")
    @patch("libraries.user_management.remove_inactive_nocodb_users")
    @patch("libraries.user_management.remove_inactive_mattermost_users")
    def test_remove_inactive_users_calls_correct_functions(
        self, mock_remove_mattermost, mock_remove_nocodb, mock_remove_outline
    ):
        authentik_users = [{"email": "user1@example.com"}]

        remove_inactive_users(["outline", "nocodb", "mattermost"], authentik_users)

        mock_remove_outline.assert_called_once_with({"user1@example.com"})
        mock_remove_nocodb.assert_called_once_with({"user1@example.com"})
        mock_remove_mattermost.assert_called_once_with({"user1@example.com"})

    @patch("libraries.user_management.remove_inactive_outline_users")
    @patch("libraries.user_management.remove_inactive_nocodb_users")
    @patch("libraries.user_management.remove_inactive_mattermost_users")
    def test_remove_inactive_users_single_service(
        self, mock_remove_mattermost, mock_remove_nocodb, mock_remove_outline
    ):
        authentik_users = [{"email": "user1@example.com"}]

        remove_inactive_users(["outline"], authentik_users)

        mock_remove_outline.assert_called_once_with({"user1@example.com"})
        mock_remove_nocodb.assert_not_called()
        mock_remove_mattermost.assert_not_called()


if __name__ == "__main__":
    unittest.main()
