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
        # Replace the real envoyer_message with an AsyncMock for testing message content
        self.bot.envoyer_message = unittest.mock.AsyncMock()


    # No longer needed as AsyncMock handles await directly
    # async def async_magic_mock_envoyer_message(self, channel_id, message_text, thread_id=None):
    #     """Helper to allow awaiting the MagicMock for envoyer_message."""
    #     return MagicMock()(channel_id, message_text, thread_id=thread_id)


    async def _send_test_message(self, message_text, channel_id="test_channel"):
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": message_text,
                        "channel_id": channel_id,
                        "user_id": "test_user",
                    }
                )
            },
        }
        # Ensure the message sending mock is reset for each distinct message test
        # self.bot.envoyer_message.reset_mock() # Reset before each call to on_message
        await self.bot.on_message(None, json.dumps(mock_message_data))


    @async_test
    async def test_handle_create_group_single_project_all_success(self):
        self.bot.authentik_client.create_group.return_value = True
        self.bot.outline_client.create_group.return_value = True
        self.bot.mattermost_api_client.create_channel.return_value = True
        project_name = "sole_project"

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_group {project_name}")

        self.bot.authentik_client.create_group.assert_called_once_with(project_name)
        self.bot.outline_client.create_group.assert_called_once_with(project_name)
        self.bot.mattermost_api_client.create_channel.assert_called_once_with(project_name)

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        processing_call_args = self.bot.envoyer_message.call_args_list[0][0] # Get args from first call
        self.assertEqual(processing_call_args[0], "test_channel")
        self.assertIn(f"Traitement de 'create_group' pour 1 projet(s) : **`{project_name}`**", processing_call_args[1])

        summary_call_args = self.bot.envoyer_message.call_args_list[1][0] # Get args from second call
        self.assertEqual(summary_call_args[0], "test_channel")
        summary_text = summary_call_args[1]

        self.assertIn(f":heavy_check_mark: Traitement de 'create_group' pour **`{project_name}`** terminé.", summary_text)
        self.assertIn(f"Résumé pour le projet **`{project_name}`**", summary_text)
        self.assertIn(f":rocket: Toutes les ressources demandées pour **`{project_name}`** ont été traitées avec succès", summary_text)
        self.assertIn(":white_check_mark: Authentik : groupe Authentik créé avec succès.", summary_text)
        self.assertIn(":white_check_mark: Outline : collection Outline créée avec succès.", summary_text)
        self.assertIn(":white_check_mark: Mattermost : canal Mattermost créé avec succès.", summary_text)

    @async_test
    async def test_handle_create_group_multiple_projects_all_success(self):
        self.bot.authentik_client.create_group.return_value = True
        self.bot.outline_client.create_group.return_value = True
        self.bot.mattermost_api_client.create_channel.return_value = True
        project_names = ["multi_proj1", "multi_proj2"]

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_group {' '.join(project_names)}")

        self.assertEqual(self.bot.authentik_client.create_group.call_count, 2)
        self.bot.authentik_client.create_group.assert_any_call(project_names[0])
        self.bot.authentik_client.create_group.assert_any_call(project_names[1])

        self.assertEqual(self.bot.outline_client.create_group.call_count, 2)
        self.bot.outline_client.create_group.assert_any_call(project_names[0])
        self.bot.outline_client.create_group.assert_any_call(project_names[1])

        self.assertEqual(self.bot.mattermost_api_client.create_channel.call_count, 2)
        self.bot.mattermost_api_client.create_channel.assert_any_call(project_names[0])
        self.bot.mattermost_api_client.create_channel.assert_any_call(project_names[1])

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_call_args = self.bot.envoyer_message.call_args_list[1][0]
        summary_text = summary_call_args[1]

        self.assertIn(f":rocket: Tous les projets ont été traités avec succès !", summary_text)
        for project_name in project_names:
            self.assertIn(f"Résumé pour le projet **`{project_name}`**", summary_text)
            self.assertIn(f":rocket: Toutes les ressources demandées pour **`{project_name}`** ont été traitées avec succès", summary_text)
            self.assertIn(":white_check_mark: Authentik : groupe Authentik créé avec succès.", summary_text)

    @async_test
    async def test_handle_create_group_single_project_one_service_fails(self):
        self.bot.authentik_client.create_group.return_value = True
        self.bot.outline_client.create_group.return_value = False # Outline fails
        self.bot.mattermost_api_client.create_channel.return_value = True
        project_name = "partial_fail_project"

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_group {project_name}")

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_call_args = self.bot.envoyer_message.call_args_list[1][0]
        summary_text = summary_call_args[1]

        self.assertIn(f":warning: Traitement de 'create_group' pour **`{project_name}`** terminé avec des avertissements.", summary_text)
        self.assertIn(f"Création partiellement terminée pour **`{project_name}`**", summary_text)
        self.assertIn(":white_check_mark: Authentik : groupe Authentik créé avec succès.", summary_text)
        self.assertIn(":warning: Outline : échec de la création de la collection Outline", summary_text) # Check for warning icon
        self.assertIn(":white_check_mark: Mattermost : canal Mattermost créé avec succès.", summary_text)

    @async_test
    async def test_handle_create_group_multiple_projects_mixed_results(self):
        project1 = "mix_proj_ok"
        project2 = "mix_proj_fail_outline"
        project3 = "mix_proj_fail_all_active"

        # Setup mock return values
        # Project 1: All success
        self.bot.authentik_client.create_group.side_effect = lambda p_name: True if p_name == project1 else self.bot.authentik_client.create_group.side_effect(p_name) # Original side effect for others
        self.bot.outline_client.create_group.side_effect = lambda p_name: True if p_name == project1 else self.bot.outline_client.create_group.side_effect(p_name)
        self.bot.mattermost_api_client.create_channel.side_effect = lambda p_name: True if p_name == project1 else self.bot.mattermost_api_client.create_channel.side_effect(p_name)

        # Project 2: Outline fails
        self.bot.authentik_client.create_group.side_effect = lambda p_name: True if p_name == project2 else (True if p_name == project1 else self.bot.authentik_client.create_group.side_effect(p_name))
        self.bot.outline_client.create_group.side_effect = lambda p_name: False if p_name == project2 else (True if p_name == project1 else self.bot.outline_client.create_group.side_effect(p_name))
        self.bot.mattermost_api_client.create_channel.side_effect = lambda p_name: True if p_name == project2 else (True if p_name == project1 else self.bot.mattermost_api_client.create_channel.side_effect(p_name))

        # Project 3: All active services fail
        self.bot.authentik_client.create_group.side_effect = lambda p_name: False if p_name == project3 else (True if p_name in [project1, project2] else self.bot.authentik_client.create_group.side_effect(p_name))
        self.bot.outline_client.create_group.side_effect = lambda p_name: False if p_name == project3 else (False if p_name == project2 else (True if p_name == project1 else self.bot.outline_client.create_group.side_effect(p_name)))
        self.bot.mattermost_api_client.create_channel.side_effect = lambda p_name: False if p_name == project3 else (True if p_name in [project1, project2] else self.bot.mattermost_api_client.create_channel.side_effect(p_name))


        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_group {project1} {project2} {project3}")

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_call_args = self.bot.envoyer_message.call_args_list[1][0]
        summary_text = summary_call_args[1]

        self.assertIn(f":information_source: Traitement de 'create_group' pour 3 projets terminé.", summary_text)

        # Check Project 1 (all success)
        self.assertIn(f"Résumé pour le projet **`{project1}`**", summary_text)
        self.assertIn(f":rocket: Toutes les ressources demandées pour **`{project1}`** ont été traitées avec succès", summary_text)

        # Check Project 2 (outline fails)
        self.assertIn(f"Résumé pour le projet **`{project2}`**", summary_text)
        self.assertIn(f":warning: Création partiellement terminée pour **`{project2}`**", summary_text)
        self.assertIn(":warning: Outline : échec de la création de la collection Outline", summary_text)

        # Check Project 3 (all active fail)
        self.assertIn(f"Résumé pour le projet **`{project3}`**", summary_text)
        self.assertIn(f":boom: Échec de la création de toutes les ressources demandées pour **`{project3}`**", summary_text)
        self.assertIn(":warning: Authentik : échec de la création du groupe Authentik", summary_text) # Authentik fails
        self.assertIn(":warning: Mattermost : échec de la création du canal Mattermost", summary_text) # MM fails


    @async_test
    async def test_handle_create_group_no_project_name_provided(self):
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_group")

        # Only one message should be sent (the error message)
        self.bot.envoyer_message.assert_called_once()
        error_call_args = self.bot.envoyer_message.call_args_list[0][0]

        self.assertEqual(error_call_args[0], "test_channel")
        self.assertIn(":warning: **Erreur :** Au moins un nom de projet est requis.", error_call_args[1])
        self.assertIn(f"Utilisation : `{self.bot.bot_name_mention} create_group <nomDuProjet1> [nomDuProjet2 ...]`", error_call_args[1])

        self.bot.authentik_client.create_group.assert_not_called()
        self.bot.outline_client.create_group.assert_not_called()
        self.bot.mattermost_api_client.create_channel.assert_not_called()

    @async_test
    async def test_handle_create_group_all_clients_not_configured(self):
        self.bot.authentik_client = None
        self.bot.outline_client = None
        self.bot.mattermost_api_client = None
        project_name = "no_clients_project"

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_group {project_name}")

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_call_args = self.bot.envoyer_message.call_args_list[1][0]
        summary_text = summary_call_args[1]

        self.assertIn(":information_source: Aucun service (Authentik, Outline, Mattermost) n'est configuré", summary_text)
        self.assertNotIn(f"Résumé pour le projet **`{project_name}`**", summary_text) # No project summary if no services are on

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

        # This test specifically tests the scenario where "create_group " (with a space, or nothing) is sent,
        # which results in project_names_str being None or empty after split by the command parser.
        # The handler _handle_create_group_command catches this at the beginning.
        expected_error_message = f":warning: **Erreur :** Au moins un nom de projet est requis. Utilisation : `{self.bot.bot_name_mention} create_group <nomDuProjet1> [nomDuProjet2 ...]`"
        self.bot.envoyer_message.assert_called_once_with("channel_no_proj", expected_error_message)

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
