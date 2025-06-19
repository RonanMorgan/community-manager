import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import json
import asyncio

# Set up dummy config values needed by bot.py at import time or during tests
# It's better if bot.py functions receive config explicitly or via a class,
# but for now, we patch the global config module used by bot.py.
from app import config as bot_config
bot_config.BOT_NAME = "marty"
bot_config.MATTERMOST_TEAM_ID = "test_team_id"
# BOT_TOKEN is used in envoyer_message and on_open, ensure it's set for tests if those are called.
bot_config.BOT_TOKEN = "test_bot_token"
bot_config.MATTERMOST_URL = "http://fake-mm.com"


# Now import bot module AFTER config is patched for BOT_NAME
from app.bot import on_message, envoyer_message # Direct import for patching

# Helper to run async test methods
def async_test(f):
    def wrapper(*args, **kwargs):
        asyncio.run(f(*args, **kwargs))
    return wrapper

class TestBotMessageHandler(unittest.TestCase):

    def setUp(self):
        # This ensures that each test gets fresh mocks if they are modified by a previous test.
        # However, patches are defined per-method or per-class in unittest.
        pass

    @patch('app.bot.mattermost_create_channel', return_value=True)
    @patch('app.bot.outline_create_group', return_value=True)
    @patch('app.bot.authentik_create_group', return_value=True)
    @patch('app.bot.envoyer_message')
    @async_test
    async def test_handle_create_group_command_all_success(self, mock_envoyer_message,
                                                            mock_auth_create, mock_outline_create, mock_mm_create):
        bot_config.BOT_NAME = "marty" # Ensure bot name is correctly set for this test
        bot_config.MATTERMOST_TEAM_ID = "test_team_id_for_this_test"

        project_name = "super_project"
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps({
                    "message": f"@{bot_config.BOT_NAME} create_group {project_name}",
                    "channel_id": "channel123",
                    "user_id": "user456"
                })
            }
        }

        # on_message is async, so await it
        await on_message(None, json.dumps(mock_message_data))

        mock_auth_create.assert_called_once_with(project_name)
        mock_outline_create.assert_called_once_with(project_name)
        mock_mm_create.assert_called_once_with(project_name, team_id=bot_config.MATTERMOST_TEAM_ID)

        mock_envoyer_message.assert_called_once()
        args, _ = mock_envoyer_message.call_args
        self.assertEqual(args[0], "channel123") # channel_id
        self.assertIn(f"Processing 'create_group' for project: **{project_name}**", args[1])
        self.assertIn("Authentik group creation: Success", args[1])
        self.assertIn("Outline collection creation: Success", args[1])
        self.assertIn("Mattermost channel creation: Success", args[1])

    @patch('app.bot.mattermost_create_channel', return_value=False) # Mattermost fails
    @patch('app.bot.outline_create_group', return_value=True)
    @patch('app.bot.authentik_create_group', return_value=True)
    @patch('app.bot.envoyer_message')
    @async_test
    async def test_handle_create_group_command_one_failure(self, mock_envoyer_message,
                                                             mock_auth_create, mock_outline_create, mock_mm_create):
        bot_config.BOT_NAME = "marty"
        bot_config.MATTERMOST_TEAM_ID = "test_team_id_failure_case"

        project_name = "lunar_project"
        mock_message_data = {
            "event": "posted",
            "data": {"post": json.dumps({
                "message": f"@{bot_config.BOT_NAME} create_group {project_name}",
                "channel_id": "channel789",
                "user_id": "user123"
            })}
        }

        await on_message(None, json.dumps(mock_message_data))

        mock_auth_create.assert_called_once_with(project_name)
        mock_outline_create.assert_called_once_with(project_name)
        mock_mm_create.assert_called_once_with(project_name, team_id=bot_config.MATTERMOST_TEAM_ID)

        mock_envoyer_message.assert_called_once()
        args, _ = mock_envoyer_message.call_args
        self.assertEqual(args[0], "channel789")
        self.assertIn(f"Processing 'create_group' for project: **{project_name}**", args[1])
        self.assertIn("Authentik group creation: Success", args[1])
        self.assertIn("Outline collection creation: Success", args[1])
        self.assertIn("Mattermost channel creation: Failed", args[1])

    @patch('app.bot.envoyer_message')
    @async_test
    async def test_handle_simple_mention_bonjour(self, mock_envoyer_message):
        bot_config.BOT_NAME = "marty"
        mock_message_data = {
            "event": "posted",
            "data": {"post": json.dumps({
                "message": f"@{bot_config.BOT_NAME} hello there",
                "channel_id": "general",
                "user_id": "user007"
            })}
        }
        await on_message(None, json.dumps(mock_message_data))
        mock_envoyer_message.assert_called_once_with("general", "Bonjour toi ! How can I help you today?")

    @patch('app.bot.envoyer_message')
    @async_test
    async def test_handle_mention_no_command(self, mock_envoyer_message):
        bot_config.BOT_NAME = "marty"
        mock_message_data = {
            "event": "posted",
            "data": {"post": json.dumps({
                "message": f"@{bot_config.BOT_NAME}",
                "channel_id": "town-square",
                "user_id": "user008"
            })}
        }
        await on_message(None, json.dumps(mock_message_data))
        mock_envoyer_message.assert_called_once_with("town-square", f"Hi! You mentioned me @{bot_config.BOT_NAME}. Try `create_group <project_name>` or ask for `help`.")


    @patch('app.bot.envoyer_message')
    @async_test
    async def test_ignore_non_mention_message(self, mock_envoyer_message):
        bot_config.BOT_NAME = "marty" # Ensure it's set, though not expected to be used for matching
        mock_message_data = {
            "event": "posted",
            "data": {"post": json.dumps({
                "message": "Hello world, just a regular message.",
                "channel_id": "random",
                "user_id": "user111"
            })}
        }
        await on_message(None, json.dumps(mock_message_data))
        mock_envoyer_message.assert_not_called()

    @patch('app.bot.envoyer_message')
    @async_test
    async def test_ignore_message_not_posted_event(self, mock_envoyer_message):
        mock_message_data = {
            "event": "typing", # Not a 'posted' event
            "data": {"user_id": "user123"}
        }
        await on_message(None, json.dumps(mock_message_data))
        mock_envoyer_message.assert_not_called()

    @patch('app.bot.envoyer_message')
    @patch('app.bot.authentik_create_group') # Mock to prevent actual calls
    @patch('app.bot.outline_create_group')
    @patch('app.bot.mattermost_create_channel')
    @async_test
    async def test_create_group_no_project_name(self, mock_mm, mock_out, mock_auth, mock_envoyer):
        bot_config.BOT_NAME = "marty"
        mock_message_data = {
            "event": "posted",
            "data": {"post": json.dumps({
                "message": f"@{bot_config.BOT_NAME} create_group ", # Empty project name
                "channel_id": "channel_no_proj",
                "user_id": "user_no_proj"
            })}
        }
        await on_message(None, json.dumps(mock_message_data))
        mock_auth.assert_not_called()
        mock_out.assert_not_called()
        mock_mm.assert_not_called()
        mock_envoyer.assert_called_once_with("channel_no_proj", "Please specify a project name for create_group. Usage: @marty create_group <project_name>")

    # The bot's current on_message doesn't have an explicit check for `sender_id == bot_user_id`.
    # It relies on the command structure (mentioning @BOT_NAME). If the bot itself sends a message
    # like "@BOT_NAME create_group ...", it would try to process it.
    # A true "ignore self" test would require mocking the bot's own user ID and having logic
    # in on_message to check `if sender_id == BOT_USER_ID: return`.
    # For now, we test that a message *from* the bot that *is not* a command doesn't cause issues.
    @patch('app.bot.envoyer_message')
    @async_test
    async def test_ignore_message_from_bot_not_a_command(self, mock_envoyer_message):
        bot_config.BOT_NAME = "marty"
        # Simulate a message that might look like it's from the bot, but isn't a command to itself.
        # For example, if the bot sent a confirmation message.
        mock_message_data = {
            "event": "posted",
            "data": {"post": json.dumps({
                "message": "Group 'some_project' created successfully!", # No @marty mention
                "channel_id": "channel123",
                "user_id": "the_bot_user_id_if_it_had_one" # Pretend this is the bot
            })}
        }
        await on_message(None, json.dumps(mock_message_data))
        mock_envoyer_message.assert_not_called()


if __name__ == '__main__':
    # This setup is a bit more involved due to async nature and config patching.
    # Running with `python -m unittest discover -s app/tests` is standard.
    unittest.main()
