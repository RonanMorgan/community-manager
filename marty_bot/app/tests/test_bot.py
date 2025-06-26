import unittest
from unittest.mock import MagicMock  # Removed 'call'
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
        self.bot.envoyer_message = MagicMock()

        self.mock_config.PERMISSIONS_MATRIX = {
            "PROJET": {"category": "PROJET", "mattermost": {"channel_type": "O"}, "outline": {"access": "read"}},
            "PROJET_ADMIN": {
                "category": "PROJET_ADMIN",
                "mattermost": {"channel_type": "P"},
                "outline": {"access": "rw"},
            },
            "ANTENNE": {"category": "ANTENNE", "mattermost": {"channel_type": "O"}, "outline": {"access": "read"}},
            "ANTENNE_ADMIN": {
                "category": "ANTENNE_ADMIN",
                "mattermost": {"channel_type": "P"},
                "outline": {"access": "rw"},
            },
            "POLES": {"category": "POLES", "mattermost": {"channel_type": "P"}, "outline": {"access": "read"}},
            "POLES_ADMIN": {
                "category": "POLES_ADMIN",
                "mattermost": {"channel_type": "P"},
                "outline": {"access": "rw"},
            },
        }
        self.bot.config = self.mock_config

    async def _send_test_message(self, message_text, channel_id="test_channel"):
        self.bot.envoyer_message.reset_mock()
        self.bot.authentik_client.reset_mock()
        self.bot.outline_client.reset_mock()
        self.bot.mattermost_api_client.reset_mock()

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
        await self.bot.on_message(None, json.dumps(mock_message_data))

    @async_test
    async def test_handle_create_projet_command_single_item_success(self):
        project_name = "SuperProjet"
        self.bot.authentik_client.create_group.return_value = True
        self.bot.outline_client.create_group.return_value = "CREATED"
        self.bot.mattermost_api_client.create_channel.return_value = True

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {project_name}")

        admin_project_name = f"{project_name} Admin"
        self.bot.authentik_client.create_group.assert_any_call(project_name)
        self.bot.authentik_client.create_group.assert_any_call(admin_project_name)
        self.bot.outline_client.create_group.assert_any_call(project_name)
        self.bot.outline_client.create_group.assert_any_call(admin_project_name)
        self.bot.mattermost_api_client.create_channel.assert_any_call(project_name, channel_type="O")
        self.bot.mattermost_api_client.create_channel.assert_any_call(admin_project_name, channel_type="P")
        self.assertEqual(self.bot.authentik_client.create_group.call_count, 2)
        self.assertEqual(self.bot.outline_client.create_group.call_count, 2)
        self.assertEqual(self.bot.mattermost_api_client.create_channel.call_count, 2)

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        self.assertIn(
            f"Traitement de 'create_projet' pour 1 projet: **`{project_name}`**...",  # noqa: F541
            self.bot.envoyer_message.call_args_list[0][0][1],
        )
        summary_text = self.bot.envoyer_message.call_args_list[1][0][1]
        self.assertIn(f"Création pour projet **`{project_name}`**", summary_text)  # noqa: F541
        self.assertIn(f"Sous-groupe/canal **`{project_name}`** (basé sur *PROJET*)", summary_text)  # noqa: F541
        self.assertIn("Mattermost: :white_check_mark: Canal (Public) créé.", summary_text)
        self.assertIn(
            f"Sous-groupe/canal **`{admin_project_name}`** (basé sur *PROJET_ADMIN*)", summary_text
        )  # noqa: F541
        self.assertIn("Mattermost: :white_check_mark: Canal (Privé) créé.", summary_text)

    @async_test
    async def test_handle_create_projet_command_multiple_items_success(self):
        project_names = ["ProjetAlpha", "ProjetBeta"]
        self.bot.authentik_client.create_group.return_value = True
        self.bot.outline_client.create_group.return_value = "CREATED"
        self.bot.mattermost_api_client.create_channel.return_value = True

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {' '.join(project_names)}")

        self.assertEqual(self.bot.authentik_client.create_group.call_count, 4)
        self.assertEqual(self.bot.outline_client.create_group.call_count, 4)
        self.assertEqual(self.bot.mattermost_api_client.create_channel.call_count, 4)

        for name in project_names:
            admin_name = f"{name} Admin"
            self.bot.authentik_client.create_group.assert_any_call(name)
            self.bot.authentik_client.create_group.assert_any_call(admin_name)
            self.bot.mattermost_api_client.create_channel.assert_any_call(name, channel_type="O")
            self.bot.mattermost_api_client.create_channel.assert_any_call(admin_name, channel_type="P")

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        initial_msg_text = self.bot.envoyer_message.call_args_list[0][0][1]
        self.assertIn(
            f"Traitement de 'create_projet' pour 2 projets: **`{'`, `'.join(project_names)}`**...", initial_msg_text
        )  # noqa: F541

        summary_text = self.bot.envoyer_message.call_args_list[1][0][1]
        self.assertIn("Résumé global pour la commande `create_projet`", summary_text)
        for name in project_names:
            self.assertIn(f"Création pour projet **`{name}`**", summary_text)  # noqa: F541
            self.assertIn(f"Sous-groupe/canal **`{name} Admin`**", summary_text)  # noqa: F541

    @async_test
    async def test_handle_create_antenne_command_multiple_items(self):
        antenne_names = ["AntenneEst", "AntenneOuest"]
        self.bot.authentik_client.create_group.return_value = True
        self.bot.outline_client.create_group.return_value = "CREATED"
        self.bot.mattermost_api_client.create_channel.return_value = True

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_antenne {' '.join(antenne_names)}")
        self.assertEqual(self.bot.mattermost_api_client.create_channel.call_count, 4)
        for name in antenne_names:
            self.bot.mattermost_api_client.create_channel.assert_any_call(name, channel_type="O")
            self.bot.mattermost_api_client.create_channel.assert_any_call(f"{name} Admin", channel_type="P")

    @async_test
    async def test_handle_create_pole_command_multiple_items(self):
        pole_names = ["PoleAlpha", "PoleBeta", "PoleGamma"]
        self.bot.authentik_client.create_group.return_value = True
        self.bot.outline_client.create_group.return_value = "CREATED"
        self.bot.mattermost_api_client.create_channel.return_value = True

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_pole {' '.join(pole_names)}")
        self.assertEqual(self.bot.mattermost_api_client.create_channel.call_count, 6)
        for name in pole_names:
            self.bot.mattermost_api_client.create_channel.assert_any_call(name, channel_type="P")
            self.bot.mattermost_api_client.create_channel.assert_any_call(f"{name} Admin", channel_type="P")

    @async_test
    async def test_create_commands_no_arg_provided(self):
        commands_to_test = {"create_projet": "projet", "create_antenne": "antenne", "create_pole": "pôle"}
        for cmd, item_type in commands_to_test.items():
            self.bot.envoyer_message.reset_mock()
            await self._send_test_message(f"@{self.mock_config.BOT_NAME} {cmd}")
            self.bot.envoyer_message.assert_called_once()
            sent_message = self.bot.envoyer_message.call_args[0][1]
            self.assertIn(f":warning: Au moins un nom de {item_type} est requis.", sent_message)
            self.assertIn(f"Usage: `{self.bot.bot_name_mention} {cmd} <Nom1> [Nom2 ...]`", sent_message)

    @async_test
    async def test_create_command_matrix_not_loaded(self):
        self.bot.config.PERMISSIONS_MATRIX = {}
        project_name = "TestProjetNoMatrix"
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {project_name}")
        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        error_message = self.bot.envoyer_message.call_args_list[1][0][1]
        self.assertIn(":x: Erreur: La matrice des permissions n'est pas chargée.", error_message)
        self.setUp()

    @async_test
    async def test_create_resources_for_category_client_errors(self):
        project_name = "ClientFailProjet"
        self.bot.authentik_client.create_group.return_value = False
        self.bot.outline_client.create_group.return_value = "FAILED"
        self.bot.mattermost_api_client.create_channel.return_value = False

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {project_name}")

        summary_text = self.bot.envoyer_message.call_args_list[1][0][1]
        # print(f"DEBUG: summary_text='{summary_text}'")
        self.assertIn("Authentik: :warning: Échec création (ou existe déjà).", summary_text)
        self.assertIn("Outline: :warning: Échec création/vérification.", summary_text)
        self.assertIn("Mattermost: :warning: Échec création (Public) (ou existe déjà).", summary_text)
        self.assertIn("Mattermost: :warning: Échec création (Privé) (ou existe déjà).", summary_text)

    @async_test
    async def test_handle_simple_mention_unknown_command(self):
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} hello there", channel_id="general")
        self.bot.envoyer_message.assert_called_once_with(
            "general",
            f":question: Commande inconnue : **`hello`**. Essayez `{self.bot.bot_name_mention} help` pour une liste des commandes disponibles.",  # noqa: E501
        )

    @async_test
    async def test_handle_mention_no_command(self):
        await self._send_test_message(f"@{self.mock_config.BOT_NAME}", channel_id="town-square")
        self.bot.envoyer_message.assert_called_once_with(
            "town-square",
            f"Bonjour ! Vous m'avez mentionné. Essayez `{self.bot.bot_name_mention} help` pour une liste des commandes.",  # noqa: E501
        )

    @async_test
    async def test_ignore_non_mention_message(self):
        self.bot.envoyer_message.reset_mock()
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
        self.bot.envoyer_message.reset_mock()
        mock_message_data = {"event": "typing", "data": {"user_id": "user123"}}
        await self.bot.on_message(None, json.dumps(mock_message_data))
        self.bot.envoyer_message.assert_not_called()

    def test_parse_command_from_mention_logic(self):
        self.assertEqual(self.bot._parse_command_from_mention("help"), ("help", None))
        self.assertEqual(self.bot._parse_command_from_mention("help   "), ("help", None))
        self.assertEqual(
            self.bot._parse_command_from_mention("create_projet MyNew Project"), ("create_projet", "MyNew Project")
        )
        self.assertEqual(
            self.bot._parse_command_from_mention("create_projet    MyNew Project"), ("create_projet", "MyNew Project")
        )
        self.assertEqual(self.bot._parse_command_from_mention("create_projet"), ("create_projet", None))
        self.assertEqual(
            self.bot._parse_command_from_mention("create_projet  My Project  "), ("create_projet", "My Project")
        )
        self.assertEqual(
            self.bot._parse_command_from_mention("Create_Projet MyCapsProject"), ("create_projet", "MyCapsProject")
        )
        self.assertEqual(self.bot._parse_command_from_mention("   anotherCommand"), ("anothercommand", None))
        self.assertEqual(self.bot._parse_command_from_mention(""), (None, None))
        self.assertEqual(self.bot._parse_command_from_mention("   "), (None, None))


if __name__ == "__main__":
    unittest.main()
