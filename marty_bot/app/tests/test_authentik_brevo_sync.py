import unittest
from unittest.mock import patch
import os

# Assuming the script is in marty_bot.libraries.authentik_brevo_sync
from libraries.authentik_brevo_sync import sync_authentik_users_to_brevo_list

# Define fake environment variables for the test duration
FAKE_AUTHENTIK_URL = "http://fake-auth-url.com"
FAKE_AUTHENTIK_TOKEN = "fake-auth-token"
FAKE_BREVO_API_URL = "http://fake-brevo-url.com"
FAKE_BREVO_API_KEY = "fake-brevo-key"
FAKE_BREVO_LIST_ID = "123"  # String, as it comes from getenv


@patch.dict(
    os.environ,
    {
        "AUTHENTIK_URL": FAKE_AUTHENTIK_URL,
        "AUTHENTIK_TOKEN": FAKE_AUTHENTIK_TOKEN,
        "BREVO_API_URL": FAKE_BREVO_API_URL,
        "BREVO_API_KEY": FAKE_BREVO_API_KEY,
        "BREVO_AUTHENTIK_USERS_LIST_ID": FAKE_BREVO_LIST_ID,
    },
)
class TestAuthentikBrevoSync(unittest.TestCase):

    @patch("libraries.authentik_brevo_sync.AuthentikClient")
    @patch("libraries.authentik_brevo_sync.BrevoClient")
    def test_sync_success_add_users(self, MockBrevoClient, MockAuthentikClient):
        # --- Setup Mocks ---
        # Mock AuthentikClient instance and its methods
        mock_auth_instance = MockAuthentikClient.return_value
        mock_auth_instance.get_all_users_emails.return_value = [
            "user1@example.com",
            "user2@example.com",
            "shared@example.com",
        ]

        # Mock BrevoClient instance and its methods
        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.get_contacts_from_list.return_value = [
            "user1@example.com",  # Already in Brevo
            "olduser@example.com",  # In Brevo, not in Authentik (should be ignored by this sync logic)
        ]
        # Mock add_contact_to_list to return True for successful additions
        mock_brevo_instance.add_contact_to_list.return_value = True

        # --- Call the function under test ---
        sync_authentik_users_to_brevo_list()

        # --- Assertions ---
        # AuthentikClient initialized correctly
        MockAuthentikClient.assert_called_once_with(base_url=FAKE_AUTHENTIK_URL, token=FAKE_AUTHENTIK_TOKEN)
        # BrevoClient initialized correctly
        MockBrevoClient.assert_called_once_with(api_url=FAKE_BREVO_API_URL, api_key=FAKE_BREVO_API_KEY)

        # Methods called on AuthentikClient
        mock_auth_instance.get_all_users_emails.assert_called_once()

        # Methods called on BrevoClient
        mock_brevo_instance.get_contacts_from_list.assert_called_once_with(int(FAKE_BREVO_LIST_ID))

        # Check that add_contact_to_list was called for users in Authentik but not Brevo
        # Expected to add: "user2@example.com", "shared@example.com"
        # Call count should be 2
        self.assertEqual(mock_brevo_instance.add_contact_to_list.call_count, 2)
        mock_brevo_instance.add_contact_to_list.assert_any_call(
            email="user2@example.com", list_id=int(FAKE_BREVO_LIST_ID)
        )
        mock_brevo_instance.add_contact_to_list.assert_any_call(
            email="shared@example.com", list_id=int(FAKE_BREVO_LIST_ID)
        )

    @patch("libraries.authentik_brevo_sync.AuthentikClient")
    @patch("libraries.authentik_brevo_sync.BrevoClient")
    def test_sync_no_new_users_to_add(self, MockBrevoClient, MockAuthentikClient):
        mock_auth_instance = MockAuthentikClient.return_value
        mock_auth_instance.get_all_users_emails.return_value = ["user1@example.com"]

        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.get_contacts_from_list.return_value = ["user1@example.com"]

        sync_authentik_users_to_brevo_list()

        mock_brevo_instance.add_contact_to_list.assert_not_called()

    @patch("libraries.authentik_brevo_sync.AuthentikClient")
    @patch("libraries.authentik_brevo_sync.BrevoClient")
    @patch("libraries.authentik_brevo_sync.logging")  # Mock logging to check error messages
    def test_sync_authentik_fetch_fails(self, mock_logging, MockBrevoClient, MockAuthentikClient):
        mock_auth_instance = MockAuthentikClient.return_value
        # Simulate failure by returning None, as checked in the sync function
        mock_auth_instance.get_all_users_emails.return_value = None

        sync_authentik_users_to_brevo_list()

        mock_logging.error.assert_any_call("Failed to fetch users from Authentik. Aborting sync.")
        MockBrevoClient.return_value.get_contacts_from_list.assert_not_called()
        MockBrevoClient.return_value.add_contact_to_list.assert_not_called()

    @patch("libraries.authentik_brevo_sync.AuthentikClient")
    @patch("libraries.authentik_brevo_sync.BrevoClient")
    @patch("libraries.authentik_brevo_sync.logging")
    def test_sync_brevo_fetch_fails(self, mock_logging, MockBrevoClient, MockAuthentikClient):
        mock_auth_instance = MockAuthentikClient.return_value
        mock_auth_instance.get_all_users_emails.return_value = ["user1@example.com"]

        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.get_contacts_from_list.return_value = None  # Simulate failure

        sync_authentik_users_to_brevo_list()

        mock_logging.error.assert_any_call(
            f"Failed to fetch contacts from Brevo list ID {FAKE_BREVO_LIST_ID}. Aborting sync."
        )
        mock_brevo_instance.add_contact_to_list.assert_not_called()

    @patch("libraries.authentik_brevo_sync.AuthentikClient")
    @patch("libraries.authentik_brevo_sync.BrevoClient")
    @patch("libraries.authentik_brevo_sync.logging")
    def test_sync_add_user_fails_in_brevo(self, mock_logging, MockBrevoClient, MockAuthentikClient):
        mock_auth_instance = MockAuthentikClient.return_value
        mock_auth_instance.get_all_users_emails.return_value = ["newuser@example.com"]

        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.get_contacts_from_list.return_value = []
        mock_brevo_instance.add_contact_to_list.return_value = False  # Simulate failure to add

        sync_authentik_users_to_brevo_list()

        mock_brevo_instance.add_contact_to_list.assert_called_once_with(
            email="newuser@example.com", list_id=int(FAKE_BREVO_LIST_ID)
        )
        # Check the summary log
        mock_logging.info.assert_any_call("Finished adding users to Brevo. Added: 0, Failed: 1.")

    @patch.dict(os.environ, {"BREVO_AUTHENTIK_USERS_LIST_ID": "not-an-int"})
    @patch("libraries.authentik_brevo_sync.logging")
    def test_sync_invalid_brevo_list_id_env(self, mock_logging):
        # Need to ensure other env vars are set if sync_authentik_users_to_brevo_list checks them all first
        with patch.dict(
            os.environ,
            {
                "AUTHENTIK_URL": FAKE_AUTHENTIK_URL,
                "AUTHENTIK_TOKEN": FAKE_AUTHENTIK_TOKEN,
                "BREVO_API_URL": FAKE_BREVO_API_URL,
                "BREVO_API_KEY": FAKE_BREVO_API_KEY,
                "BREVO_AUTHENTIK_USERS_LIST_ID": "not-an-int",  # This is the one being tested
            },
        ):
            sync_authentik_users_to_brevo_list()
            mock_logging.error.assert_any_call(
                "Invalid BREVO_AUTHENTIK_USERS_LIST_ID: 'not-an-int'. Must be an integer."
            )

    @patch.dict(os.environ, {"AUTHENTIK_URL": ""})  # Missing one required env var
    @patch("libraries.authentik_brevo_sync.logging")
    def test_sync_missing_env_var(self, mock_logging):
        # Ensure all other potentially checked env vars are present to isolate the test
        with patch.dict(
            os.environ,
            {
                "AUTHENTIK_URL": "",  # Specifically testing this one missing
                "AUTHENTIK_TOKEN": FAKE_AUTHENTIK_TOKEN,
                "BREVO_API_URL": FAKE_BREVO_API_URL,
                "BREVO_API_KEY": FAKE_BREVO_API_KEY,
                "BREVO_AUTHENTIK_USERS_LIST_ID": FAKE_BREVO_LIST_ID,
            },
        ):
            sync_authentik_users_to_brevo_list()
            mock_logging.error.assert_any_call(
                "Missing one or more required environment variables for Authentik/Brevo sync: "
                "AUTHENTIK_URL, AUTHENTIK_TOKEN, BREVO_API_URL, BREVO_API_KEY, BREVO_AUTHENTIK_USERS_LIST_ID"
            )


if __name__ == "__main__":
    unittest.main()
