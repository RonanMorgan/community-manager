import unittest
from unittest.mock import patch, MagicMock  # Removed AsyncMock, PropertyMock
import json
import asyncio

# Import the bot module itself to access its global client instances
from app import bot as marty_bot_module
from app import config as bot_config  # Used for BOT_NAME etc.


# Helper to run async test methods
def async_test(f):
    def wrapper(*args, **kwargs):
        asyncio.run(f(*args, **kwargs))

    return wrapper


class TestBotMessageHandler(unittest.TestCase):

    def setUp(self):
        # Store original config values that might be changed by tests
        self.original_bot_name = bot_config.BOT_NAME
        self.original_mm_team_id = bot_config.MATTERMOST_TEAM_ID

        # Set default test values
        bot_config.BOT_NAME = "martytest"
        bot_config.MATTERMOST_TEAM_ID = "test_team_id"
        bot_config.BOT_TOKEN = "test_bot_token_for_envoyer"
        bot_config.MATTERMOST_URL = "http://fake-mm.com"

    def tearDown(self):
        # Restore original config values
        bot_config.BOT_NAME = self.original_bot_name
        bot_config.MATTERMOST_TEAM_ID = self.original_mm_team_id
        # Reset other potentially modified configs if necessary

    # Patching the client instances where they are defined in the marty_bot_module (app.bot)
    @patch.object(marty_bot_module, "envoyer_message", new_callable=MagicMock)  # Patched envoyer_message
    @patch.object(
        marty_bot_module, "mattermost_api_client", create=True
    )  # create=True if it might not exist due to init logic
    @patch.object(marty_bot_module, "outline_client", create=True)
    @patch.object(marty_bot_module, "authentik_client", create=True)
    @async_test
    async def test_handle_create_group_command_all_success(
        self,
        mock_auth_client_instance,
        mock_outline_client_instance,
        mock_mm_api_client_instance,
        mock_envoyer_message_func,
    ):
        # Configure mock instances
        mock_auth_client_instance.create_group.return_value = True
        mock_outline_client_instance.create_group.return_value = True
        mock_mm_api_client_instance.create_channel.return_value = True

        project_name = "super_project"
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": f"@{bot_config.BOT_NAME} create_group {project_name}",
                        "channel_id": "channel123",
                        "user_id": "user456",
                    }
                )
            },
        }

        await marty_bot_module.on_message(None, json.dumps(mock_message_data))

        mock_auth_client_instance.create_group.assert_called_once_with(project_name)
        mock_outline_client_instance.create_group.assert_called_once_with(project_name)
        mock_mm_api_client_instance.create_channel.assert_called_once_with(
            project_name
        )  # team_id is handled by client

        mock_envoyer_message_func.assert_called_once()
        args, _ = mock_envoyer_message_func.call_args
        self.assertEqual(args[0], "channel123")
        self.assertIn(f"Processing 'create_group' for project: **{project_name}**", args[1])
        self.assertIn("Authentik group creation: Success", args[1])
        self.assertIn("Outline collection creation: Success", args[1])
        self.assertIn("Mattermost channel creation: Success", args[1])

    @patch.object(marty_bot_module, "envoyer_message", new_callable=MagicMock)
    @patch.object(marty_bot_module, "mattermost_api_client", create=True)
    @patch.object(marty_bot_module, "outline_client", create=True)
    @patch.object(marty_bot_module, "authentik_client", create=True)
    @async_test
    async def test_handle_create_group_one_failure(
        self,
        mock_auth_client_instance,
        mock_outline_client_instance,
        mock_mm_api_client_instance,
        mock_envoyer_message_func,
    ):
        mock_auth_client_instance.create_group.return_value = True
        mock_outline_client_instance.create_group.return_value = False  # Outline fails
        mock_mm_api_client_instance.create_channel.return_value = True

        project_name = "nebula_project"
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": f"@{bot_config.BOT_NAME} create_group {project_name}",
                        "channel_id": "channel789",
                        "user_id": "user123",
                    }
                )
            },
        }

        await marty_bot_module.on_message(None, json.dumps(mock_message_data))

        mock_envoyer_message_func.assert_called_once()
        args, _ = mock_envoyer_message_func.call_args
        self.assertIn("Outline collection creation: Failed", args[1])
        self.assertIn("Authentik group creation: Success", args[1])
        self.assertIn("Mattermost channel creation: Success", args[1])

    @patch.object(marty_bot_module, "envoyer_message", new_callable=MagicMock)
    @patch.object(marty_bot_module, "authentik_client", None)  # Simulate Authentik client not initialized
    @patch.object(marty_bot_module, "outline_client", create=True)
    @patch.object(marty_bot_module, "mattermost_api_client", create=True)
    @async_test
    async def test_handle_create_group_authentik_client_none(
        self, mock_mm_api_client_instance, mock_outline_client_instance, mock_envoyer_message_func
    ):
        # authentik_client is already patched to None for this test's scope
        mock_outline_client_instance.create_group.return_value = True
        mock_mm_api_client_instance.create_channel.return_value = True

        project_name = "no_auth_project"
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": f"@{bot_config.BOT_NAME} create_group {project_name}",
                        "channel_id": "channel_no_auth",
                        "user_id": "user_no_auth",
                    }
                )
            },
        }

        await marty_bot_module.on_message(None, json.dumps(mock_message_data))

        mock_envoyer_message_func.assert_called_once()
        args, _ = mock_envoyer_message_func.call_args
        self.assertIn("- Authentik client not initialized. Skipping.", args[1])
        self.assertIn("Outline collection creation: Success", args[1])
        self.assertIn("Mattermost channel creation: Success", args[1])
        # Check that auth client's method was NOT called
        # Since it's None, it has no methods, so this check is implicit.
        # If it were a Mock that was None, could do: self.assertFalse(mock_auth_client_instance.create_group.called)

    @patch.object(marty_bot_module, "envoyer_message", new_callable=MagicMock)
    @patch.object(marty_bot_module, "authentik_client", create=True)  # Assume other clients are fine
    @patch.object(marty_bot_module, "outline_client", create=True)
    @patch.object(marty_bot_module, "mattermost_api_client", None)  # Simulate Mattermost client not initialized
    @async_test
    async def test_handle_create_group_mattermost_client_none(
        self, mock_outline_client_instance, mock_auth_client_instance, mock_envoyer_message_func
    ):
        # mattermost_api_client is patched to None for this test's scope
        mock_auth_client_instance.create_group.return_value = True
        mock_outline_client_instance.create_group.return_value = True

        project_name = "no_mattermost_project"
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": f"@{bot_config.BOT_NAME} create_group {project_name}",
                        "channel_id": "channel_no_mm",
                        "user_id": "user_no_mm",
                    }
                )
            },
        }

        await marty_bot_module.on_message(None, json.dumps(mock_message_data))

        mock_envoyer_message_func.assert_called_once()
        args, _ = mock_envoyer_message_func.call_args
        self.assertIn("- Mattermost API client not initialized. Skipping.", args[1])
        self.assertIn("Authentik group creation: Success", args[1])
        self.assertIn("Outline collection creation: Success", args[1])

    @patch.object(marty_bot_module, "envoyer_message", new_callable=MagicMock)
    @async_test
    async def test_handle_simple_mention_bonjour(self, mock_envoyer_message_func):
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {"message": f"@{bot_config.BOT_NAME} hello there", "channel_id": "general", "user_id": "user007"}
                )
            },
        }
        await marty_bot_module.on_message(None, json.dumps(mock_message_data))
        mock_envoyer_message_func.assert_called_once_with("general", "Bonjour toi ! How can I help you today?")

    @patch.object(marty_bot_module, "envoyer_message", new_callable=MagicMock)
    @async_test
    async def test_ignore_non_mention_message(self, mock_envoyer_message_func):
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {"message": "Hello world, just a regular message.", "channel_id": "random", "user_id": "user111"}
                )
            },
        }
        # This message does not mention BOT_NAME, so on_message should return early.
        await marty_bot_module.on_message(None, json.dumps(mock_message_data))
        mock_envoyer_message_func.assert_not_called()

    @patch.object(marty_bot_module, "envoyer_message", new_callable=MagicMock)
    @async_test
    async def test_create_group_no_project_name(self, mock_envoyer_message_func):
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": f"@{bot_config.BOT_NAME} create_group ",
                        "channel_id": "channel_no_proj",
                        "user_id": "user_no_proj",
                    }
                )
            },
        }
        await marty_bot_module.on_message(None, json.dumps(mock_message_data))
        mock_envoyer_message_func.assert_called_once_with(
            "channel_no_proj",
            f"Please specify a project name for create_group. Usage: @{bot_config.BOT_NAME} create_group <project_name>",  # noqa: E501
        )


if __name__ == "__main__":
    unittest.main()
