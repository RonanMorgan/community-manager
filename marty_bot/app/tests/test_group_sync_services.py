import asyncio
import unittest
from unittest.mock import MagicMock, patch

from clients.authentik_client import AuthentikClient
from clients.brevo_client import BrevoClient
from clients.mattermost_client import MattermostClient
from clients.nocodb_client import NocoDBClient
from clients.outline_client import OutlineClient
from clients.vaultwarden_client import VaultwardenClient
from libraries.group_sync_services import orchestrate_group_synchronization
from libraries.services.mattermost import slugify


def async_test(f):
    def wrapper(*args, **kwargs):
        asyncio.run(f(*args, **kwargs))

    return wrapper


class TestGroupSyncServices(unittest.TestCase):
    def setUp(self):
        self.mock_authentik_client = MagicMock(spec=AuthentikClient)
        self.mock_mattermost_client = MagicMock(spec=MattermostClient)
        self.mock_outline_client = MagicMock(spec=OutlineClient)
        self.mock_brevo_client = MagicMock(spec=BrevoClient)
        self.mock_nocodb_client = MagicMock(spec=NocoDBClient)
        self.mock_vaultwarden_client = MagicMock(spec=VaultwardenClient)
        self.mm_team_id = "test_team_id"

    @patch("libraries.group_sync_services.config")
    @async_test
    async def test_orchestrate_group_synchronization_with_sync_mode_mm_to_tools(self, mock_lib_config):
        self.mock_authentik_client.reset_mock()
        self.mock_mattermost_client.reset_mock()
        self.mock_outline_client.reset_mock()

        mock_team_id = "team_upsert_mode"
        std_mm_channel_name = "projet-alpha"
        adm_mm_channel_name = "projet-alpha-admin"
        std_mm_channel_obj = {
            "id": "mm_alpha_id",
            "name": std_mm_channel_name,
            "display_name": "PROJET Alpha",
        }
        adm_mm_channel_obj = {
            "id": "mm_beta_adm_id",
            "name": adm_mm_channel_name,
            "display_name": "PROJET Alpha Admin",
        }
        self.mock_mattermost_client.get_channels_for_team.return_value = [
            std_mm_channel_obj,
            adm_mm_channel_obj,
        ]

        mock_lib_config.PERMISSIONS_MATRIX = {
            "PROJET": {
                "standard": {
                    "mattermost_channel_name_pattern": "PROJET {base_name}",
                    "authentik_group_name_pattern": "auth_projet_{base_name}",
                },
                "admin": {
                    "mattermost_channel_name_pattern": "PROJET {base_name} Admin",
                    "authentik_group_name_pattern": "auth_projet_{base_name}_admin",
                },
            }
        }

        clients = {
            "authentik": self.mock_authentik_client,
            "mattermost": self.mock_mattermost_client,
            "outline": self.mock_outline_client,
            "brevo": self.mock_brevo_client,
            "nocodb": self.mock_nocodb_client,
            "vaultwarden": self.mock_vaultwarden_client,
        }
        success, detailed_results = await orchestrate_group_synchronization(
            clients=clients,
            mm_team_id=mock_team_id,
            sync_mode="MM_TO_TOOLS",
        )

        self.assertTrue(success)
        self.assertEqual(len(detailed_results), 0)
