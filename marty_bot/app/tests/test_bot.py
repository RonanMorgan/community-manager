import unittest
from unittest.mock import MagicMock
import json
import asyncio

from app.bot import MartyBot


# Helper to run async test methods
def async_test(f):
    def wrapper(*args, **kwargs):
        asyncio.run(f(*args, **kwargs))

    return wrapper


class TestMartyBot(unittest.TestCase):

    def setUp(self):
        self.mock_config = MagicMock()
        self.mock_config.BOT_NAME = "martytest"
        self.mock_config.MATTERMOST_URL = "http://fake-mm.com"
        self.mock_config.BOT_TOKEN = "fake_bot_token"
        self.mock_config.MATTERMOST_TEAM_ID = "fake_team_id"
        self.mock_config.AUTHENTIK_URL = "http://fake-auth.com"
        self.mock_config.AUTHENTIK_TOKEN = "fake_auth_token"
        self.mock_config.OUTLINE_URL = "http://fake-outline.com"
        self.mock_config.OUTLINE_TOKEN = "fake_outline_token"
        self.mock_config.DEBUG = False

        self.bot = MartyBot(self.mock_config)
        self.bot.authentik_client = MagicMock()
        self.bot.outline_client = MagicMock()
        self.bot.mattermost_api_client = MagicMock()
        # Original envoyer_message is sync, so MagicMock is appropriate.
        # The warning was due to using AsyncMock for a sync function called with to_thread.
        self.bot.envoyer_message = MagicMock()

    @async_test
    async def test_handle_create_group_command_all_success(self):
        self.bot.authentik_client.create_group.return_value = True
        self.bot.outline_client.create_group.return_value = True
        self.bot.mattermost_api_client.create_channel.return_value = True
        project_name = "super_project"
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": f"@{self.mock_config.BOT_NAME} create_group {project_name}",
                        "channel_id": "channel123",
                        "user_id": "user456",
                    }
                )
            },
        }
        await self.bot.on_message(None, json.dumps(mock_message_data))
        self.bot.authentik_client.create_group.assert_called_once_with(project_name)
        self.bot.outline_client.create_group.assert_called_once_with(project_name)
        self.bot.mattermost_api_client.create_channel.assert_called_once_with(project_name)

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        processing_args, _ = self.bot.envoyer_message.call_args_list[0]
        self.assertEqual(processing_args[0], "channel123")
        self.assertEqual(
            processing_args[1],
            f":hourglass_flowing_sand: Traitement de 'create_group' pour le projet : **`{project_name}`**...",
        )

        summary_args, _ = self.bot.envoyer_message.call_args_list[1]
        self.assertEqual(summary_args[0], "channel123")
        self.assertIn(
            f":rocket: Toutes les ressources demandées pour le projet **`{project_name}`** ont été créées avec succès !", summary_args[1]
        )
        self.assertIn(
            ":white_check_mark: Création du groupe Authentik réussie. (Client configuré : True)", summary_args[1]
        )
        self.assertIn(
            ":white_check_mark: Création de la collection Outline réussie. (Client configuré : True)", summary_args[1]
        )
        self.assertIn(
            ":white_check_mark: Création du canal Mattermost réussie. (Client configuré : True)", summary_args[1]
        )

    @async_test
    async def test_handle_create_group_one_failure(self):
        self.bot.authentik_client.create_group.return_value = True
        self.bot.outline_client.create_group.return_value = False  # Outline fails
        self.bot.mattermost_api_client.create_channel.return_value = True
        project_name = "nebula_project"
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": f"@{self.mock_config.BOT_NAME} create_group {project_name}",
                        "channel_id": "channel789",
                        "user_id": "user123",
                    }
                )
            },
        }
        await self.bot.on_message(None, json.dumps(mock_message_data))

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_args, _ = self.bot.envoyer_message.call_args_list[1]
        self.assertEqual(summary_args[0], "channel789")
        self.assertIn(
            f":warning: Création de groupe partiellement terminée pour le projet **`{project_name}`** :", summary_args[1]
        )
        self.assertIn(
            ":white_check_mark: Création du groupe Authentik réussie. (Client configuré : True)", summary_args[1]
        )
        self.assertIn(":x: Création de la collection Outline échouée. (Client configuré : True)", summary_args[1])
        self.assertIn(
            ":white_check_mark: Création du canal Mattermost réussie. (Client configuré : True)", summary_args[1]
        )

    @async_test
    async def test_handle_create_group_authentik_client_not_initialized(self):
        self.bot.authentik_client = None
        self.bot.outline_client.create_group.return_value = True
        self.bot.mattermost_api_client.create_channel.return_value = True
        project_name = "no_auth_project"
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": f"@{self.mock_config.BOT_NAME} create_group {project_name}",
                        "channel_id": "channel_no_auth",
                        "user_id": "user_no_auth",
                    }
                )
            },
        }
        await self.bot.on_message(None, json.dumps(mock_message_data))

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_args, _ = self.bot.envoyer_message.call_args_list[1]
        self.assertEqual(summary_args[0], "channel_no_auth")
        self.assertIn(
            f":rocket: Toutes les ressources demandées pour le projet **`{project_name}`** ont été créées avec succès !", summary_args[1]
        )
        self.assertIn(":x: Création du groupe Authentik échouée. (Client configuré : False)", summary_args[1])
        self.assertIn(
            ":white_check_mark: Création de la collection Outline réussie. (Client configuré : True)", summary_args[1]
        )
        self.assertIn(
            ":white_check_mark: Création du canal Mattermost réussie. (Client configuré : True)", summary_args[1]
        )

    @async_test
    async def test_handle_create_group_mattermost_client_not_initialized(self):
        self.bot.mattermost_api_client = None
        self.bot.authentik_client.create_group.return_value = True
        self.bot.outline_client.create_group.return_value = True
        project_name = "no_mattermost_project"
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": f"@{self.mock_config.BOT_NAME} create_group {project_name}",
                        "channel_id": "channel_no_mm",
                        "user_id": "user_no_mm",
                    }
                )
            },
        }
        await self.bot.on_message(None, json.dumps(mock_message_data))

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_args, _ = self.bot.envoyer_message.call_args_list[1]
        self.assertEqual(summary_args[0], "channel_no_mm")
        self.assertIn(
            f":rocket: Toutes les ressources demandées pour le projet **`{project_name}`** ont été créées avec succès !", summary_args[1]
        )
        self.assertIn(
            ":white_check_mark: Création du groupe Authentik réussie. (Client configuré : True)", summary_args[1]
        )
        self.assertIn(
            ":white_check_mark: Création de la collection Outline réussie. (Client configuré : True)", summary_args[1]
        )
        self.assertIn(":x: Création du canal Mattermost échouée. (Client configuré : False)", summary_args[1])

    @async_test
    async def test_handle_simple_mention_unknown_command(self):
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": f"@{self.mock_config.BOT_NAME} hello there",
                        "channel_id": "general",
                        "user_id": "user007",
                    }
                )
            },
        }
        await self.bot.on_message(None, json.dumps(mock_message_data))
        self.bot.envoyer_message.assert_called_once_with(
            "general",
            f":question: Commande inconnue : **`hello`**. Essayez `{self.bot.bot_name_mention} help` pour une liste des commandes disponibles.",
        )

    @async_test
    async def test_handle_mention_no_command(self):
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {"message": f"@{self.mock_config.BOT_NAME}", "channel_id": "town-square", "user_id": "user008"}
                )
            },
        }
        await self.bot.on_message(None, json.dumps(mock_message_data))
        self.bot.envoyer_message.assert_called_once_with(
            "town-square",
            f"Bonjour ! Vous m'avez mentionné. Essayez `{self.bot.bot_name_mention} help` pour une liste des commandes.",
        )

    @async_test
    async def test_ignore_non_mention_message(self):
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {"message": "Hello world, just a regular message.", "channel_id": "random", "user_id": "user111"}
                )
            },
        }
        await self.bot.on_message(None, json.dumps(mock_message_data))
        self.bot.envoyer_message.assert_not_called()

    @async_test
    async def test_ignore_message_not_posted_event(self):
        mock_message_data = {"event": "typing", "data": {"user_id": "user123"}}
        await self.bot.on_message(None, json.dumps(mock_message_data))
        self.bot.envoyer_message.assert_not_called()

    @async_test
    async def test_create_group_no_project_name(self):
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": f"@{self.mock_config.BOT_NAME} create_group ",
                        "channel_id": "channel_no_proj",
                        "user_id": "user_no_proj",
                    }
                )
            },
        }
        await self.bot.on_message(None, json.dumps(mock_message_data))
        self.bot.authentik_client.create_group.assert_not_called()
        self.bot.outline_client.create_group.assert_not_called()
        self.bot.mattermost_api_client.create_channel.assert_not_called()
        self.bot.envoyer_message.assert_called_once_with(
            "channel_no_proj",
            f":warning: **Erreur :** Le nom du projet est requis. Utilisation : `{self.bot.bot_name_mention} create_group <nomDuProjet>`",
        )

    def test_parse_command_from_mention_logic(self):
        self.assertEqual(self.bot._parse_command_from_mention("help"), ("help", None))
        self.assertEqual(self.bot._parse_command_from_mention("help   "), ("help", None))
        self.assertEqual(
            self.bot._parse_command_from_mention("create_group MyNew Project"), ("create_group", "MyNew Project")
        )
        self.assertEqual(
            self.bot._parse_command_from_mention("create_group    MyNew Project"), ("create_group", "MyNew Project")
        )
        self.assertEqual(self.bot._parse_command_from_mention("create_group"), ("create_group", None))
        self.assertEqual(
            self.bot._parse_command_from_mention("create_group  My Project  "), ("create_group", "My Project")
        )
        self.assertEqual(
            self.bot._parse_command_from_mention("Create_Group MyCapsProject"), ("create_group", "MyCapsProject")
        )
        self.assertEqual(self.bot._parse_command_from_mention("   anotherCommand"), ("anothercommand", None))
        self.assertEqual(self.bot._parse_command_from_mention(""), (None, None))
        self.assertEqual(self.bot._parse_command_from_mention("   "), (None, None))


if __name__ == "__main__":
    unittest.main()
