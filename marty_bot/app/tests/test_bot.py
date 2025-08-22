import asyncio
import json
import os  # Added import
import unittest
from unittest.mock import MagicMock, patch

from app.bot import MartyBot
from libraries.services.mattermost import slugify


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
        self.mock_config.BREVO_API_URL = "http://fake-brevo.com"
        self.mock_config.BREVO_API_KEY = "fake_brevo_key"
        self.mock_config.BREVO_DEFAULT_SENDER_EMAIL = "sender@example.com"
        self.mock_config.BREVO_DEFAULT_SENDER_NAME = "Marty Test Sender"
        self.mock_config.DEBUG = False
        self.mock_config.VAULTWARDEN_ORGANIZATION_ID = "fake_vw_org_id"  # Added
        self.mock_config.VAULTWARDEN_SERVER_URL = "http://fake-vw.com"  # Added
        self.mock_config.VAULTWARDEN_CLIENT_ID = "fake_vw_client_id"  # Added for new client init
        self.mock_config.VAULTWARDEN_CLIENT_SECRET = "fake_vw_client_secret"  # Added for new client init

        # Updated PERMISSIONS_MATRIX to include folder_name for Brevo and vaultwarden config
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
                "brevo": {
                    "list_name_pattern": "brevo_projet_{base_name}",
                    "folder_name": "Dossier Projets Test",
                },
                "vaultwarden": {"collection_name_pattern": "VW_Projet_{base_name}"},  # Added
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
                "brevo": {"list_name_pattern": "brevo_antenne_{base_name}"},
                "vaultwarden": {"collection_name_pattern": "VW_Antenne_{base_name}"},  # Added
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
                "brevo": {"list_name_pattern": "brevo_pole_{base_name}"},
                "vaultwarden": {"collection_name_pattern": "VW_Pole_{base_name}"},  # Added
            },
        }

        self.bot = MartyBot(self.mock_config)
        self.bot.authentik_client = MagicMock()
        self.bot.outline_client = MagicMock()
        self.bot.mattermost_api_client = MagicMock()
        self.bot.brevo_client = MagicMock()
        self.bot.nocodb_client = MagicMock()  # Added NocoDB mock
        self.bot.vaultwarden_client = MagicMock()
        self.bot.envoyer_message = MagicMock(return_value="mock_post_id")
        self.test_user_id = "test_user_who_posted"

    async def _send_test_message(self, message_text, channel_id="test_channel", user_id=None):
        self.bot.envoyer_message.reset_mock()
        # Reset all client mocks
        client_attrs_to_reset = [
            "authentik_client",
            "outline_client",
            "mattermost_api_client",
            "brevo_client",
            "nocodb_client",
            "vaultwarden_client",  # Added Vaultwarden client to reset
        ]
        for client_attr in client_attrs_to_reset:
            client_mock = getattr(self.bot, client_attr, None)
            if client_mock:
                client_mock.reset_mock()
        post_content = {
            "message": message_text,
            "channel_id": channel_id,
            "user_id": user_id if user_id else self.test_user_id,
        }
        mock_message_data = {
            "event": "posted",
            "data": {"post": json.dumps(post_content)},
        }
        await self.bot.websocket_handler.on_message(None, json.dumps(mock_message_data))

    @async_test
    async def test_handle_help_command(self):
        original_envoyer_message = self.bot.envoyer_message
        self.bot.envoyer_message = MagicMock(return_value="post_id_help")
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} help")
        self.bot.envoyer_message.assert_called_once()
        args, _ = self.bot.envoyer_message.call_args
        self.assertEqual(args[0], "test_channel")
        help_text_content = args[1]
        self.assertIn("### Commandes disponibles pour MartyBot", help_text_content)
        self.assertIn("* **`create_projet`**", help_text_content)
        self.assertIn(
            f"* `{self.bot.bot_name_mention} create_projet MonProjet1 MonProjet2`",
            help_text_content,
        )
        self.assertIn(
            f"* **`{self.bot.bot_name_mention} update_all_user_rights`**",
            help_text_content,
        )
        self.assertIn(
            "Rôle : S'assure que les utilisateurs présents dans les canaux Mattermost",
            help_text_content,
        )
        self.bot.envoyer_message = original_envoyer_message

    @async_test
    async def test_handle_create_projet_command_single_item_success_and_user_added(
        self,
    ):
        project_name = "SuperProjet"
        expected_std_auth_name = f"projet_{project_name}"
        expected_std_mm_name = f"projet_{project_name}"
        expected_adm_auth_name = f"projet_{project_name} Admin"
        expected_adm_mm_name = f"projet_{project_name} Admin"
        expected_outline_coll_name = f"projet_{project_name}"
        mock_channel_data_std = {
            "id": "std_channel_id_123",
            "name": slugify(expected_std_mm_name),
        }
        mock_channel_data_adm = {
            "id": "adm_channel_id_456",
            "name": slugify(expected_adm_mm_name),
        }
        self.bot.authentik_client.create_group.return_value = {
            "name": expected_std_auth_name,
            "pk": "fake_pk",
        }
        self.bot.outline_client.create_group.return_value = {
            "name": expected_outline_coll_name,
            "id": "fake_id",
        }
        expected_brevo_list_name = f"brevo_projet_{project_name}"
        mocked_folder_id = 12345
        self.bot.brevo_client.get_folder_id_by_name.return_value = mocked_folder_id
        self.bot.brevo_client.get_list_by_name.return_value = None  # Simulate list does not exist initially
        self.bot.brevo_client.create_list.return_value = {
            "name": expected_brevo_list_name,
            "id": "fake_brevo_id",
            "folderId": mocked_folder_id,
        }

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
        self.bot.brevo_client.get_folder_id_by_name.assert_called_once_with("Dossier Projets Test")
        self.bot.brevo_client.get_list_by_name.assert_called_once_with(expected_brevo_list_name)
        self.bot.brevo_client.create_list.assert_called_once_with(expected_brevo_list_name, folder_id=mocked_folder_id)
        self.bot.mattermost_api_client.create_channel.assert_any_call(expected_std_mm_name, channel_type="O")
        self.bot.mattermost_api_client.create_channel.assert_any_call(expected_adm_mm_name, channel_type="P")
        self.bot.mattermost_api_client.add_user_to_channel.assert_any_call(
            mock_channel_data_std["id"], self.test_user_id
        )
        self.bot.mattermost_api_client.add_user_to_channel.assert_any_call(
            mock_channel_data_adm["id"], self.test_user_id
        )
        self.assertEqual(self.bot.mattermost_api_client.add_user_to_channel.call_count, 2)
        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_text = self.bot.envoyer_message.call_args_list[1][0][1]
        self.assertIn(
            f"Création pour projet **`{project_name}`** (entité: *PROJET*)",
            summary_text,
        )
        self.assertIn(
            f"Authentik Groupe `{expected_std_auth_name}`: :white_check_mark: Créé.",
            summary_text,
        )
        self.assertIn(
            f"Mattermost Canal `{expected_std_mm_name}` (type: O): :white_check_mark: Créé (ID: {mock_channel_data_std['id']}). Demandeur ajouté.",
            summary_text,
        )
        self.assertIn(
            f"Authentik Groupe `{expected_adm_auth_name}`: :white_check_mark: Créé.",
            summary_text,
        )
        self.assertIn(
            f"Mattermost Canal `{expected_adm_mm_name}` (type: P): :white_check_mark: Créé (ID: {mock_channel_data_adm['id']}). Demandeur ajouté.",
            summary_text,
        )
        self.assertIn(
            f"Outline Collection `{expected_outline_coll_name}`: :white_check_mark: Collection assurée (créée ou existante).",
            summary_text,
        )
        self.assertIn(
            f"Brevo Liste `{expected_brevo_list_name}` (Dossier: 'Dossier Projets Test', ID: {mocked_folder_id}): :white_check_mark: Créée",
            summary_text,
        )

    @async_test
    async def test_handle_create_projet_command_multiple_items_success(self):
        project_names_input = ["ProjetAlpha", "ProjetBeta"]
        self.bot.authentik_client.create_group.return_value = {
            "name": "mocked_auth_group",
            "pk": "mocked_pk",
        }
        self.bot.outline_client.create_group.return_value = {
            "name": "mocked_outline_coll",
            "id": "mocked_id",
        }
        self.bot.brevo_client.get_folder_id_by_name.return_value = 123  # Mock folder ID for these tests
        self.bot.brevo_client.get_list_by_name.return_value = None
        # Ensure the side_effect lambda for create_list accepts folder_id
        self.bot.brevo_client.create_list.side_effect = lambda name, folder_id: {
            "name": name,
            "id": f"brevo_id_{name}",
            "folderId": folder_id,
        }
        self.bot.mattermost_api_client.create_channel.return_value = {
            "id": "mock_channel_id",
            "name": "mock_channel_name",
        }
        self.bot.mattermost_api_client.add_user_to_channel.return_value = True
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {' '.join(project_names_input)}")
        self.assertEqual(
            self.bot.authentik_client.create_group.call_count,
            len(project_names_input) * 2,
        )
        self.assertEqual(self.bot.outline_client.create_group.call_count, len(project_names_input))
        self.assertEqual(self.bot.brevo_client.create_list.call_count, len(project_names_input))
        self.assertEqual(
            self.bot.mattermost_api_client.create_channel.call_count,
            len(project_names_input) * 2,
        )
        self.assertEqual(
            self.bot.mattermost_api_client.add_user_to_channel.call_count,
            len(project_names_input) * 2,
        )
        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_text = self.bot.envoyer_message.call_args_list[1][0][1]
        for name_input in project_names_input:
            expected_brevo_list_name = f"brevo_projet_{name_input}"
            self.assertIn(
                f"Création pour projet **`{name_input}`** (entité: *PROJET*)",
                summary_text,
            )
            self.assertIn(
                f"Outline Collection `projet_{name_input}`: :white_check_mark: Collection assurée (créée ou existante).",
                summary_text,
            )
            self.assertIn(
                f"Brevo Liste `{expected_brevo_list_name}` (Dossier: 'Dossier Projets Test', ID: 123): :white_check_mark: Créée",
                summary_text,
            )

    @async_test
    async def test_handle_create_antenne_command_multiple_items(self):
        antenne_names_input = ["AntenneEst", "AntenneOuest"]
        self.mock_config.PERMISSIONS_MATRIX["ANTENNE"]["brevo"][
            "folder_name"
        ] = "Dossier Antennes Test"  # Ensure folder name for test
        # Add NocoDB config for ANTENNE
        self.mock_config.PERMISSIONS_MATRIX["ANTENNE"]["nocodb"] = {
            "base_title_pattern": "nocodb_ant_{base_name}",
            "default_access": "viewer",
            "admin_access": "owner",
        }
        self.bot.authentik_client.create_group.return_value = {
            "name": "mocked_auth_group",
            "pk": "mocked_pk",
        }
        self.bot.outline_client.create_group.return_value = {
            "name": "mocked_outline_coll",
            "id": "mocked_id",
        }
        self.bot.brevo_client.get_folder_id_by_name.return_value = 456
        self.bot.brevo_client.get_list_by_name.return_value = None
        self.bot.brevo_client.create_list.side_effect = lambda name, folder_id: {
            "name": name,
            "id": f"brevo_id_{name}",
            "folderId": folder_id,
        }
        # Mock NocoDB client methods for Antenne
        self.bot.nocodb_client.get_base_by_title.return_value = None  # Simulate base does not exist
        self.bot.nocodb_client.create_base.return_value = {
            "id": "nc_base_ant_id",
            "title": "mock_nc_ant_base",
        }

        self.bot.mattermost_api_client.create_channel.return_value = {"id": "mock_channel_id"}
        self.bot.mattermost_api_client.add_user_to_channel.return_value = True

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_antenne {' '.join(antenne_names_input)}")

        self.assertEqual(
            self.bot.authentik_client.create_group.call_count,
            len(antenne_names_input) * 2,
        )
        self.assertEqual(self.bot.brevo_client.create_list.call_count, len(antenne_names_input))
        self.assertEqual(self.bot.nocodb_client.create_base.call_count, len(antenne_names_input))  # Check NocoDB calls
        self.assertEqual(self.bot.envoyer_message.call_count, 2)

        summary_text = self.bot.envoyer_message.call_args_list[1][0][1]
        for name_input in antenne_names_input:
            expected_brevo_list_name = f"brevo_antenne_{name_input}"
            expected_nocodb_base_title = f"nocodb_ant_{name_input}"
            self.assertIn(
                f"Brevo Liste `{expected_brevo_list_name}` (Dossier: 'Dossier Antennes Test', ID: 456): :white_check_mark: Créée",
                summary_text,
            )
            self.assertIn(
                f"NoCoDB Base `{expected_nocodb_base_title}`: :white_check_mark: Créée",  # Check NocoDB message
                summary_text,
            )

    @async_test
    async def test_handle_create_pole_command_multiple_items(self):
        pole_names_input = ["PoleAlpha", "PoleBeta", "PoleGamma"]
        # Ensure folder_name is in PERMISSIONS_MATRIX for POLES or mock get_folder_id_by_name to return None
        # Assuming we want to test with a folder for poles as well for consistency:
        self.mock_config.PERMISSIONS_MATRIX["POLES"]["brevo"]["folder_name"] = "Dossier Poles Test"
        mocked_pole_folder_id = 789
        self.bot.brevo_client.get_folder_id_by_name.return_value = mocked_pole_folder_id
        # Add NocoDB config for POLES
        self.mock_config.PERMISSIONS_MATRIX["POLES"]["nocodb"] = {
            "base_title_pattern": "nocodb_pole_{base_name}",
            "default_access": "viewer",
            "admin_access": "owner",
        }

        self.bot.authentik_client.create_group.return_value = {
            "name": "mocked_auth_group",
            "pk": "mocked_pk",
        }
        self.bot.outline_client.create_group.return_value = {
            "name": "mocked_outline_coll",
            "id": "mocked_id",
        }
        self.bot.brevo_client.get_list_by_name.return_value = None
        self.bot.brevo_client.create_list.side_effect = lambda name, folder_id: {
            "name": name,
            "id": f"brevo_id_{name}",
            "folderId": folder_id,
        }
        # Mock NocoDB client methods for Pole
        self.bot.nocodb_client.get_base_by_title.return_value = None
        self.bot.nocodb_client.create_base.return_value = {
            "id": "nc_base_pole_id",
            "title": "mock_nc_pole_base",
        }

        self.bot.mattermost_api_client.create_channel.return_value = {"id": "mock_channel_id"}
        self.bot.mattermost_api_client.add_user_to_channel.return_value = True

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_pole {' '.join(pole_names_input)}")

        self.assertEqual(self.bot.authentik_client.create_group.call_count, len(pole_names_input) * 2)
        self.assertEqual(self.bot.brevo_client.create_list.call_count, len(pole_names_input))
        self.assertEqual(self.bot.nocodb_client.create_base.call_count, len(pole_names_input))  # Check NocoDB
        self.assertEqual(self.bot.envoyer_message.call_count, 2)

        summary_text = self.bot.envoyer_message.call_args_list[1][0][1]
        for name_input in pole_names_input:
            expected_brevo_list_name = f"brevo_pole_{name_input}"
            expected_nocodb_base_title = f"nocodb_pole_{name_input}"
            self.assertIn(
                f"Brevo Liste `{expected_brevo_list_name}` (Dossier: 'Dossier Poles Test', ID: {mocked_pole_folder_id}): :white_check_mark: Créée",
                summary_text,
            )
            self.assertIn(
                f"NoCoDB Base `{expected_nocodb_base_title}`: :white_check_mark: Créée",
                summary_text,
            )

    @async_test
    async def test_create_commands_no_arg_provided(self):
        commands_to_test = {
            "create_projet": "projet",
            "create_antenne": "antenne",
            "create_pole": "pôle",
        }
        for cmd, item_type in commands_to_test.items():
            self.bot.envoyer_message.reset_mock()
            await self._send_test_message(f"@{self.mock_config.BOT_NAME} {cmd}")
            self.bot.envoyer_message.assert_called_once()
            sent_message = self.bot.envoyer_message.call_args[0][1]
            self.assertIn(f":warning: Au moins un nom de {item_type} est requis.", sent_message)
            expected_cmd_in_usage = "create_pôle" if cmd == "create_pole" else cmd
            self.assertIn(
                f"Usage: `{self.bot.bot_name_mention} {expected_cmd_in_usage} <Nom1> [Nom2 ...]`",
                sent_message,
            )

    @async_test
    async def test_create_command_matrix_not_loaded(self):
        original_matrix = self.bot.config.PERMISSIONS_MATRIX
        self.bot.config.PERMISSIONS_MATRIX = {}
        project_name = "TestProjetNoMatrix"
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {project_name}")
        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        final_summary_message = self.bot.envoyer_message.call_args_list[1][0][1]
        self.assertIn(
            ":x: Erreur: Configuration pour l'entité 'PROJET' non trouvée dans la matrice des permissions.",
            final_summary_message,
        )
        self.bot.config.PERMISSIONS_MATRIX = original_matrix

    @async_test
    async def test_create_resources_for_category_client_errors(self):
        project_name_input = "ClientFailProjet"
        self.bot.authentik_client.create_group.return_value = None
        self.bot.outline_client.create_group.return_value = None
        self.bot.brevo_client.get_list_by_name.return_value = None
        self.bot.brevo_client.create_list.return_value = None
        self.bot.mattermost_api_client.create_channel.return_value = None
        self.bot.nocodb_client.get_base_by_title.return_value = None  # NocoDB base does not exist
        self.bot.nocodb_client.create_base.return_value = None  # NocoDB creation fails

        # Test for ANTENNE which should have NoCoDB
        # Ensure PERMISSIONS_MATRIX for ANTENNE has nocodb config for this test
        if "nocodb" not in self.mock_config.PERMISSIONS_MATRIX["ANTENNE"]:
            self.mock_config.PERMISSIONS_MATRIX["ANTENNE"]["nocodb"] = {
                "base_title_pattern": "fail_ant_{base_name}",
            }
        antenne_name_input = "ClientFailAntenne"

        # PERMISSIONS_MATRIX for PROJET already defines "folder_name": "Dossier Projets Test" in setUp
        projet_brevo_config = self.mock_config.PERMISSIONS_MATRIX["PROJET"]["brevo"]
        expected_folder_name = projet_brevo_config["folder_name"]
        mocked_folder_id_for_this_test = 5678

        # Use patch.object to mock get_folder_id_by_name for this specific test execution
        # For PROJET (no NocoDB)
        with patch.object(
            self.bot.brevo_client,
            "get_folder_id_by_name",
            return_value=mocked_folder_id_for_this_test,
        ) as mock_get_id_method_projet:
            await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {project_name_input}")
            summary_text_projet = self.bot.envoyer_message.call_args_list[1][0][1]  # Second call is summary
            mock_get_id_method_projet.assert_called_once_with(expected_folder_name)
            self.assertNotIn("NoCoDB Base", summary_text_projet)  # NocoDB should not be mentioned for PROJET

        self.bot.envoyer_message.reset_mock()  # Reset for next command

        # For ANTENNE (with NocoDB)
        antenne_brevo_config = self.mock_config.PERMISSIONS_MATRIX["ANTENNE"]["brevo"]
        antenne_expected_folder_name = antenne_brevo_config.get("folder_name")  # Might be None if not set for Antenne
        antenne_mocked_folder_id = 9012

        with patch.object(
            self.bot.brevo_client,
            "get_folder_id_by_name",
            return_value=antenne_mocked_folder_id,
        ) as mock_get_id_method_antenne:
            await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_antenne {antenne_name_input}")
            summary_text_antenne = self.bot.envoyer_message.call_args_list[1][0][1]
            if antenne_expected_folder_name:
                mock_get_id_method_antenne.assert_called_once_with(antenne_expected_folder_name)
            else:  # If no folder_name for antenne, it shouldn't be called
                mock_get_id_method_antenne.assert_not_called()

            expected_nocodb_base_title = f"fail_ant_{antenne_name_input}"
            self.assertIn(
                f"NoCoDB Base `{expected_nocodb_base_title}`: :warning: Échec création.",
                summary_text_antenne,
            )

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
        mock_message_data = {
            "event": "posted",
            "data": {
                "post": json.dumps(
                    {
                        "message": "Hello world, just a regular message.",
                        "channel_id": "random",
                        "user_id": "user111",
                    }
                )
            },
        }
        await self.bot.websocket_handler.on_message(None, json.dumps(mock_message_data))
        self.bot.envoyer_message.assert_not_called()

    @async_test
    async def test_ignore_message_not_posted_event(self):
        mock_message_data = {"event": "typing", "data": {"user_id": "user123"}}
        await self.bot.websocket_handler.on_message(None, json.dumps(mock_message_data))
        self.bot.envoyer_message.assert_not_called()

    def test_parse_command_from_mention_logic(self):
        self.assertEqual(self.bot._parse_command_from_mention("help"), ("help", None))
        self.assertEqual(self.bot._parse_command_from_mention("help   "), ("help", None))
        self.assertEqual(
            self.bot._parse_command_from_mention("create_projet MyNew Project"),
            ("create_projet", "MyNew Project"),
        )
        self.assertEqual(
            self.bot._parse_command_from_mention("create_projet    MyNew Project"),
            ("create_projet", "MyNew Project"),
        )
        self.assertEqual(
            self.bot._parse_command_from_mention("create_projet"),
            ("create_projet", None),
        )
        self.assertEqual(
            self.bot._parse_command_from_mention("create_projet  My Project  "),
            ("create_projet", "My Project"),
        )
        self.assertEqual(
            self.bot._parse_command_from_mention("Create_Projet MyCapsProject"),
            ("create_projet", "MyCapsProject"),
        )
        self.assertEqual(
            self.bot._parse_command_from_mention("   anotherCommand"),
            ("anothercommand", None),
        )
        self.assertEqual(self.bot._parse_command_from_mention(""), (None, None))
        self.assertEqual(self.bot._parse_command_from_mention("   "), (None, None))

    @patch("app.commands.update_all_user_rights.orchestrate_group_synchronization")
    def test_handle_update_all_user_rights_command_success(self, mock_orchestrate_sync):
        async def actual_test_logic():
            command_name = "update_all_user_rights"
            admin_user_id = "admin_user_for_upsert"
            self.bot.mattermost_api_client.get_user_roles.return_value = [
                "system_admin",
                "system_user",
            ]

            mock_orchestrate_sync.return_value = (
                True,
                [
                    {
                        "mm_username": "testuser",
                        "service": "AUTHENTIK",
                        "action": "USER_ADDED_TO_AUTHENTIK_GROUP",
                        "status": "SUCCESS",
                        "target_resource_name": "TestGroup",
                    }
                ],
            )
            await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_name}", user_id=admin_user_id)

            self.bot.mattermost_api_client.get_user_roles.assert_called_once_with(admin_user_id)
            clients = {
                "authentik": self.bot.authentik_client,
                "mattermost": self.bot.mattermost_api_client,
                "outline": self.bot.outline_client,
                "brevo": self.bot.brevo_client,
                "nocodb": self.bot.nocodb_client,
                "vaultwarden": self.bot.vaultwarden_client,
            }
            mock_orchestrate_sync.assert_called_once_with(
                clients=clients,
                mm_team_id=self.bot.config.MATTERMOST_TEAM_ID,
                sync_mode="MM_TO_TOOLS",
                skip_services=None,
            )
            self.assertGreaterEqual(self.bot.envoyer_message.call_count, 2)
            summary_call_found = False
            for call_args_tuple in self.bot.envoyer_message.call_args_list:
                message_text = call_args_tuple[0][1]
                if "Résumé de Mise à jour (upsert) des droits" in message_text:
                    summary_call_found = True
                    break
            self.assertTrue(summary_call_found, "Summary message for upsert not found.")

        asyncio.run(actual_test_logic())

    @patch("app.commands.update_user_rights_and_remove.differential_sync")
    def test_handle_update_user_rights_and_remove_command_success_admin_user(self, mock_differential_sync):
        async def actual_test_logic():
            command_name = "update_user_rights_and_remove"
            admin_user_id = "admin_user_id_for_sync"
            self.bot.mattermost_api_client.get_user_roles.return_value = [
                "system_admin",
                "system_user",
            ]

            mock_differential_sync.return_value = (
                True,
                [
                    {
                        "mm_username": "testuser",
                        "service": "AUTHENTIK",
                        "action": "USER_REMOVED_FROM_AUTHENTIK_GROUP",
                        "status": "SUCCESS",
                        "target_resource_name": "TestGroupRemove",
                    }
                ],
            )
            await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_name}", user_id=admin_user_id)

            self.bot.mattermost_api_client.get_user_roles.assert_called_once_with(admin_user_id)
            clients = {
                "authentik": self.bot.authentik_client,
                "mattermost": self.bot.mattermost_api_client,
                "outline": self.bot.outline_client,
                "brevo": self.bot.brevo_client,
                "nocodb": self.bot.nocodb_client,
                "vaultwarden": self.bot.vaultwarden_client,
            }
            mock_differential_sync.assert_called_once_with(
                clients=clients,
                mm_team_id=self.bot.config.MATTERMOST_TEAM_ID,
                skip_services=None,
            )
            self.assertGreaterEqual(self.bot.envoyer_message.call_count, 2)
            summary_call_found = False
            for call_args_tuple in self.bot.envoyer_message.call_args_list:
                message_text = call_args_tuple[0][1]
                if "Résumé de Suppression/synchronisation des droits" in message_text:
                    summary_call_found = True
                    break
            self.assertTrue(summary_call_found, "Summary message for full sync/remove not found.")

        asyncio.run(actual_test_logic())

    @async_test
    @patch("app.commands.update_all_user_rights.orchestrate_group_synchronization")
    @patch("app.commands.update_user_rights_and_remove.differential_sync")
    async def test_sync_commands_permission_denied_non_admin(self, mock_differential_sync, mock_sync_all_rights):
        commands_to_test = [
            "update_all_user_rights",
            "update_user_rights_and_remove",
        ]
        non_admin_user_id = "non_admin_user_for_sync"
        self.bot.mattermost_api_client.get_user_roles.return_value = ["system_user"]

        for command_key in commands_to_test:
            with self.subTest(command=command_key):
                self.bot.envoyer_message.reset_mock()
                self.bot.mattermost_api_client.get_user_roles.reset_mock()
                mock_differential_sync.reset_mock()
                mock_sync_all_rights.reset_mock()

                await self._send_test_message(
                    f"@{self.mock_config.BOT_NAME} {command_key}",
                    user_id=non_admin_user_id,
                )

                self.bot.mattermost_api_client.get_user_roles.assert_called_once_with(non_admin_user_id)
                mock_differential_sync.assert_not_called()
                mock_sync_all_rights.assert_not_called()
                self.bot.envoyer_message.assert_called_once()
                sent_message = self.bot.envoyer_message.call_args[0][1]
                self.assertIn(":no_entry_sign: Accès refusé.", sent_message)

    @async_test
    @patch(
        "app.commands.update_all_user_rights.orchestrate_group_synchronization",
        return_value=(False, []),
    )
    @patch(
        "app.commands.update_user_rights_and_remove.differential_sync",
        return_value=(False, []),
    )
    async def test_sync_commands_orchestration_failure_admin_user(
        self,
        mock_differential_sync,
        mock_sync_all_rights,
    ):
        commands_to_test = ["update_all_user_rights", "update_user_rights_and_remove"]
        admin_user_id = "admin_user_for_fail_test"
        self.bot.mattermost_api_client.get_user_roles.return_value = ["system_admin"]

        for command_key in commands_to_test:
            with self.subTest(command=command_key):
                self.bot.envoyer_message.reset_mock()
                self.bot.mattermost_api_client.get_user_roles.reset_mock()
                mock_differential_sync.reset_mock()
                mock_sync_all_rights.reset_mock()

                await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_key}", user_id=admin_user_id)

                self.bot.mattermost_api_client.get_user_roles.assert_called_once_with(admin_user_id)

                if command_key == "update_all_user_rights":
                    mock_sync_all_rights.assert_called_once()
                    mock_differential_sync.assert_not_called()
                else:
                    mock_differential_sync.assert_called_once()
                    mock_sync_all_rights.assert_not_called()

                self.assertEqual(self.bot.envoyer_message.call_count, 2)
                final_message_text = self.bot.envoyer_message.call_args_list[1][0][1]
                self.assertIn(
                    "échoué de manière critique durant l'orchestration",
                    final_message_text,
                )

    @async_test
    async def test_sync_commands_no_clients_configured_admin_user(self):
        commands_to_test = ["update_all_user_rights", "update_user_rights_and_remove"]
        admin_user_id = "admin_user_for_noclient_test"
        self.bot.mattermost_api_client.get_user_roles.return_value = ["system_admin"]

        original_auth_client = self.bot.authentik_client
        self.bot.authentik_client = None

        for command_key in commands_to_test:
            with self.subTest(command=command_key):
                self.bot.envoyer_message.reset_mock()
                self.bot.mattermost_api_client.get_user_roles.reset_mock()

                await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_key}", user_id=admin_user_id)

                self.bot.mattermost_api_client.get_user_roles.assert_called_once_with(admin_user_id)
                self.assertEqual(self.bot.envoyer_message.call_count, 2)
                error_message_text = self.bot.envoyer_message.call_args_list[1][0][1]
                self.assertIn("Le bot n'est pas correctement configuré", error_message_text)
        self.bot.authentik_client = original_auth_client

    @patch.dict(os.environ, {"BW_PASSWORD": "testpassword"})
    @async_test
    async def test_handle_create_projet_calls_vaultwarden_client(self):
        project_name = "VWTestProjet"
        self.bot.authentik_client.create_group.return_value = {
            "name": "any_auth_group",
            "pk": "any_pk",
        }
        self.bot.outline_client.create_group.return_value = {
            "name": "any_outline_coll",
            "id": "any_outline_id",
        }
        self.bot.brevo_client.get_list_by_name.return_value = None
        self.bot.brevo_client.create_list.return_value = {
            "name": "any_brevo_list",
            "id": "any_brevo_id",
            "folderId": 1,
        }
        self.bot.mattermost_api_client.create_channel.return_value = {
            "id": "any_mm_channel_id",
            "name": "any_mm_channel_name",
        }
        self.bot.mattermost_api_client.add_user_to_channel.return_value = True

        expected_vw_collection_name = f"VW_Projet_{project_name}"
        self.bot.vaultwarden_client.create_collection.return_value = "fake_vw_collection_id"

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} create_projet {project_name}")

        self.bot.vaultwarden_client.create_collection.assert_called_once_with(expected_vw_collection_name)

        self.assertEqual(self.bot.envoyer_message.call_count, 2)
        summary_text = self.bot.envoyer_message.call_args_list[1][0][1]
        self.assertIn(
            f"Vaultwarden Collection `{expected_vw_collection_name}`: :white_check_mark: Collection assurée (ID: fake_vw_collection_id).",
            summary_text,
        )

    @async_test
    @patch("app.commands.update_user_rights_and_remove.differential_sync")
    async def test_handle_update_user_rights_and_remove_command_with_skip_nocodb(self, mock_differential_sync):
        command_name = "update_user_rights_and_remove"
        arg_string = "nocodb=false"
        admin_user_id = "admin_for_skip_nocodb"
        self.bot.mattermost_api_client.get_user_roles.return_value = [
            "system_admin",
            "system_user",
        ]
        mock_differential_sync.return_value = (True, [])

        await self._send_test_message(
            f"@{self.mock_config.BOT_NAME} {command_name} {arg_string}",
            user_id=admin_user_id,
        )

        self.bot.mattermost_api_client.get_user_roles.assert_called_once_with(admin_user_id)
        clients = {
            "authentik": self.bot.authentik_client,
            "mattermost": self.bot.mattermost_api_client,
            "outline": self.bot.outline_client,
            "brevo": self.bot.brevo_client,
            "nocodb": self.bot.nocodb_client,
            "vaultwarden": self.bot.vaultwarden_client,
        }
        mock_differential_sync.assert_called_once_with(
            clients=clients,
            mm_team_id=self.bot.config.MATTERMOST_TEAM_ID,
            skip_services=["nocodb"],
        )
        self.assertGreaterEqual(self.bot.envoyer_message.call_count, 1)
        processing_message_call = self.bot.envoyer_message.call_args_list[0][0][1]
        self.assertIn("NoCoDB ignoré", processing_message_call)


