import asyncio
import json
import os
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

from app.bot import MartyBot
from libraries.services.mattermost import slugify


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
        self.mock_config.VAULTWARDEN_ORGANIZATION_ID = "fake_vw_org_id"
        self.mock_config.VAULTWARDEN_SERVER_URL = "http://fake-vw.com"
        self.mock_config.VAULTWARDEN_CLIENT_ID = "fake_vw_client_id"
        self.mock_config.VAULTWARDEN_CLIENT_SECRET = "fake_vw_client_secret"
        self.mock_config.PERMISSIONS_MATRIX = {
            "PROJET": {
                "standard": {"mattermost_channel_name_pattern": "projet_{base_name}", "mattermost_channel_type": "O", "authentik_group_name_pattern": "projet_{base_name}"},
                "admin": {"mattermost_channel_name_pattern": "projet_{base_name} Admin", "mattermost_channel_type": "P", "authentik_group_name_pattern": "projet_{base_name} Admin"},
                "outline": {"collection_name_pattern": "projet_{base_name}", "default_access": "read", "admin_access": "read_write"},
                "brevo": {"list_name_pattern": "brevo_projet_{base_name}", "folder_name": "Dossier Projets Test"},
                "vaultwarden": {"collection_name_pattern": "VW_Projet_{base_name}"},
            },
            "ANTENNE": {
                "standard": {"mattermost_channel_name_pattern": "antenne_{base_name}", "mattermost_channel_type": "O", "authentik_group_name_pattern": "antenne_{base_name}"},
                "admin": {"mattermost_channel_name_pattern": "antenne_{base_name} Admin", "mattermost_channel_type": "P", "authentik_group_name_pattern": "antenne_{base_name} Admin"},
                "outline": {"collection_name_pattern": "antenne_{base_name}", "default_access": "read", "admin_access": "read_write"},
                "brevo": {"list_name_pattern": "brevo_antenne_{base_name}"},
                "vaultwarden": {"collection_name_pattern": "VW_Antenne_{base_name}"},
            },
            "POLES": {
                "standard": {"mattermost_channel_name_pattern": "pole_{base_name}", "mattermost_channel_type": "P", "authentik_group_name_pattern": "pole_{base_name}"},
                "admin": {"mattermost_channel_name_pattern": "pole_{base_name} Admin", "mattermost_channel_type": "P", "authentik_group_name_pattern": "pole_{base_name} Admin"},
                "outline": {"collection_name_pattern": "pole_{base_name}", "default_access": "read", "admin_access": "read_write"},
                "brevo": {"list_name_pattern": "brevo_pole_{base_name}"},
                "vaultwarden": {"collection_name_pattern": "VW_Pole_{base_name}"},
            },
        }
        with patch('clients.client_factory.create_clients', return_value={}):
            self.bot = MartyBot(self.mock_config)
        self.bot.authentik_client = MagicMock()
        self.bot.outline_client = MagicMock()
        self.bot.mattermost_api_client = MagicMock()
        self.bot.brevo_client = MagicMock()
        self.bot.nocodb_client = MagicMock()
        self.bot.vaultwarden_client = MagicMock()
        self.bot.envoyer_message = MagicMock(return_value="mock_post_id")
        self.test_user_id = "test_user_who_posted"

    async def _send_test_message(self, message_text, channel_id="test_channel", user_id=None):
        self.bot.envoyer_message.reset_mock()
        client_attrs_to_reset = ["authentik_client", "outline_client", "mattermost_api_client", "brevo_client", "nocodb_client", "vaultwarden_client"]
        for client_attr in client_attrs_to_reset:
            client_mock = getattr(self.bot, client_attr, None)
            if client_mock:
                client_mock.reset_mock()
        post_content = {"message": message_text, "channel_id": channel_id, "user_id": user_id if user_id else self.test_user_id}
        mock_message_data = {"event": "posted", "data": {"post": json.dumps(post_content)}}
        await self.bot.websocket_handler.on_message(None, json.dumps(mock_message_data))

    @async_test
    @patch("app.user_right_manager.UserRightManager.is_admin", new_callable=AsyncMock)
    async def test_handle_update_all_user_rights_command_success(self, mock_is_admin):
        mock_is_admin.return_value = True
        command_name = "update_all_user_rights"
        admin_user_id = "admin_user_for_upsert"

        with patch("app.commands.update_all_user_rights.orchestrate_group_synchronization", new_callable=AsyncMock) as mock_orchestrate_sync:
            mock_orchestrate_sync.return_value = (True, [{"mm_username": "testuser", "service": "AUTHENTIK", "action": "USER_ADDED_TO_AUTHENTIK_GROUP", "status": "SUCCESS", "target_resource_name": "TestGroup"}])
            await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_name}", user_id=admin_user_id)

            mock_is_admin.assert_called_once_with(admin_user_id)
            mock_orchestrate_sync.assert_called_once()
            self.assertGreaterEqual(self.bot.envoyer_message.call_count, 2)

    @async_test
    @patch("app.user_right_manager.UserRightManager.is_admin", new_callable=AsyncMock)
    async def test_handle_update_user_rights_and_remove_command_success_admin_user(self, mock_is_admin):
        mock_is_admin.return_value = True
        command_name = "update_user_rights_and_remove"
        admin_user_id = "admin_user_id_for_sync"

        with patch("app.commands.update_user_rights_and_remove.differential_sync", new_callable=AsyncMock) as mock_differential_sync:
            mock_differential_sync.return_value = (True, [{"mm_username": "testuser", "service": "AUTHENTIK", "action": "USER_REMOVED_FROM_AUTHENTIK_GROUP", "status": "SUCCESS", "target_resource_name": "TestGroupRemove"}])
            await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_name}", user_id=admin_user_id)
            mock_is_admin.assert_called_once_with(admin_user_id)
            mock_differential_sync.assert_called_once()
            self.assertGreaterEqual(self.bot.envoyer_message.call_count, 2)

    @async_test
    @patch("app.user_right_manager.UserRightManager.is_admin", new_callable=AsyncMock)
    @patch("app.commands.update_all_user_rights.orchestrate_group_synchronization", new_callable=AsyncMock)
    @patch("app.commands.update_user_rights_and_remove.differential_sync", new_callable=AsyncMock)
    async def test_sync_commands_permission_denied_non_admin(self, mock_differential_sync, mock_sync_all_rights, mock_is_admin):
        mock_is_admin.return_value = False
        commands_to_test = ["update_all_user_rights", "update_user_rights_and_remove"]
        non_admin_user_id = "non_admin_user_for_sync"

        for command_key in commands_to_test:
            with self.subTest(command=command_key):
                self.bot.envoyer_message.reset_mock()
                mock_is_admin.reset_mock()
                await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_key}", user_id=non_admin_user_id)
                mock_is_admin.assert_called_once_with(non_admin_user_id)
                mock_differential_sync.assert_not_called()
                mock_sync_all_rights.assert_not_called()
                self.bot.envoyer_message.assert_called_once()
                sent_message = self.bot.envoyer_message.call_args[0][1]
                self.assertIn(":no_entry_sign: Accès refusé.", sent_message)

