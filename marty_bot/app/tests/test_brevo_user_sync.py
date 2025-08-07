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
        "BREVO_API_URL": FAKE_BREVO_API_URL,
        "BREVO_API_KEY": FAKE_BREVO_API_KEY,
        "BREVO_AUTHENTIK_USERS_LIST_ID": FAKE_BREVO_LIST_ID,
    },
)
class TestAuthentikBrevoSync(unittest.TestCase):
    @patch("libraries.brevo_user_sync.BrevoClient")
    def test_sync_success_add_users(self, MockBrevoClient):
        # --- Setup Mocks ---
        authentik_users_data = [
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
            },
        ]

        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.get_contacts_from_list.return_value = [
            "user1@example.com",
            "olduser@example.com",
        ]
        mock_brevo_instance.add_contact_to_list.return_value = True

        # --- Call the function under test ---
        sync_authentik_users_to_brevo_list(authentik_users_data)

        # --- Assertions ---
        MockBrevoClient.assert_called_once_with(api_url=FAKE_BREVO_API_URL, api_key=FAKE_BREVO_API_KEY)
        mock_brevo_instance.get_contacts_from_list.assert_called_once_with(int(FAKE_BREVO_LIST_ID))
        self.assertEqual(mock_brevo_instance.add_contact_to_list.call_count, 3)
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
            attributes={},
        )

    @patch("libraries.brevo_user_sync.BrevoClient")
    def test_sync_no_new_users_to_add(self, MockBrevoClient):
        authentik_users_data = [{"email": "user1@example.com", "attributes": {"attributes.ville": "Lyon"}}]
        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.get_contacts_from_list.return_value = ["user1@example.com"]
        sync_authentik_users_to_brevo_list(authentik_users_data)
        mock_brevo_instance.add_contact_to_list.assert_not_called()

    @patch("libraries.brevo_user_sync.BrevoClient")
    @patch("libraries.brevo_user_sync.logging")
    def test_sync_brevo_fetch_fails(self, mock_logging, MockBrevoClient):
        authentik_users_data = [{"email": "user1@example.com", "attributes": {}}]
        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.get_contacts_from_list.return_value = None
        sync_authentik_users_to_brevo_list(authentik_users_data)
        mock_logging.error.assert_any_call(
            f"Failed to fetch contacts from Brevo list ID {FAKE_BREVO_LIST_ID}. Aborting sync."
        )
        mock_brevo_instance.add_contact_to_list.assert_not_called()

    @patch("libraries.brevo_user_sync.BrevoClient")
    @patch("libraries.brevo_user_sync.logging")
    def test_sync_add_user_fails_in_brevo(self, mock_logging, MockBrevoClient):
        authentik_users_data = [{"email": "newuser@example.com", "attributes": {"attributes.ville": "Nice"}}]
        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.get_contacts_from_list.return_value = []
        mock_brevo_instance.add_contact_to_list.return_value = False
        sync_authentik_users_to_brevo_list(authentik_users_data)
        expected_brevo_attrs = {"CITY": "Nice"}
        mock_brevo_instance.add_contact_to_list.assert_called_once_with(
            email="newuser@example.com",
            list_id=int(FAKE_BREVO_LIST_ID),
            attributes=expected_brevo_attrs,
        )
        mock_logging.info.assert_any_call("Finished adding users to Brevo. Added: 0, Failed: 1.")

    @patch.dict(os.environ, {"BREVO_AUTHENTIK_USERS_LIST_ID": "not-an-int"})
    @patch("libraries.brevo_user_sync.logging")
    def test_sync_invalid_brevo_list_id_env(self, mock_logging):
        sync_authentik_users_to_brevo_list([])
        mock_logging.error.assert_any_call("Invalid BREVO_AUTHENTIK_USERS_LIST_ID: 'not-an-int'. Must be an integer.")

    @patch.dict(os.environ, {"BREVO_API_URL": ""})
    @patch("libraries.brevo_user_sync.logging")
    def test_sync_missing_env_var(self, mock_logging):
        sync_authentik_users_to_brevo_list([])
        mock_logging.error.assert_any_call(
            "Missing one or more required environment variables for Brevo sync: "
            "BREVO_API_URL, BREVO_API_KEY, BREVO_AUTHENTIK_USERS_LIST_ID"
        )


if __name__ == "__main__":
    unittest.main()
