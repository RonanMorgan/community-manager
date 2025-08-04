import os
import unittest
from unittest.mock import patch

# Assuming the script is in marty_bot.libraries.brevo_user_sync
from libraries.brevo_user_sync import sync_authentik_users_to_brevo_list

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
    @patch("libraries.brevo_user_sync.AuthentikClient")
    @patch("libraries.brevo_user_sync.BrevoClient")
    def test_sync_success_add_users(self, MockBrevoClient, MockAuthentikClient):
        # --- Setup Mocks ---
        # Mock AuthentikClient instance and its methods
        mock_auth_instance = MockAuthentikClient.return_value
        # Simulate Authentik returning user data including attributes
        mock_auth_instance.get_all_users_data.return_value = [
            {"email": "user1@example.com", "attributes": {"attributes.ville": "Paris"}},
            {
                "email": "user2@example.com",
                "attributes": {"attributes.activity": "Dev"},
            },
            {
                "email": "shared@example.com",
                "attributes": {"attributes.metier": "Engineer"},
            },
            {
                "email": "user_no_attrs@example.com",
                "attributes": {},
            },  # User with no specific attributes
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
        mock_auth_instance.get_all_users_data.assert_called_once()  # Changed from get_all_users_emails

        # Methods called on BrevoClient
        mock_brevo_instance.get_contacts_from_list.assert_called_once_with(int(FAKE_BREVO_LIST_ID))

        # Expected users to be added to Brevo with mapped attributes:
        # user2@example.com with DOMAIN:Dev
        # shared@example.com with JOB:Engineer
        # user_no_attrs@example.com with {}

        # Call count should be 3 (user2, shared, user_no_attrs)
        self.assertEqual(mock_brevo_instance.add_contact_to_list.call_count, 3)

        # Check calls with mapped attributes
        mock_brevo_instance.add_contact_to_list.assert_any_call(
            email="user2@example.com",
            list_id=int(FAKE_BREVO_LIST_ID),
            attributes={"DOMAIN": "Dev"},
        )
        mock_brevo_instance.add_contact_to_list.assert_any_call(
            email="shared@example.com",
            list_id=int(FAKE_BREVO_LIST_ID),
            attributes={"JOB": "Engineer"},
        )
        mock_brevo_instance.add_contact_to_list.assert_any_call(
            email="user_no_attrs@example.com",
            list_id=int(FAKE_BREVO_LIST_ID),
            attributes={},  # Empty mapped attributes
        )

    @patch("libraries.brevo_user_sync.AuthentikClient")
    @patch("libraries.brevo_user_sync.BrevoClient")
    def test_sync_no_new_users_to_add(self, MockBrevoClient, MockAuthentikClient):
        mock_auth_instance = MockAuthentikClient.return_value
        mock_auth_instance.get_all_users_data.return_value = [  # Now returns list of dicts
            {"email": "user1@example.com", "attributes": {"attributes.ville": "Lyon"}}
        ]

        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.get_contacts_from_list.return_value = ["user1@example.com"]  # Brevo list has the email

        sync_authentik_users_to_brevo_list()

        mock_brevo_instance.add_contact_to_list.assert_not_called()

    @patch("libraries.brevo_user_sync.AuthentikClient")
    @patch("libraries.brevo_user_sync.BrevoClient")
    @patch("libraries.brevo_user_sync.logging")  # Mock logging to check error messages
    def test_sync_authentik_fetch_fails(self, mock_logging, MockBrevoClient, MockAuthentikClient):
        mock_auth_instance = MockAuthentikClient.return_value
        # Simulate failure by returning None
        mock_auth_instance.get_all_users_data.return_value = None

        sync_authentik_users_to_brevo_list()

        mock_logging.error.assert_any_call("Failed to fetch users data from Authentik. Aborting sync.")
        MockBrevoClient.return_value.get_contacts_from_list.assert_not_called()
        MockBrevoClient.return_value.add_contact_to_list.assert_not_called()

    @patch("libraries.brevo_user_sync.AuthentikClient")
    @patch("libraries.brevo_user_sync.BrevoClient")
    @patch("libraries.brevo_user_sync.logging")
    def test_sync_brevo_fetch_fails(self, mock_logging, MockBrevoClient, MockAuthentikClient):
        mock_auth_instance = MockAuthentikClient.return_value
        mock_auth_instance.get_all_users_data.return_value = [  # Now returns list of dicts
            {"email": "user1@example.com", "attributes": {}}
        ]

        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.get_contacts_from_list.return_value = None  # Simulate failure

        sync_authentik_users_to_brevo_list()

        mock_logging.error.assert_any_call(
            f"Failed to fetch contacts from Brevo list ID {FAKE_BREVO_LIST_ID}. Aborting sync."
        )
        mock_brevo_instance.add_contact_to_list.assert_not_called()

    @patch("libraries.brevo_user_sync.AuthentikClient")
    @patch("libraries.brevo_user_sync.BrevoClient")
    @patch("libraries.brevo_user_sync.logging")
    def test_sync_add_user_fails_in_brevo(self, mock_logging, MockBrevoClient, MockAuthentikClient):
        mock_auth_instance = MockAuthentikClient.return_value
        mock_auth_instance.get_all_users_data.return_value = [  # Now returns list of dicts
            {"email": "newuser@example.com", "attributes": {"attributes.ville": "Nice"}}
        ]

        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.get_contacts_from_list.return_value = []
        mock_brevo_instance.add_contact_to_list.return_value = False  # Simulate failure to add

        sync_authentik_users_to_brevo_list()

        expected_brevo_attrs = {"CITY": "Nice"}  # Mapped attributes
        mock_brevo_instance.add_contact_to_list.assert_called_once_with(
            email="newuser@example.com",
            list_id=int(FAKE_BREVO_LIST_ID),
            attributes=expected_brevo_attrs,
        )
        # Check the summary log
        mock_logging.info.assert_any_call("Finished adding users to Brevo. Added: 0, Failed: 1.")

    @patch.dict(os.environ, {"BREVO_AUTHENTIK_USERS_LIST_ID": "not-an-int"})
    @patch("libraries.brevo_user_sync.logging")
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
    @patch("libraries.brevo_user_sync.logging")
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
