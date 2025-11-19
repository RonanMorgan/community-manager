import os
import unittest
from unittest.mock import MagicMock, patch

from libraries.brevo_user_sync import sync_authentik_users_to_brevo_list

# Define fake environment variables for the test duration
FAKE_BREVO_API_URL = "http://fake-brevo-url.com"
FAKE_BREVO_API_KEY = "fake-brevo-key"
FAKE_BREVO_LIST_ID = "123"


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
    @patch("libraries.brevo_user_sync.logging")
    def test_sync_success_upsert_users(self, mock_logging, MockBrevoClient):
        """
        Tests the successful upserting of a list of users.
        Verifies that every user is processed and attributes are correctly mapped.
        """
        # --- Setup Mocks ---
        # Note: The 'attributes' dict key from Authentik should not contain a nested 'attributes.' prefix.
        # The sync function expects keys like 'ville', 'activity', etc., directly inside 'attributes'.
        authentik_users_data = [
            {"email": "user1@example.com", "attributes": {"ville": "Paris", "metier": "Développeur"}},
            {"email": "user2@example.com", "attributes": {"activity": "DevOps"}},
            {"email": "shared@example.com", "attributes": {"totem": "Licorne"}},
            {"email": "user_no_attrs@example.com", "attributes": {}},
            {
                "email": "user.without.email@example.com",
                "attributes": {"ville": "Lille"},
            },  # Should be skipped if email is missing in map creation
        ]
        # Simulate that one user has no email key
        del authentik_users_data[4]["email"]

        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.add_contact_to_list.return_value = True

        # --- Call the function under test ---
        sync_authentik_users_to_brevo_list(authentik_users_data)

        # --- Assertions ---
        # Verify BrevoClient was initialized correctly
        MockBrevoClient.assert_called_once_with(api_url=FAKE_BREVO_API_URL, api_key=FAKE_BREVO_API_KEY)

        # The function should now attempt to add/update every user from Authentik
        self.assertEqual(
            mock_brevo_instance.add_contact_to_list.call_count,
            4,
            "Should call add_contact_to_list for each user with an email",
        )

        # Check the calls with correctly mapped attributes
        mock_brevo_instance.add_contact_to_list.assert_any_call(
            email="user1@example.com",
            list_id=int(FAKE_BREVO_LIST_ID),
            attributes={"CITY": "Paris", "JOB_TITLE": "Développeur"},
        )
        mock_brevo_instance.add_contact_to_list.assert_any_call(
            email="user2@example.com",
            list_id=int(FAKE_BREVO_LIST_ID),
            attributes={"JOB": "DevOps"},
        )
        mock_brevo_instance.add_contact_to_list.assert_any_call(
            email="shared@example.com",
            list_id=int(FAKE_BREVO_LIST_ID),
            attributes={"TOTEM": "Licorne"},
        )
        mock_brevo_instance.add_contact_to_list.assert_any_call(
            email="user_no_attrs@example.com",
            list_id=int(FAKE_BREVO_LIST_ID),
            attributes={},
        )

        # Check final summary log
        mock_logging.info.assert_any_call("Finished syncing users to Brevo. Success: 4, Failed: 0.")

    @patch("libraries.brevo_user_sync.BrevoClient")
    def test_sync_updates_existing_user(self, MockBrevoClient):
        """
        Tests that the sync function attempts to add a user even if they are conceptually 'existing'.
        The new logic is 'upsert-only', so it should always call the add function.
        """
        authentik_users_data = [{"email": "user1@example.com", "attributes": {"ville": "Lyon"}}]

        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.add_contact_to_list.return_value = True

        sync_authentik_users_to_brevo_list(authentik_users_data)

        # Assert that add_contact_to_list IS called, as the logic is now upsert
        mock_brevo_instance.add_contact_to_list.assert_called_once_with(
            email="user1@example.com",
            list_id=int(FAKE_BREVO_LIST_ID),
            attributes={"CITY": "Lyon"},
        )

    @patch("libraries.brevo_user_sync.BrevoClient")
    @patch("libraries.brevo_user_sync.logging")
    def test_sync_add_user_fails_in_brevo(self, mock_logging, MockBrevoClient):
        """
        Tests how the system behaves when the Brevo API call to add a contact fails.
        """
        authentik_users_data = [{"email": "newuser@example.com", "attributes": {"ville": "Nice"}}]

        mock_brevo_instance = MockBrevoClient.return_value
        # Simulate a failure from the Brevo client
        mock_brevo_instance.add_contact_to_list.return_value = False

        sync_authentik_users_to_brevo_list(authentik_users_data)

        # Verify the attempt was made
        mock_brevo_instance.add_contact_to_list.assert_called_once_with(
            email="newuser@example.com",
            list_id=int(FAKE_BREVO_LIST_ID),
            attributes={"CITY": "Nice"},
        )

        # Verify the failure is logged correctly in the summary
        mock_logging.info.assert_any_call("Finished syncing users to Brevo. Success: 0, Failed: 1.")

    @patch.dict(os.environ, {"BREVO_AUTHENTIK_USERS_LIST_ID": "not-an-int"})
    @patch("libraries.brevo_user_sync.logging")
    def test_sync_invalid_brevo_list_id_env(self, mock_logging: MagicMock):
        """
        Tests that the script exits gracefully if the Brevo List ID is not a valid integer.
        """
        sync_authentik_users_to_brevo_list([])
        mock_logging.error.assert_any_call("Invalid BREVO_AUTHENTIK_USERS_LIST_ID: 'not-an-int'. Must be an integer.")

    @patch.dict(os.environ, {"BREVO_API_URL": ""})
    @patch("libraries.brevo_user_sync.logging")
    def test_sync_missing_env_var(self, mock_logging: MagicMock):
        """
        Tests that the script exits gracefully if a required environment variable is missing.
        """
        sync_authentik_users_to_brevo_list([])
        mock_logging.error.assert_any_call(
            "Missing one or more required environment variables for Brevo sync: "
            "BREVO_API_URL, BREVO_API_KEY, BREVO_AUTHENTIK_USERS_LIST_ID"
        )

    @patch("libraries.brevo_user_sync.BrevoClient")
    @patch("libraries.brevo_user_sync.logging")
    def test_no_authentik_users(self, mock_logging: MagicMock, MockBrevoClient: MagicMock):
        """
        Tests that the function handles an empty list of Authentik users gracefully.
        """
        sync_authentik_users_to_brevo_list([])

        mock_logging.info.assert_any_call("No users found in Authentik.")
        # Ensure no calls were made to Brevo
        mock_brevo_instance = MockBrevoClient.return_value
        mock_brevo_instance.add_contact_to_list.assert_not_called()


if __name__ == "__main__":
    unittest.main()