if __name__ == "__main__":
    unittest.main()


class TestSendEmailCommand(TestMartyBot):
    def setUp(self):
        super().setUp()
        self.mock_config.BREVO_DEFAULT_SENDER_EMAIL = "marty.sender@example.com"
        self.mock_config.BREVO_DEFAULT_SENDER_NAME = "Marty Test Bot"

    @patch("libraries.group_sync_services.slugify", wraps=slugify)
    @patch("libraries.group_sync_services._map_mm_channel_to_entity_and_base_name")
    def test_handle_send_email_success(self, mock_map_channel, mock_slugify_call):
        async def actual_test_logic():
            command_name = "send_email"
            channel_id = "admin_channel_projet_test"
            user_id = "test_user_admin"
            subject = "Test Email Subject"
            body = "This is the email body."
            arg_string = f"{subject} /// {body}"
            base_name_for_test = "Test Projet"
            entity_key_for_test = "PROJET"

            admin_channel_config = self.mock_config.PERMISSIONS_MATRIX[entity_key_for_test]["admin"]
            admin_channel_display_name = admin_channel_config["mattermost_channel_name_pattern"].format(
                base_name=base_name_for_test
            )
            admin_channel_slug = slugify(admin_channel_display_name)

            def map_channel_side_effect(ch_slug_arg, ch_display_name_arg, entity_config_slice_arg):
                iter_entity_key = list(entity_config_slice_arg.keys())[0]
                if (
                    iter_entity_key == entity_key_for_test
                    and ch_slug_arg == admin_channel_slug
                    and ch_display_name_arg == admin_channel_display_name
                ):
                    return (entity_key_for_test, base_name_for_test, "admin")
                return (None, None, None)

            mock_map_channel.side_effect = map_channel_side_effect

            self.bot.mattermost_api_client.get_channel_by_id.return_value = {
                "id": channel_id,
                "name": admin_channel_slug,
                "display_name": admin_channel_display_name,
            }
            self.bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": user_id}]

            brevo_list_name_pattern_from_config = self.mock_config.PERMISSIONS_MATRIX[entity_key_for_test]["brevo"][
                "list_name_pattern"
            ]
            expected_brevo_list_name = brevo_list_name_pattern_from_config.format(base_name=base_name_for_test)
            self.bot.brevo_client.get_list_by_name.return_value = {
                "id": "brevo_list_123",
                "name": expected_brevo_list_name,
            }
            contacts_on_list = [
                {"email": "contact1@example.com"},
                {"email": "contact2@example.com"},
            ]
            expected_to_contacts = [
                {"email": "contact1@example.com"},
                {"email": "contact2@example.com"},
            ]
            self.bot.brevo_client.get_contacts_from_list.return_value = contacts_on_list
            self.bot.brevo_client.send_transactional_email.return_value = True

            await self._send_test_message(
                f"@{self.mock_config.BOT_NAME} {command_name} {arg_string}",
                user_id=user_id,
                channel_id=channel_id,
            )

            self.assertGreaterEqual(mock_map_channel.call_count, 1)
            projet_config_slice = {"PROJET": self.mock_config.PERMISSIONS_MATRIX["PROJET"]}
            mock_map_channel.assert_any_call(admin_channel_slug, admin_channel_display_name, projet_config_slice)

            self.bot.brevo_client.get_list_by_name.assert_called_once_with(expected_brevo_list_name)
            self.bot.brevo_client.get_contacts_from_list.assert_called_once_with("brevo_list_123")
            self.bot.brevo_client.send_transactional_email.assert_called_once_with(
                subject,
                body,
                self.mock_config.BREVO_DEFAULT_SENDER_EMAIL,
                self.mock_config.BREVO_DEFAULT_SENDER_NAME,
                expected_to_contacts,
                html_content=unittest.mock.ANY,
            )
            self.bot.envoyer_message.assert_called_with(channel_id, unittest.mock.ANY)
            last_call_args = self.bot.envoyer_message.call_args[0]
            self.assertIn(
                ":white_check_mark: Email avec sujet 'Test Email Subject' envoyé",
                last_call_args[1],
            )

        asyncio.run(actual_test_logic())

    @patch("libraries.group_sync_services._map_mm_channel_to_entity_and_base_name")
    def test_handle_send_email_not_admin_channel(self, mock_map_channel):
        async def actual_test_logic():
            command_name = "send_email"
            mock_map_channel.return_value = (None, None, None)
            channel_id = "some_other_channel"
            channel_display_name = "Not An Admin Channel"
            channel_slug = "not-an-admin-channel"
            self.bot.mattermost_api_client.get_channel_by_id.return_value = {
                "id": channel_id,
                "name": channel_slug,
                "display_name": channel_display_name,
            }
            self.bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": "test_user"}]
            await self._send_test_message(
                f"@{self.mock_config.BOT_NAME} {command_name} Subject /// Body",
                user_id="test_user",
                channel_id=channel_id,
            )
            self.bot.envoyer_message.assert_called_with(channel_id, unittest.mock.ANY)
            last_call_args = self.bot.envoyer_message.call_args[0]
            self.assertIn(
                "Cette commande doit être lancée depuis un canal admin",
                last_call_args[1],
            )
            self.bot.brevo_client.send_transactional_email.assert_not_called()

        asyncio.run(actual_test_logic())

    @patch("libraries.group_sync_services._map_mm_channel_to_entity_and_base_name")
    def test_handle_send_email_brevo_list_not_found(self, mock_map_channel):
        async def actual_test_logic():
            command_name = "send_email"
            base_name_for_test = "NoListProjet"
            entity_key_for_test = "PROJET"
            admin_display_name = self.mock_config.PERMISSIONS_MATRIX[entity_key_for_test]["admin"][
                "mattermost_channel_name_pattern"
            ].format(base_name=base_name_for_test)
            admin_slug = slugify(admin_display_name)

            def map_channel_side_effect(ch_slug_arg, ch_display_name_arg, entity_config_slice_arg):
                iter_entity_key = list(entity_config_slice_arg.keys())[0]
                if iter_entity_key == entity_key_for_test and ch_display_name_arg == admin_display_name:
                    return (entity_key_for_test, base_name_for_test, "admin")
                return (None, None, None)

            mock_map_channel.side_effect = map_channel_side_effect
            channel_id = "admin_no_list"
            self.bot.mattermost_api_client.get_channel_by_id.return_value = {
                "id": channel_id,
                "name": admin_slug,
                "display_name": admin_display_name,
            }
            self.bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": "test_user"}]
            self.bot.brevo_client.get_list_by_name.return_value = None
            await self._send_test_message(
                f"@{self.mock_config.BOT_NAME} {command_name} Sujet /// Corps",
                user_id="test_user",
                channel_id=channel_id,
            )
            self.bot.envoyer_message.assert_called_with(channel_id, unittest.mock.ANY)
            last_call_args = self.bot.envoyer_message.call_args[0]
            expected_brevo_list_name = self.mock_config.PERMISSIONS_MATRIX[entity_key_for_test]["brevo"][
                "list_name_pattern"
            ].format(base_name=base_name_for_test)
            self.assertIn(
                f"Liste Brevo '{expected_brevo_list_name}' non trouvée.",
                last_call_args[1],
            )
            self.bot.brevo_client.send_transactional_email.assert_not_called()

        asyncio.run(actual_test_logic())

    @patch("libraries.group_sync_services._map_mm_channel_to_entity_and_base_name")
    def test_handle_send_email_no_recipients_in_list(self, mock_map_channel):
        async def actual_test_logic():
            command_name = "send_email"
            base_name_for_test = "EmptyListProjet"
            entity_key_for_test = "PROJET"
            admin_display_name = self.mock_config.PERMISSIONS_MATRIX[entity_key_for_test]["admin"][
                "mattermost_channel_name_pattern"
            ].format(base_name=base_name_for_test)
            admin_slug = slugify(admin_display_name)

            def map_channel_side_effect(ch_slug_arg, ch_display_name_arg, entity_config_slice_arg):
                iter_entity_key = list(entity_config_slice_arg.keys())[0]
                if iter_entity_key == entity_key_for_test and ch_display_name_arg == admin_display_name:
                    return (entity_key_for_test, base_name_for_test, "admin")
                return (None, None, None)

            mock_map_channel.side_effect = map_channel_side_effect
            channel_id = "admin_empty_list"
            self.bot.mattermost_api_client.get_channel_by_id.return_value = {
                "id": channel_id,
                "name": admin_slug,
                "display_name": admin_display_name,
            }
            self.bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": "test_user"}]
            brevo_list_name_pattern = self.mock_config.PERMISSIONS_MATRIX[entity_key_for_test]["brevo"][
                "list_name_pattern"
            ]
            expected_brevo_list_name = brevo_list_name_pattern.format(base_name=base_name_for_test)
            self.bot.brevo_client.get_list_by_name.return_value = {
                "id": "brevo_empty_list_id",
                "name": expected_brevo_list_name,
            }
            self.bot.brevo_client.get_contacts_from_list.return_value = []
            await self._send_test_message(
                f"@{self.mock_config.BOT_NAME} {command_name} Sujet /// Corps",
                user_id="test_user",
                channel_id=channel_id,
            )
            self.bot.envoyer_message.assert_called_with(channel_id, unittest.mock.ANY)
            last_call_args = self.bot.envoyer_message.call_args[0]
            self.assertIn(
                f"La liste Brevo '{expected_brevo_list_name}' ne contient aucun contact",
                last_call_args[1],
            )
            self.bot.brevo_client.send_transactional_email.assert_not_called()

        asyncio.run(actual_test_logic())

    @patch("libraries.group_sync_services._map_mm_channel_to_entity_and_base_name")
    def test_handle_send_email_brevo_send_fails(self, mock_map_channel):
        async def actual_test_logic():
            command_name = "send_email"
            base_name_for_test = "SendFailProjet"
            entity_key_for_test = "PROJET"
            admin_display_name = self.mock_config.PERMISSIONS_MATRIX[entity_key_for_test]["admin"][
                "mattermost_channel_name_pattern"
            ].format(base_name=base_name_for_test)
            admin_slug = slugify(admin_display_name)

            def map_channel_side_effect(ch_slug_arg, ch_display_name_arg, entity_config_slice_arg):
                iter_entity_key = list(entity_config_slice_arg.keys())[0]
                if iter_entity_key == entity_key_for_test and ch_display_name_arg == admin_display_name:
                    return (entity_key_for_test, base_name_for_test, "admin")
                return (None, None, None)

            mock_map_channel.side_effect = map_channel_side_effect
            channel_id = "admin_send_fail"
            self.bot.mattermost_api_client.get_channel_by_id.return_value = {
                "id": channel_id,
                "name": admin_slug,
                "display_name": admin_display_name,
            }
            self.bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": "test_user"}]
            brevo_list_name_pattern = self.mock_config.PERMISSIONS_MATRIX[entity_key_for_test]["brevo"][
                "list_name_pattern"
            ]
            expected_brevo_list_name = brevo_list_name_pattern.format(base_name=base_name_for_test)
            self.bot.brevo_client.get_list_by_name.return_value = {
                "id": "brevo_sendfail_list_id",
                "name": expected_brevo_list_name,
            }
            self.bot.brevo_client.get_contacts_from_list.return_value = [{"email": "contact@example.com"}]
            self.bot.brevo_client.send_transactional_email.return_value = False
            await self._send_test_message(
                f"@{self.mock_config.BOT_NAME} {command_name} Sujet /// Corps",
                user_id="test_user",
                channel_id=channel_id,
            )
            self.bot.envoyer_message.assert_called_with(channel_id, unittest.mock.ANY)
            last_call_args = self.bot.envoyer_message.call_args[0]
            self.assertIn("Échec de l'envoi de l'email", last_call_args[1])
            self.bot.brevo_client.send_transactional_email.assert_called_once()

        asyncio.run(actual_test_logic())

    @patch("app.commands.send_email.SendEmailCommand.check_user_right", new_callable=unittest.mock.AsyncMock)
    def test_handle_send_email_bad_syntax(self, mock_check_user_right):
        async def actual_test_logic():
            mock_check_user_right.return_value = True
            command_name = "send_email"
            channel_id = "admin_channel_syntax"
            self.bot.mattermost_api_client.get_channel_by_id.return_value = {
                "id": channel_id,
                "name": "projet-syntax-admin",
                "display_name": "Projet Syntax Admin",
            }
            self.bot.mattermost_api_client.get_users_in_channel.return_value = [{"id": "test_user"}]
            with patch(
                "libraries.group_sync_services._map_mm_channel_to_entity_and_base_name",
                return_value=("PROJET", "SyntaxTest"),
            ):
                await self._send_test_message(
                    f"@{self.mock_config.BOT_NAME} {command_name} Just subject no body",
                    user_id="test_user",
                    channel_id=channel_id,
                )
                self.bot.envoyer_message.assert_called_with(channel_id, unittest.mock.ANY)
                last_call_args = self.bot.envoyer_message.call_args[0]
                self.assertIn("Syntaxe incorrecte.", last_call_args[1])
                self.bot.envoyer_message.reset_mock()
                await self._send_test_message(
                    f"@{self.mock_config.BOT_NAME} {command_name} Subject /// ",
                    user_id="test_user",
                    channel_id=channel_id,
                )
                self.bot.envoyer_message.assert_called_with(channel_id, unittest.mock.ANY)
                last_call_args = self.bot.envoyer_message.call_args[0]
                self.assertIn(
                    "Le sujet et le contenu ne peuvent pas être vides.",
                    last_call_args[1],
                )
                self.bot.envoyer_message.reset_mock()
                await self._send_test_message(
                    f"@{self.mock_config.BOT_NAME} {command_name}  /// Body",
                    user_id="test_user",
                    channel_id=channel_id,
                )
                self.bot.envoyer_message.assert_called_with(channel_id, unittest.mock.ANY)
                last_call_args = self.bot.envoyer_message.call_args[0]
                self.assertIn(
                    "Le sujet et le contenu ne peuvent pas être vides.",
                    last_call_args[1],
                )

        asyncio.run(actual_test_logic())