class TestSendEmailCommand(TestMartyBot):
    def setUp(self):
        super().setUp()
        self.mock_config.BREVO_DEFAULT_SENDER_EMAIL = "marty.sender@example.com"
        self.mock_config.BREVO_DEFAULT_SENDER_NAME = "Marty Test Bot"

    @async_test
    @patch("app.user_right_manager.UserRightManager.is_channel_admin", new_callable=AsyncMock)
    async def test_handle_send_email_success(self, mock_is_channel_admin):
        base_name_for_test = "Test-Projet"
        entity_key_for_test = "PROJET"
        mock_is_channel_admin.return_value = (True, entity_key_for_test, base_name_for_test)

        command_name = "send_email"
        channel_id = "admin_channel_projet_test"
        user_id = "test_user_admin"
        subject = "Test Email Subject"
        body = "This is the email body."
        arg_string = f"{subject} /// {body}"

        expected_brevo_list_name = self.mock_config.PERMISSIONS_MATRIX[entity_key_for_test]["brevo"]["list_name_pattern"].format(base_name=base_name_for_test)
        self.bot.brevo_client.get_list_by_name.return_value = {"id": "brevo_list_123", "name": expected_brevo_list_name}
        self.bot.brevo_client.get_contacts_from_list.return_value = [{"email": "contact1@example.com"}]
        self.bot.brevo_client.send_transactional_email.return_value = True

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_name} {arg_string}", user_id=user_id, channel_id=channel_id)

        mock_is_channel_admin.assert_called_once_with(user_id, channel_id)
        self.bot.brevo_client.send_transactional_email.assert_called_once()
        self.bot.envoyer_message.assert_called_with(channel_id, unittest.mock.ANY)
        last_call_args = self.bot.envoyer_message.call_args[0]
        self.assertIn("Email avec sujet 'Test Email Subject' envoyé", last_call_args[1])

    @async_test
    @patch("app.user_right_manager.UserRightManager.is_channel_admin", new_callable=AsyncMock)
    async def test_handle_send_email_not_admin_channel(self, mock_is_channel_admin):
        mock_is_channel_admin.return_value = (False, None, None)
        command_name = "send_email"
        await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_name} Subject /// Body", user_id="test_user", channel_id="not_an_admin_channel")
        self.bot.envoyer_message.assert_called_once()
        self.bot.brevo_client.send_transactional_email.assert_not_called()

    @async_test
    @patch("app.user_right_manager.UserRightManager.is_channel_admin", new_callable=AsyncMock)
    async def test_handle_send_email_bad_syntax(self, mock_is_channel_admin):
        mock_is_channel_admin.return_value = (True, "PROJET", "SyntaxTest")
        command_name = "send_email"
        channel_id = "admin_channel_syntax"

        await self._send_test_message(f"@{self.mock_config.BOT_NAME} {command_name} Just subject no body", user_id="test_user", channel_id=channel_id)
        self.bot.envoyer_message.assert_called_with(channel_id, unittest.mock.ANY)
        last_call_args = self.bot.envoyer_message.call_args[0]
        self.assertIn("Syntaxe incorrecte.", last_call_args[1])
