import unittest
from unittest.mock import MagicMock, patch
import json
import asyncio

from app.bot import MartyBot
from clients.mattermost_client import slugify


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
            "PROJET": {
                "standard": {
                    "mattermost_channel_name_pattern": "projet_{base_name}",
                    "mattermost_channel_type": "O",
                    "authentik_group_name_pattern": "projet_{base_name}",
                },
                "admin": {
                    "mattermost_channel_name_pattern": "projet_{base_name} Admin",
                    "mattermost_channel_type": "P",
                    "authentik_group_name_pattern": "projet_{base_name} Admin",
                },
                "outline": {
                    "collection_name_pattern": "projet_{base_name}",
                    "default_access": "read",
                    "admin_access": "read_write",
                },
            },
            "ANTENNE": {
                "standard": {
                    "mattermost_channel_name_pattern": "antenne_{base_name}",
                    "mattermost_channel_type": "O",
                    "authentik_group_name_pattern": "antenne_{base_name}",
                },
                "admin": {
                    "mattermost_channel_name_pattern": "antenne_{base_name} Admin",
                    "mattermost_channel_type": "P",
                    "authentik_group_name_pattern": "antenne_{base_name} Admin",
                },
                "outline": {
                    "collection_name_pattern": "antenne_{base_name}",
                    "default_access": "read",
                    "admin_access": "read_write",
                },
            },
            "POLES": {
                "standard": {
                    "mattermost_channel_name_pattern": "pole_{base_name}",
                    "mattermost_channel_type": "P",
                    "authentik_group_name_pattern": "pole_{base_name}",
                },
                "admin": {
                    "mattermost_channel_name_pattern": "pole_{base_name} Admin",
                    "mattermost_channel_type": "P",
                    "authentik_group_name_pattern": "pole_{base_name} Admin",
                },
                "outline": {
                    "collection_name_pattern": "pole_{base_name}",
                    "default_access": "read",
                    "admin_access": "read_write",
                },
            },
        }
        self.bot.config = self.mock_config
        self.test_user_id = "test_user_who_posted"

    async def _send_test_message(self, message_text, channel_id="test_channel", user_id=None):
        self.bot.envoyer_message.reset_mock()
        if self.bot.authentik_client:
            self.bot.authentik_client.reset_mock()
        if self.bot.outline_client:
            self.bot.outline_client.reset_mock()
        if self.bot.mattermost_api_client:
            self.bot.mattermost_api_client.reset_mock()
        post_content = {
            "message": message_text,
            "channel_id": channel_id,
            "user_id": user_id if user_id else self.test_user_id,
        }
        mock_message_data = {"event": "posted", "data": {"post": json.dumps(post_content)}}
        await self.bot.on_message(None, json.dumps(mock_message_data))

    @async_test
    async def test_handle_create_projet_command_single_item_success_and_user_added(self):
        project_name = "SuperProjet"
        expected_std_auth_name = f"projet_{project_name}"
        expected_std_mm_name = f"projet_{project_name}"
        expected_adm_auth_name = f"projet_{project_name} Admin"
        expected_adm_mm_name = f"projet_{project_name} Admin"
        expected_outline_coll_name = f"projet_{project_name}"
        mock_channel_data_std = {"id": "std_channel_id_123", "name": slugify(expected_std_mm_name)}
        mock_channel_data_adm = {"id": "adm_channel_id_456", "name": slugify(expected_adm_mm_name)}
        self.bot.authentik_client.create_group.return_value = {"name": expected_std_auth_name, "pk": "fake_pk"}
        self.bot.outline_client.create_group.return_value = {"name": expected_outline_coll_name, "id": "fake_id"}

        def create_channel_side_effect(name, channel_type):
            if name == expected_std_mm_name:
                return mock_channel_data_std
            elif name == expected_adm_mm_name:
                return mock_channel_data_adm
            return None

        self.bot.mattermost_api_client.create_channel.side_effect = create_channel_side_effect
        self.bot.mattermost_api_client.add_user_to_channel.return_value = True
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {project_name}")
        self.bot.authentik_client.create_group.assert_any_call(expected_std_auth_name)
        self.bot.authentik_client.create_group.assert_any_call(expected_adm_auth_name)
        self.bot.outline_client.create_group.assert_called_once_with(expected_outline_coll_name)
        self.bot.mattermost_api_client.create_channel.assert_any_call(expected_std_mm_name, channel_type="O")
        self.bot.mattermost_api_client.create_channel.assert_any_call(expected_adm_mm_name, channel_type="P")
        self.bot.mattermost_api_client.add_user_to_channel.assert_any_call(
            mock_channel_data_std["id"], self.test_user_id
        )
        self.bot.mattermost_api_client.add_user_to_channel.assert_any_call(
            mock_channel_data_adm["id"], self.test_user_id
        )
        self.assertEqual(self.bot.mattermost_api_client.add_user_to_channel.call_count, 2)
        summary_text = self.bot.envoyer_message.call_args_list[1][0][1]
        self.assertIn(f"Création pour projet **`{project_name}`** (entité: *PROJET*)", summary_text)
        self.assertIn(f"Authentik Groupe `{expected_std_auth_name}`: :white_check_mark: Créé.", summary_text)
        self.assertIn(
            f"Mattermost Canal `{expected_std_mm_name}` (type: O): :white_check_mark: Créé (ID: {mock_channel_data_std['id']}). Demandeur ajouté.",
            summary_text,
        )
        self.assertIn(f"Authentik Groupe `{expected_adm_auth_name}`: :white_check_mark: Créé.", summary_text)
        self.assertIn(
            f"Mattermost Canal `{expected_adm_mm_name}` (type: P): :white_check_mark: Créé (ID: {mock_channel_data_adm['id']}). Demandeur ajouté.",
            summary_text,
        )
        self.assertIn(f"Outline Collection `{expected_outline_coll_name}`: :white_check_mark: Collection assurée (créée ou existante).", summary_text)


    @async_test
    async def test_handle_create_projet_command_multiple_items_success(self):
        project_names_input = ["ProjetAlpha", "ProjetBeta"]
        created_channel_ids = {}

        def create_channel_side_effect_multi(name, channel_type):
            channel_id = f"channel_for_{slugify(name)}"
            created_channel_ids[name] = channel_id
            return {"id": channel_id, "name": slugify(name)}

        self.bot.authentik_client.create_group.return_value = {"name": "mocked_auth_group", "pk": "mocked_pk"}
        self.bot.outline_client.create_group.return_value = {"name": "mocked_outline_coll", "id": "mocked_id"}
        self.bot.mattermost_api_client.create_channel.side_effect = create_channel_side_effect_multi
        self.bot.mattermost_api_client.add_user_to_channel.return_value = True
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {' '.join(project_names_input)}")
        self.assertEqual(self.bot.authentik_client.create_group.call_count, len(project_names_input) * 2)
        self.assertEqual(self.bot.outline_client.create_group.call_count, len(project_names_input))
        self.assertEqual(self.bot.mattermost_api_client.create_channel.call_count, len(project_names_input) * 2)
        self.assertEqual(self.bot.mattermost_api_client.add_user_to_channel.call_count, len(project_names_input) * 2)
        summary_text = self.bot.envoyer_message.call_args_list[1][0][1]
        for name_input in project_names_input:
            self.assertIn(f"Création pour projet **`{name_input}`** (entité: *PROJET*)", summary_text)
            self.assertIn(f"Outline Collection `projet_{name_input}`: :white_check_mark: Collection assurée (créée ou existante).", summary_text)


    @async_test
    async def test_handle_create_antenne_command_multiple_items(self):
        antenne_names_input = ["AntenneEst", "AntenneOuest"]
        self.bot.authentik_client.create_group.return_value = {"name": "mocked_auth_group", "pk": "mocked_pk"}
        self.bot.outline_client.create_group.return_value = {"name": "mocked_outline_coll", "id": "mocked_id"}
        created_channel_ids = {}
        def create_channel_side_effect_multi(name, channel_type):
            channel_id = f"channel_for_{slugify(name)}"
            created_channel_ids[name] = channel_id
            return {"id": channel_id, "name": slugify(name)}
        self.bot.mattermost_api_client.create_channel.side_effect = create_channel_side_effect_multi
        self.bot.mattermost_api_client.add_user_to_channel.return_value = True
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_antenne {' '.join(antenne_names_input)}")
        self.assertEqual(self.bot.authentik_client.create_group.call_count, len(antenne_names_input) * 2)


    @async_test
    async def test_handle_create_pole_command_multiple_items(self):
        pole_names_input = ["PoleAlpha", "PoleBeta", "PoleGamma"]
        self.bot.authentik_client.create_group.return_value = {"name": "mocked_auth_group", "pk": "mocked_pk"}
        self.bot.outline_client.create_group.return_value = {"name": "mocked_outline_coll", "id": "mocked_id"}
        created_channel_ids = {}
        def create_channel_side_effect_multi(name, channel_type):
            channel_id = f"channel_for_{slugify(name)}"
            created_channel_ids[name] = channel_id
            return {"id": channel_id, "name": slugify(name)}
        self.bot.mattermost_api_client.create_channel.side_effect = create_channel_side_effect_multi
        self.bot.mattermost_api_client.add_user_to_channel.return_value = True
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_pole {' '.join(pole_names_input)}")
        self.assertEqual(self.bot.authentik_client.create_group.call_count, len(pole_names_input) * 2)


    @async_test
    async def test_create_commands_no_arg_provided(self):
        commands_to_test = {"create_projet": "projet", "create_antenne": "antenne", "create_pole": "pôle"}
        for cmd, item_type in commands_to_test.items():
            self.bot.envoyer_message.reset_mock()
            await self._send_test_message(f"@{self.mock_config.BOT_NAME} {cmd}")
            self.bot.envoyer_message.assert_called_once()
            sent_message = self.bot.envoyer_message.call_args[0][1]
            self.assertIn(f":warning: Au moins un nom de {item_type} est requis.", sent_message)
            expected_cmd_in_usage = "create_pôle" if cmd == "create_pole" else cmd
            self.assertIn(
                "Usage: `" + self.bot.bot_name_mention + " " + expected_cmd_in_usage + " <Nom1> [Nom2 ...]`",
                sent_message,
            )

    @async_test
    async def test_create_command_matrix_not_loaded(self):
        self.bot.config.PERMISSIONS_MATRIX = {}
        project_name = "TestProjetNoMatrix"
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {project_name}")
        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        final_summary_message = self.bot.envoyer_message.call_args_list[1][0][1]
        self.assertIn(
            f":x: Erreur: Configuration pour l'entité 'PROJET' non trouvée dans la matrice des permissions.",
            final_summary_message,
        )
        self.setUp()

    @async_test
    async def test_create_resources_for_category_client_errors(self):
        project_name_input = "ClientFailProjet"
        self.bot.authentik_client.create_group.return_value = None
        self.bot.outline_client.create_group.return_value = None
        self.bot.mattermost_api_client.create_channel.return_value = None
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {project_name_input}")
        summary_text = self.bot.envoyer_message.call_args_list[1][0][1]
        expected_std_auth_name = f"projet_{project_name_input}"
        expected_std_mm_name = f"projet_{project_name_input}"
        expected_adm_auth_name = f"projet_{project_name_input} Admin"
        expected_adm_mm_name = f"projet_{project_name_input} Admin"
        expected_outline_coll_name = f"projet_{project_name_input}"
        self.assertIn(f"Authentik Groupe `{expected_std_auth_name}`: :warning: Échec/Existe déjà.", summary_text)
        self.assertIn(f"Mattermost Canal `{expected_std_mm_name}` (type: O): :warning: Échec/Existe déjà.", summary_text)
        self.assertIn(f"Authentik Groupe `{expected_adm_auth_name}`: :warning: Échec/Existe déjà.", summary_text)
        self.assertIn(f"Mattermost Canal `{expected_adm_mm_name}` (type: P): :warning: Échec/Existe déjà.", summary_text)
        self.assertIn(f"Outline Collection `{expected_outline_coll_name}`: :warning: Échec création/vérification.", summary_text)


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
        self.bot.envoyer_message.reset_mock()
        mock_message_data = {"event": "posted", "data": {"post": json.dumps( {"message": "Hello world, just a regular message.", "channel_id": "random", "user_id": "user111"})}}
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
        self.assertEqual(self.bot._parse_command_from_mention("create_projet MyNew Project"), ("create_projet", "MyNew Project"))
        self.assertEqual(self.bot._parse_command_from_mention("create_projet    MyNew Project"), ("create_projet", "MyNew Project"))
        self.assertEqual(self.bot._parse_command_from_mention("create_projet"), ("create_projet", None))
        self.assertEqual(self.bot._parse_command_from_mention("create_projet  My Project  "), ("create_projet", "My Project"))
        self.assertEqual(self.bot._parse_command_from_mention("Create_Projet MyCapsProject"), ("create_projet", "MyCapsProject"))
        self.assertEqual(self.bot._parse_command_from_mention("   anotherCommand"), ("anothercommand", None))
        self.assertEqual(self.bot._parse_command_from_mention(""), (None, None))
        self.assertEqual(self.bot._parse_command_from_mention("   "), (None, None))

    @async_test
    async def test_handle_update_all_user_rights_command_success(self):
        """Tests update_all_user_rights (upsert) command success."""
        command_name = "update_all_user_rights"
        self.bot.envoyer_message.reset_mock()
        with patch("app.bot.orchestrate_group_synchronization") as mock_orchestrate:
            mock_orchestrate.return_value = (True, [{"mm_username": "testuser", "service": "AUTHENTIK", "action": "USER_ADDED_TO_AUTHENTIK_GROUP", "status": "SUCCESS", "target_resource_name": "TestGroup",}])
            await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_name}")

            self.bot.envoyer_message.assert_any_call("test_channel", unittest.mock.ANY)
            mock_orchestrate.assert_called_once_with(
                self.bot.authentik_client,
                self.bot.mattermost_api_client,
                self.bot.outline_client,
                self.bot.config.MATTERMOST_TEAM_ID,
                perform_deletions=False,
                fetch_remote_members=False
            )
            self.assertGreaterEqual(self.bot.envoyer_message.call_count, 3)
            found_summary_message = False
            for call_args in self.bot.envoyer_message.call_args_list:
                message_text = call_args[0][1]
                if "Résumé de Mise à jour (upsert) des droits" in message_text:
                    found_summary_message = True
                    break
            self.assertTrue(found_summary_message, f"Summary message not found for command {command_name}")


    @async_test
    async def test_handle_update_user_rights_and_remove_command_success(self):
        """Tests update_user_rights_and_remove command success."""
        command_name = "update_user_rights_and_remove"
        self.bot.envoyer_message.reset_mock()
        with patch("app.bot.orchestrate_group_synchronization") as mock_orchestrate:
            mock_orchestrate.return_value = (True, [{"mm_username": "testuser", "service": "AUTHENTIK", "action": "USER_REMOVED_FROM_AUTHENTIK_GROUP", "status": "SUCCESS", "target_resource_name": "TestGroupRemove"}])
            await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_name}")
            self.bot.envoyer_message.assert_any_call("test_channel", unittest.mock.ANY)
            mock_orchestrate.assert_called_once_with(
                self.bot.authentik_client,
                self.bot.mattermost_api_client,
                self.bot.outline_client,
                self.bot.config.MATTERMOST_TEAM_ID,
                perform_deletions=True,
                fetch_remote_members=True
            )
            self.assertGreaterEqual(self.bot.envoyer_message.call_count, 3)
            found_summary_message = False
            for call_args in self.bot.envoyer_message.call_args_list:
                message_text = call_args[0][1]
                if "Résumé de Suppression/synchronisation des droits" in message_text:
                    found_summary_message = True
                    break
            self.assertTrue(found_summary_message, f"Summary message not found for command {command_name}")


    @async_test
    async def test_sync_commands_orchestration_failure(self):
        commands_to_test = {
            "update_all_user_rights": self.bot._handle_update_all_user_rights_command,
            "update_user_rights_and_remove": self.bot._handle_update_user_rights_and_remove_command,
        }
        for command_key, handler_method in commands_to_test.items():
            with self.subTest(command=command_key):
                self.bot.envoyer_message.reset_mock()
                with patch("app.bot.orchestrate_group_synchronization") as mock_orchestrate:
                    mock_orchestrate.return_value = (False, [])
                    await handler_method(channel_id="test_channel", arg_string=None)
                    self.assertEqual(self.bot.envoyer_message.call_count, 2)
                    final_message_text = self.bot.envoyer_message.call_args_list[1][0][1]
                    self.assertIn("échoué de manière critique durant l'orchestration", final_message_text)

    @async_test
    async def test_sync_commands_no_clients_configured(self):
        commands_to_test = {
            "update_all_user_rights": self.bot._handle_update_all_user_rights_command,
            "update_user_rights_and_remove": self.bot._handle_update_user_rights_and_remove_command,
        }
        original_auth_client = self.bot.authentik_client
        self.bot.authentik_client = None

        for command_key, handler_method in commands_to_test.items():
            with self.subTest(command=command_key):
                self.bot.envoyer_message.reset_mock()
                await handler_method(channel_id="test_channel", arg_string=None)
                self.assertEqual(self.bot.envoyer_message.call_count, 2)
                error_message_text = self.bot.envoyer_message.call_args_list[1][0][1]
                self.assertIn("Le bot n'est pas correctement configuré", error_message_text)

        self.bot.authentik_client = original_auth_client


if __name__ == "__main__":
    unittest.main()
