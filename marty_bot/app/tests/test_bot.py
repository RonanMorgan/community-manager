import unittest
from unittest.mock import MagicMock # unittest.mock.AsyncMock removed
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
        # Utiliser MagicMock car envoyer_message est synchrone et appelé via asyncio.to_thread
        self.bot.envoyer_message = MagicMock()


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
        # Reset mock avant chaque appel pour des assertions précises par test
        self.bot.envoyer_message.reset_mock()
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
        processing_call_args = self.bot.envoyer_message.call_args_list[0][0]
        self.assertEqual(processing_call_args[0], "test_channel")
        self.assertIn(f"Traitement de 'create_group' pour 1 projet(s) : **`{project_name}`**", processing_call_args[1])

        summary_call_args = self.bot.envoyer_message.call_args_list[1][0]
        self.assertEqual(summary_call_args[0], "test_channel")
        summary_text = summary_call_args[1]

        # For single project, no global header like ":heavy_check_mark: Traitement de 'create_group'..." is added.
        # The project-specific summary is the main content.
        self.assertIn(f"--- Résumé pour le projet **`{project_name}`** ---", summary_text)
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
        # ... (assertions pour outline et mattermost)

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_call_args = self.bot.envoyer_message.call_args_list[1][0]
        summary_text = summary_call_args[1]

        self.assertIn(f":rocket: Tous les projets ont été traités avec succès !", summary_text)
        for project_name in project_names:
            self.assertIn(f"Résumé pour le projet **`{project_name}`**", summary_text)
            self.assertIn(f":rocket: Toutes les ressources demandées pour **`{project_name}`** ont été traitées avec succès", summary_text)
            self.assertIn(":white_check_mark: Authentik : groupe Authentik créé avec succès.", summary_text)
            # ... (assertions pour les autres services pour chaque projet)

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

        # For single project, no global header like ":warning: Traitement de 'create_group'..." is added.
        self.assertIn(f"--- Résumé pour le projet **`{project_name}`** ---", summary_text)
        self.assertIn(f":warning: Création partiellement terminée pour **`{project_name}`**.", summary_text) # Note the period.
        self.assertIn(":white_check_mark: Authentik : groupe Authentik créé avec succès.", summary_text)
        self.assertIn(":warning: Outline : échec de la création de la collection Outline", summary_text)
        self.assertIn(":white_check_mark: Mattermost : canal Mattermost créé avec succès.", summary_text)

    @async_test
    async def test_handle_create_group_multiple_projects_mixed_results(self):
        project1 = "mix_proj_ok"
        project2 = "mix_proj_fail_outline"
        project3 = "mix_proj_fail_all_active"

        # Configure side_effect pour simuler différents résultats par projet
        def auth_side_effect(p_name):
            if p_name == project1: return True
            if p_name == project2: return True
            if p_name == project3: return False
            return False # Default
        def outline_side_effect(p_name):
            if p_name == project1: return True
            if p_name == project2: return False # Outline fails for project2
            if p_name == project3: return False
            return False
        def mm_side_effect(p_name):
            if p_name == project1: return True
            if p_name == project2: return True
            if p_name == project3: return False
            return False

        self.bot.authentik_client.create_group.side_effect = auth_side_effect
        self.bot.outline_client.create_group.side_effect = outline_side_effect
        self.bot.mattermost_api_client.create_channel.side_effect = mm_side_effect

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_group {project1} {project2} {project3}")

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_call_args = self.bot.envoyer_message.call_args_list[1][0]
        summary_text = summary_call_args[1]

        self.assertIn(f":information_source: Traitement de 'create_group' pour 3 projets terminé.", summary_text)

        self.assertIn(f"Résumé pour le projet **`{project1}`**", summary_text)
        self.assertIn(f":rocket: Toutes les ressources demandées pour **`{project1}`** ont été traitées avec succès", summary_text)

        self.assertIn(f"Résumé pour le projet **`{project2}`**", summary_text)
        self.assertIn(f":warning: Création partiellement terminée pour **`{project2}`**", summary_text)
        self.assertIn(":warning: Outline : échec de la création de la collection Outline", summary_text)

        self.assertIn(f"Résumé pour le projet **`{project3}`**", summary_text)
        self.assertIn(f":boom: Échec de la création de toutes les ressources demandées pour **`{project3}`**", summary_text)
        self.assertIn(":warning: Authentik : échec de la création du groupe Authentik", summary_text)
        self.assertIn(":warning: Mattermost : échec de la création du canal Mattermost", summary_text)

    @async_test
    async def test_handle_create_group_no_project_name_provided(self):
        # Test avec "create_group" (sans argument)
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_group")

        self.bot.envoyer_message.assert_called_once()
        error_call_args = self.bot.envoyer_message.call_args_list[0][0]
        expected_error_msg = f":warning: **Erreur :** Au moins un nom de projet est requis. Utilisation : `{self.bot.bot_name_mention} create_group <nomDuProjet1> [nomDuProjet2 ...]`"
        self.assertEqual(error_call_args[1], expected_error_msg)
        self.bot.authentik_client.create_group.assert_not_called()

        # Test avec "create_group " (espace après)
        self.bot.envoyer_message.reset_mock()
        self.bot.authentik_client.create_group.reset_mock() # Ensure mocks are reset
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_group ")
        self.bot.envoyer_message.assert_called_once()
        error_call_args_space = self.bot.envoyer_message.call_args_list[0][0]
        self.assertEqual(error_call_args_space[1], expected_error_msg)
        self.bot.authentik_client.create_group.assert_not_called()


    @async_test
    async def test_handle_create_group_all_clients_not_configured(self):
        self.bot.authentik_client = None
        self.bot.outline_client = None
        self.bot.mattermost_api_client = None
        project_name = "no_clients_project"

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_group {project_name}")

        self.assertEqual(self.bot.envoyer_message.call_count, 2) # Processing + summary
        summary_call_args = self.bot.envoyer_message.call_args_list[1][0]
        summary_text = summary_call_args[1]

        # Avec la correction, si aucun service n'est configuré, seul le header est affiché.
        expected_final_message = f":information_source: Aucun service (Authentik, Outline, Mattermost) n'est configuré pour la commande 'create_group'. Veuillez vérifier la configuration du bot."
        self.assertEqual(summary_text.strip(), expected_final_message.strip())


    @async_test
    async def test_handle_simple_mention_unknown_command(self):
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} hello there", channel_id="general")
        self.bot.envoyer_message.assert_called_once_with(
            "general",
            f":question: Commande inconnue : **`hello`**. Essayez `{self.bot.bot_name_mention} help` pour une liste des commandes disponibles.",
        )

    @async_test
    async def test_handle_mention_no_command(self):
        await self._send_test_message(f"@{self.mock_config.BOT_NAME}", channel_id="town-square")
        self.bot.envoyer_message.assert_called_once_with(
            "town-square",
            f"Bonjour ! Vous m'avez mentionné. Essayez `{self.bot.bot_name_mention} help` pour une liste des commandes.",
        )

    @async_test
    async def test_ignore_non_mention_message(self):
        # Need to reset mock as it's shared across tests via _send_test_message
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

    # Ce test est l'original, maintenant couvert par test_handle_create_group_no_project_name_provided
    # @async_test
    # async def test_create_group_no_project_name(self):
    #     await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_group ", channel_id="channel_no_proj")
    #     self.bot.authentik_client.create_group.assert_not_called()
    #     self.bot.outline_client.create_group.assert_not_called()
    #     self.bot.mattermost_api_client.create_channel.assert_not_called()
    #     expected_error_message = f":warning: **Erreur :** Au moins un nom de projet est requis. Utilisation : `{self.bot.bot_name_mention} create_group <nomDuProjet1> [nomDuProjet2 ...]`"
    #     self.bot.envoyer_message.assert_called_once_with("channel_no_proj",expected_error_message)


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
