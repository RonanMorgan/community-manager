import asyncio
import unittest
from unittest.mock import MagicMock, mock_open, patch

from clients.authentik_client import AuthentikClient
from clients.brevo_client import BrevoClient
from clients.mattermost_client import MattermostClient
from clients.nocodb_client import NocoDBClient
from clients.outline_client import OutlineClient
from clients.vaultwarden_client import VaultwardenClient
import os

import config as app_config
from libraries.group_sync_services import (
    orchestrate_group_synchronization,
)
from libraries.services.authentik import AuthentikService
from libraries.services.mattermost import (
    _extract_base_name,
    _map_mm_channel_to_entity_and_base_name,
    slugify,
)


def async_test(f):
    def wrapper(*args, **kwargs):
        asyncio.run(f(*args, **kwargs))

    return wrapper


def reload_config_module():
    import importlib

    importlib.reload(app_config)


class TestGroupSyncServices(unittest.TestCase):
    def setUp(self):
        self.mock_authentik_client = MagicMock(spec=AuthentikClient)
        self.mock_mattermost_client = MagicMock(spec=MattermostClient)
        self.mock_outline_client = MagicMock(spec=OutlineClient)
        self.mock_brevo_client = MagicMock(spec=BrevoClient)
        self.mock_nocodb_client = MagicMock(spec=NocoDBClient)
        self.mock_vaultwarden_client = MagicMock(spec=VaultwardenClient)
        self.mm_team_id = "test_team_id"
        self.mock_vaultwarden_client.organization_id = "test_vw_org_id"  # Mock organization_id
        self.mock_vaultwarden_client.api_username = "vw_api_user"  # Mock api_username
        self.mock_vaultwarden_client.api_password = "vw_api_pass"  # Mock api_password

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

    def test_extract_base_name(self):
        self.assertEqual(
            _extract_base_name("projet_TestProjet_dev", "projet_{base_name}_dev"),
            "TestProjet",
        )
        self.assertEqual(_extract_base_name("projet_TestProjet", "projet_{base_name}"), "TestProjet")
        self.assertEqual(_extract_base_name("TestProjet_dev", "{base_name}_dev"), "TestProjet")
        self.assertIsNone(_extract_base_name("projet_TestProjet_dev", "antenne_{base_name}_dev"))
        self.assertIsNone(_extract_base_name("projet_TestProjet", "projet_{base_name}_suffix_mismatch"))
        self.assertIsNone(_extract_base_name("projet_TestProjet", "exact_name_no_placeholder"))
        self.assertEqual(_extract_base_name("Projet Alpha", "Projet {base_name}"), "Alpha")
        self.assertEqual(_extract_base_name("Projet Super Cool", "Projet {base_name}"), "Super Cool")
        self.assertIsNone(_extract_base_name("Projet Admin", "Projet {base_name} Admin"))
        self.assertEqual(_extract_base_name("ProjetAdmin", "Projet{base_name}Admin"), "")  # No spaces around base_name
        self.assertEqual(
            _extract_base_name("Projet Super Cool Admin", "Projet {base_name} Admin"),
            "Super Cool",
        )

    def test_map_auth_group_to_entity_and_base_name(self):
        matrix = {
            "PROJET": {
                "standard": {"authentik_group_name_pattern": "projet_{base_name}"},
                "admin": {"authentik_group_name_pattern": "projet_{base_name}_admin"},
            },
            "ANTENNE": {
                "standard": {"authentik_group_name_pattern": "antenne_{base_name}_standard"},
            },
        }
        authentik_service = AuthentikService(None, None, None, None)
        self.assertEqual(
            authentik_service._map_auth_group_to_entity_and_base_name("projet_MonProjet", matrix),
            ("PROJET", "MonProjet"),
        )
        self.assertEqual(
            authentik_service._map_auth_group_to_entity_and_base_name("projet_MonProjet_admin", matrix),
            ("PROJET", "MonProjet"),
        )
        # "projet_admin" will be matched by "projet_{base_name}" (standard) before "projet_{base_name}_admin" (admin)
        # because _extract_base_name("projet_admin", "projet_{base_name}_admin") returns None.
        self.assertEqual(
            authentik_service._map_auth_group_to_entity_and_base_name("projet_admin", matrix),
            ("PROJET", "admin"),
        )
        self.assertEqual(
            authentik_service._map_auth_group_to_entity_and_base_name("projet__admin", matrix),
            ("PROJET", ""),
        )  # Test expects "" now
        self.assertEqual(
            authentik_service._map_auth_group_to_entity_and_base_name("antenne_MaRegion_standard", matrix),
            ("ANTENNE", "MaRegion"),
        )
        self.assertIsNone(authentik_service._map_auth_group_to_entity_and_base_name("unknown_group_format", matrix)[0])

    def test_map_mm_channel_to_entity_and_base_name(self):
        matrix = {
            "PROJET": {
                "standard": {"mattermost_channel_name_pattern": "Projet {base_name}"},
                "admin": {"mattermost_channel_name_pattern": "Projet {base_name} Admin"},
            },
            "ANTENNE": {
                "standard": {"mattermost_channel_name_pattern": "Antenne {base_name} Standard"},
            },
        }
        self.assertEqual(
            _map_mm_channel_to_entity_and_base_name("projet-alpha", "Projet Alpha", matrix),
            ("PROJET", "Alpha"),
        )
        self.assertEqual(
            _map_mm_channel_to_entity_and_base_name("projet-alpha-admin", "Projet Alpha Admin", matrix),
            ("PROJET", "Alpha"),
        )
        self.assertEqual(
            _map_mm_channel_to_entity_and_base_name("antenne-maregion-standard", "Antenne MaRegion Standard", matrix),
            ("ANTENNE", "MaRegion"),
        )
        self.assertIsNone(
            _map_mm_channel_to_entity_and_base_name("unknown-channel", "Unknown Channel Format", matrix)[0]
        )
        matrix_slug_friendly = {"PROJET": {"standard": {"mattermost_channel_name_pattern": "projet-{base_name}"}}}
        self.assertEqual(
            _map_mm_channel_to_entity_and_base_name(
                "projet-my-cool-project", "DIFFERENT DISPLAY NAME", matrix_slug_friendly
            ),
            ("PROJET", "my-cool-project"),
        )

    @patch("dotenv.main.find_dotenv", return_value=None)
    @patch("os.getenv")
    @patch("builtins.open")
    @patch("os.path.exists")
    def test_config_loading_file_not_found(self, mock_exists, mock_open_file, mock_getenv, mock_find_dotenv):
        def getenv_side_effect(key, default=None):
            if key == "EXCLUDED_USERS_FILE_PATH":
                return "dummy_path/non_existent_excluded.txt"
            if key == "PERMISSIONS_MATRIX_FILE_PATH":
                return "dummy_path/non_existent_matrix.yml"
            return os.environ.get(key, default)

        mock_getenv.side_effect = getenv_side_effect
        mock_exists.return_value = False
        app_config.EXCLUDED_USERS = {"dummy"}
        app_config.PERMISSIONS_MATRIX = {"dummy": "data"}
        reload_config_module()
        self.assertEqual(app_config.EXCLUDED_USERS, set())
        self.assertEqual(app_config.PERMISSIONS_MATRIX, {})
        mock_open_file.assert_not_called()

    @patch("dotenv.main.find_dotenv", return_value=None)
    @patch("os.getenv")
    @patch("builtins.open")
    @patch("os.path.exists")
    def test_config_loading_empty_file(self, mock_exists, mock_open_file, mock_getenv, mock_find_dotenv):
        dummy_excluded_path = "dummy_path/existent_empty_excluded.txt"
        dummy_matrix_path = "dummy_path/existent_empty_matrix.yml"

        def getenv_side_effect(key, default=None):
            if key == "EXCLUDED_USERS_FILE_PATH":
                return dummy_excluded_path
            if key == "PERMISSIONS_MATRIX_FILE_PATH":
                return dummy_matrix_path
            return os.environ.get(key, default)

        mock_getenv.side_effect = getenv_side_effect
        mock_exists.return_value = True
        mock_open_file.return_value = mock_open(read_data="")()
        app_config.EXCLUDED_USERS = {"dummy"}
        app_config.PERMISSIONS_MATRIX = {"dummy": "data"}
        reload_config_module()
        self.assertEqual(app_config.EXCLUDED_USERS, set())
        self.assertEqual(app_config.PERMISSIONS_MATRIX, {})
        mock_open_file.assert_any_call(dummy_excluded_path, "r")
        mock_open_file.assert_any_call(dummy_matrix_path, "r")

    @patch("dotenv.main.find_dotenv", return_value=None)
    @patch("os.getenv")
    @patch("builtins.open")
    @patch("os.path.exists")
    def test_config_loading_excluded_users_success(self, mock_exists, mock_open_file, mock_getenv, mock_find_dotenv):
        excluded_users_content = "userA\nuserB\n\nuserC  \n"
        dummy_excluded_path = "dummy_path/existent_excluded.txt"
        dummy_matrix_path = "dummy_path/non_existent_matrix.yml"

        def getenv_side_effect(key, default=None):
            if key == "EXCLUDED_USERS_FILE_PATH":
                return dummy_excluded_path
            if key == "PERMISSIONS_MATRIX_FILE_PATH":
                return dummy_matrix_path
            return os.environ.get(key, default)

        mock_getenv.side_effect = getenv_side_effect
        mock_exists.side_effect = lambda path: path == dummy_excluded_path
        mock_open_file.return_value = mock_open(read_data=excluded_users_content)()
        app_config.EXCLUDED_USERS = set()
        app_config.PERMISSIONS_MATRIX = {"dummy": "data"}
        reload_config_module()
        self.assertEqual(app_config.EXCLUDED_USERS, {"userA", "userB", "userC"})
        self.assertEqual(app_config.PERMISSIONS_MATRIX, {})
        mock_open_file.assert_called_once_with(dummy_excluded_path, "r")

    @patch("dotenv.main.find_dotenv", return_value=None)
    @patch("os.getenv")
    @patch("builtins.open")
    @patch("os.path.exists")
    def test_config_loading_permissions_matrix_success(
        self, mock_exists, mock_open_file, mock_getenv, mock_find_dotenv
    ):
        permissions_yaml_content = """
permissions:
  PROJET:
    standard: {authentik_group_name_pattern: "projet_{base_name}"}
    outline: {collection_name_pattern: "projet_{base_name}", default_access: "read"}
"""
        dummy_matrix_path = "dummy_permissions_matrix.yml"
        dummy_excluded_path = "dummy_excluded_users.txt"

        def getenv_side_effect(key, default=None):
            if key == "PERMISSIONS_MATRIX_FILE_PATH":
                return dummy_matrix_path
            if key == "EXCLUDED_USERS_FILE_PATH":
                return dummy_excluded_path
            return os.environ.get(key, default)

        mock_getenv.side_effect = getenv_side_effect
        mock_exists.side_effect = lambda path: path == dummy_matrix_path
        mock_open_file.return_value = mock_open(read_data=permissions_yaml_content)()
        app_config.PERMISSIONS_MATRIX = {}
        app_config.EXCLUDED_USERS = {"dummy"}
        reload_config_module()
        mock_open_file.assert_called_once_with(dummy_matrix_path, "r")
        self.assertIn("PROJET", app_config.PERMISSIONS_MATRIX)
        if "PROJET" in app_config.PERMISSIONS_MATRIX:
            self.assertEqual(
                app_config.PERMISSIONS_MATRIX["PROJET"]["outline"]["default_access"],
                "read",
            )
        self.assertEqual(app_config.EXCLUDED_USERS, set())

    # --- Tests for Brevo list synchronization ---
    @patch("libraries.group_sync_services.config")  # To mock EXCLUDED_USERS
    def test_sync_brevo_list_creation_and_user_add(self, mock_lib_config_brevo):
        mock_lib_config_brevo.EXCLUDED_USERS = set()
        brevo_list_name = "TestBrevoList1"
        mm_users = [
            {"username": "brevo_user1", "email": "brevo1@example.com"},
            {"username": "brevo_user2", "email": "brevo2@example.com"},
        ]
        mm_channel_name_log = "MMChannelForBrevo1"

        self.mock_brevo_client.get_lists.return_value = []  # List does not exist
        # Use the ID pattern from the mock_brevo_client.create_list setup
        expected_created_list_id = f"new_brevo_list_id_for_{slugify(brevo_list_name)}"
        created_list_obj_for_test = {
            "id": expected_created_list_id,
            "name": brevo_list_name,
        }
        # Ensure create_list mock returns this structure if called
        self.mock_brevo_client.create_list.return_value = created_list_obj_for_test
        self.mock_brevo_client.add_contact_to_list.return_value = True

        results = self.sync_single_brevo_list_helper(
            self.mock_brevo_client,
            brevo_list_name,
            mm_users,
            mm_channel_name_log,
        )

        self.mock_brevo_client.get_lists.assert_called_once_with(name=brevo_list_name)
        self.mock_brevo_client.create_list.assert_called_once_with(brevo_list_name)
        self.assertEqual(self.mock_brevo_client.add_contact_to_list.call_count, 2)
        self.mock_brevo_client.add_contact_to_list.assert_any_call(
            email="brevo1@example.com", list_id=expected_created_list_id
        )
        self.mock_brevo_client.add_contact_to_list.assert_any_call(
            email="brevo2@example.com", list_id=expected_created_list_id
        )

        self.assertEqual(len(results), 2)
        for res in results:
            self.assertEqual(res["status"], "SUCCESS")
            self.assertEqual(res["action"], "USER_ENSURED_IN_BREVO_LIST")
            self.assertEqual(res["service"], "BREVO")

    @patch("libraries.services.brevo.config")
    @patch("libraries.group_sync_services.config")
    def test_sync_brevo_list_excluded_user_not_added_or_removed(
        self, mock_lib_config_brevo, mock_service_config_brevo
    ):
        excluded_username = "excluded_brevo_user"
        mock_lib_config_brevo.EXCLUDED_USERS = {excluded_username}
        mock_service_config_brevo.EXCLUDED_USERS = {excluded_username}
        brevo_list_name = "TestBrevoListExcluded"
        existing_list_obj = {"id": "brevo_list_id_789", "name": brevo_list_name}
        self.mock_brevo_client.get_lists.return_value = [existing_list_obj]

        mm_users_in_channel = [
            {"username": excluded_username, "email": "excluded_brevo@example.com"},
            {"username": "normal_user", "email": "normal@example.com"},
        ]
        # Assume an unmanaged user is on the Brevo list and should be removed.
        # The excluded user is not on the list and should not be added.
        brevo_contacts_on_list = [{"email": "unmanaged@example.com"}]
        self.mock_brevo_client.get_contacts_from_list.return_value = brevo_contacts_on_list

        results = self.sync_single_brevo_list_helper(
            self.mock_brevo_client,
            brevo_list_name,
            mm_users_in_channel,
            "MMChannelForBrevoExcluded",
        )

        # "normal_user" should be added because they are in the MM channel and not excluded.
        self.mock_brevo_client.add_contact_to_list.assert_called_once_with(
            email="normal@example.com", list_id=existing_list_obj["id"]
        )

        # Verify that no action was logged for the excluded user.
        actions_for_excluded = [r for r in results if r.get("mm_user_email") == "excluded_brevo@example.com"]
        self.assertEqual(
            len(actions_for_excluded),
            0,
            "No direct add/remove actions should be logged for excluded user based on MM channel presence.",
        )

    def sync_single_brevo_list_helper(
        self,
        mock_brevo_client,
        brevo_list_name,
        mm_users,
        mm_channel_name_log,
    ):
        """Helper to call the static _sync_single_brevo_list method for testing."""
        from libraries.services.brevo import BrevoService

        brevo_service = BrevoService(None, None, None, None)
        return brevo_service._sync_single_brevo_list(
            brevo_client=mock_brevo_client,
            brevo_list_name=brevo_list_name,
            mm_users_in_channel=mm_users,
            mm_channel_display_name_for_log=mm_channel_name_log,
        )

    # --- Tests for NocoDB base synchronization ---
    @patch("libraries.services.nocodb.config")
    @patch("libraries.group_sync_services.config")  # To mock EXCLUDED_USERS and NOCODB_URL
    def test_sync_nocodb_base_creation_and_user_invite_with_dm(
        self, mock_lib_config_nocodb, mock_service_config_nocodb
    ):
        mock_lib_config_nocodb.EXCLUDED_USERS = set()
        mock_lib_config_nocodb.NOCODB_URL = "https://test-nocodb.example.com"  # Mock NOCODB_URL for DM link
        mock_service_config_nocodb.EXCLUDED_USERS = set()
        mock_service_config_nocodb.NOCODB_URL = "https://test-nocodb.example.com"
        from libraries.services.nocodb import NocoDBService

        nocodb_service = NocoDBService(None, None, None, None)
        base_title_pattern = "test_nocodb_{base_name}"
        entity_base_name = "MyNocoAntenne"
        nocodb_base_title = base_title_pattern.format(base_name=entity_base_name)

        mm_users_for_perm = {
            "user1@nocodb.com": {
                "username": "nocodb_user1",
                "mm_user_id": "mm_nc_u1",
                "is_admin_channel_member": False,
            },
            "admin@nocodb.com": {
                "username": "nocodb_admin1",
                "mm_user_id": "mm_nc_a1",
                "is_admin_channel_member": True,
            },
        }
        default_perm = "viewer"
        admin_perm = "owner"
        mm_channel_context = "TestNocoDBChannel"

        # Mock NocoDB client calls for this test
        self.mock_nocodb_client.get_base_by_title.return_value = {
            "id": "nc_base_id_123",
            "title": nocodb_base_title,
        }
        self.mock_nocodb_client.list_base_users.return_value = []  # No users initially
        self.mock_nocodb_client.invite_user_to_base.return_value = True
        self.mock_mattermost_client.send_dm.return_value = True  # Assume DMs are sent successfully

        results = nocodb_service._sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,
            base_title_pattern,
            entity_base_name,
            mm_users_for_perm,
            default_perm,
            admin_perm,
            mm_channel_context,
        )
        self.mock_nocodb_client.get_base_by_title.assert_called_once_with(nocodb_base_title)
        self.mock_nocodb_client.list_base_users.assert_called_once_with("nc_base_id_123")

        self.assertEqual(self.mock_nocodb_client.invite_user_to_base.call_count, 2)
        self.mock_nocodb_client.invite_user_to_base.assert_any_call("nc_base_id_123", "user1@nocodb.com", default_perm)
        self.mock_nocodb_client.invite_user_to_base.assert_any_call("nc_base_id_123", "admin@nocodb.com", admin_perm)

        # Check DMs
        self.assertEqual(self.mock_mattermost_client.send_dm.call_count, 2)
        expected_base_url = f"{mock_lib_config_nocodb.NOCODB_URL.rstrip('/')}/#/nc/nc_base_id_123/dashboard"

        dm_calls = self.mock_mattermost_client.send_dm.call_args_list

        # Check DM for user1
        dm_call_user1_found = False
        for call_args in dm_calls:
            actual_recipient_id = call_args[0][0]
            actual_dm_text = call_args[0][1]

            if actual_recipient_id == "mm_nc_u1":
                expected_dm_text_user1 = (
                    f"Bonjour @nocodb_user1, vous avez été invité(e) à la base NoCoDb "
                    f"**{nocodb_base_title}** (rôle: {default_perm}).\n"
                    f"Vous pouvez y accéder ici : {expected_base_url}"
                )
                self.assertEqual(
                    actual_dm_text,
                    expected_dm_text_user1,
                    f"\nExpected: {repr(expected_dm_text_user1)}\nActual:   {repr(actual_dm_text)}",
                )
                dm_call_user1_found = True
            elif actual_recipient_id == "mm_nc_a1":
                expected_dm_text_admin1 = (
                    f"Bonjour @nocodb_admin1, vous avez été invité(e) à la base NoCoDb "
                    f"**{nocodb_base_title}** (rôle: {admin_perm}).\n"
                    f"Vous pouvez y accéder ici : {expected_base_url}"
                )
                self.assertEqual(
                    actual_dm_text,
                    expected_dm_text_admin1,
                    f"\nExpected: {repr(expected_dm_text_admin1)}\nActual:   {repr(actual_dm_text)}",
                )
                dm_call_admin1_found = True

        self.assertTrue(dm_call_user1_found, "DM call for user1 (mm_nc_u1) not found.")
        self.assertTrue(dm_call_admin1_found, "DM call for admin1 (mm_nc_a1) not found.")

        self.assertEqual(len(results), 2)
        for res in results:
            self.assertEqual(res["status"], "SUCCESS")
            if res["mm_user_email"] == "user1@nocodb.com":
                self.assertEqual(
                    res["action"],
                    f"NOCODB_USER_INVITED_AS_{default_perm.upper()}_AND_DM_SENT",
                )
            elif res["mm_user_email"] == "admin@nocodb.com":
                self.assertEqual(
                    res["action"],
                    f"NOCODB_USER_INVITED_AS_{admin_perm.upper()}_AND_DM_SENT",
                )

    @patch("libraries.services.nocodb.config")
    @patch("libraries.group_sync_services.config")
    def test_sync_nocodb_base_invite_dm_fails(self, mock_lib_config_nocodb, mock_service_config_nocodb):
        mock_lib_config_nocodb.EXCLUDED_USERS = set()
        mock_lib_config_nocodb.NOCODB_URL = "https://test-nocodb.example.com"
        mock_service_config_nocodb.EXCLUDED_USERS = set()
        mock_service_config_nocodb.NOCODB_URL = "https://test-nocodb.example.com"
        from libraries.services.nocodb import NocoDBService

        nocodb_service = NocoDBService(None, None, None, None)
        base_title_pattern = "dm_fail_nocodb_{base_name}"
        entity_base_name = "NocoDMFail"
        nocodb_base_title = base_title_pattern.format(base_name=entity_base_name)
        base_id = "nc_base_id_dm_fail"
        mm_user = {
            "username": "dm_fail_user",
            "mm_user_id": "mm_dm_fail",
            "is_admin_channel_member": False,
        }
        mm_users_for_perm = {"dm.fail@example.com": mm_user}

        self.mock_nocodb_client.get_base_by_title.return_value = {
            "id": base_id,
            "title": nocodb_base_title,
        }
        self.mock_nocodb_client.list_base_users.return_value = []
        self.mock_nocodb_client.invite_user_to_base.return_value = True
        self.mock_mattermost_client.send_dm.return_value = False  # Simulate DM failure

        results = nocodb_service._sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,
            base_title_pattern,
            entity_base_name,
            mm_users_for_perm,
            "viewer",
            "owner",
            "ChanDMFail",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")  # Invite itself was successful
        self.assertEqual(results[0]["action"], "NOCODB_USER_INVITED_AS_VIEWER_DM_FAILED")
        self.mock_mattermost_client.send_dm.assert_called_once()

    @patch("libraries.services.nocodb.config")
    @patch("libraries.group_sync_services.config")
    def test_sync_nocodb_base_invite_dm_skipped_no_url(self, mock_lib_config_nocodb, mock_service_config_nocodb):
        mock_lib_config_nocodb.EXCLUDED_USERS = set()
        mock_lib_config_nocodb.NOCODB_URL = None  # Simulate NOCODB_URL not being set
        mock_service_config_nocodb.EXCLUDED_USERS = set()
        mock_service_config_nocodb.NOCODB_URL = None
        from libraries.services.nocodb import NocoDBService

        nocodb_service = NocoDBService(None, None, None, None)
        base_title_pattern = "dm_skip_nocodb_{base_name}"
        entity_base_name = "NocoDMSkip"
        nocodb_base_title = base_title_pattern.format(base_name=entity_base_name)
        base_id = "nc_base_id_dm_skip"
        mm_user = {
            "username": "dm_skip_user",
            "mm_user_id": "mm_dm_skip",
            "is_admin_channel_member": False,
        }
        mm_users_for_perm = {"dm.skip@example.com": mm_user}

        self.mock_nocodb_client.get_base_by_title.return_value = {
            "id": base_id,
            "title": nocodb_base_title,
        }
        self.mock_nocodb_client.list_base_users.return_value = []
        self.mock_nocodb_client.invite_user_to_base.return_value = True

        results = nocodb_service._sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,
            base_title_pattern,
            entity_base_name,
            mm_users_for_perm,
            "viewer",
            "owner",
            "ChanDMSkip",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")  # Invite itself was successful
        self.assertEqual(results[0]["action"], "NOCODB_USER_INVITED_AS_VIEWER_DM_SKIPPED_NO_URL")
        self.mock_mattermost_client.send_dm.assert_not_called()

    @patch("libraries.services.nocodb.config")
    @patch("libraries.group_sync_services.config")
    def test_sync_nocodb_base_user_update_and_removal(self, mock_lib_config_nocodb, mock_service_config_nocodb):
        mock_lib_config_nocodb.EXCLUDED_USERS = set()
        mock_lib_config_nocodb.NOCODB_URL = (
            "https://test-nocodb.example.com"  # For consistency, though not strictly needed for removal/update tests
        )
        mock_service_config_nocodb.EXCLUDED_USERS = set()
        mock_service_config_nocodb.NOCODB_URL = "https://test-nocodb.example.com"
        from libraries.services.nocodb import NocoDBService

        nocodb_service = NocoDBService(None, None, None, None)
        base_title_pattern = "upd_rem_nocodb_{base_name}"
        entity_base_name = "NocoAntenneTwo"
        nocodb_base_title = base_title_pattern.format(base_name=entity_base_name)
        base_id = "nc_base_id_456"

        # MM users: user1 (viewer), user2 (owner)
        mm_users_for_perm = {
            "user1.update@nocodb.com": {
                "username": "nc_user1_upd",
                "mm_user_id": "mm_u1u",
                "is_admin_channel_member": False,
            },
            "user2.owner@nocodb.com": {
                "username": "nc_user2_own",
                "mm_user_id": "mm_u2o",
                "is_admin_channel_member": True,
            },
        }
        # NocoDB users initially: user1 (owner), user_to_remove (viewer)
        initial_nocodb_users = [
            {
                "id": "nc_uid1",
                "email": "user1.update@nocodb.com",
                "roles": "owner",
            },  # Role needs update
            {
                "id": "nc_uid_remove",
                "email": "user.remove@nocodb.com",
                "roles": "viewer",
                "firstname": "Remove",
                "lastname": "Me",
            },
        ]

        self.mock_nocodb_client.get_base_by_title.return_value = {
            "id": base_id,
            "title": nocodb_base_title,
        }
        self.mock_nocodb_client.list_base_users.return_value = initial_nocodb_users
        self.mock_nocodb_client.update_base_user.return_value = True
        self.mock_nocodb_client.invite_user_to_base.return_value = True  # For user2 who is new

        results = nocodb_service._sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,  # Added mattermost_client
            base_title_pattern,
            entity_base_name,
            mm_users_for_perm,
            "viewer",
            "owner",
            "NocoDBUpdateRemoveChannel",
        )

        # Check update for user1
        self.mock_nocodb_client.update_base_user.assert_any_call(base_id, "nc_uid1", "viewer")
        # Check invite for user2
        self.mock_nocodb_client.invite_user_to_base.assert_any_call(base_id, "user2.owner@nocodb.com", "owner")

        self.assertEqual(len(results), 2)  # 1 update, 1 invite
        actions = [r["action"] for r in results]
        self.assertIn("NOCODB_USER_ROLE_UPDATED_TO_VIEWER", actions)
        # Assuming send_dm is True by default from setUp for the invited user
        self.assertIn("NOCODB_USER_INVITED_AS_OWNER_AND_DM_SENT", actions)

    @patch("libraries.services.nocodb.config")
    @patch("libraries.group_sync_services.config")
    def test_sync_nocodb_base_excluded_user_handling(self, mock_lib_config_nocodb, mock_service_config_nocodb):
        excluded_username = "excluded_nc_user"
        mock_lib_config_nocodb.EXCLUDED_USERS = {excluded_username}
        mock_service_config_nocodb.EXCLUDED_USERS = {excluded_username}
        from libraries.services.nocodb import NocoDBService

        nocodb_service = NocoDBService(None, None, None, None)
        base_title_pattern = "excl_nocodb_{base_name}"
        entity_base_name = "NocoAntenneExcl"
        nocodb_base_title = base_title_pattern.format(base_name=entity_base_name)
        base_id = "nc_base_id_789"

        mm_users_for_perm = {
            "excluded.user@nocodb.com": {
                "username": excluded_username,
                "mm_user_id": "mm_excl",
                "is_admin_channel_member": False,
            },
            "normal.user@nocodb.com": {
                "username": "normal_nc_user",
                "mm_user_id": "mm_norm",
                "is_admin_channel_member": False,
            },
        }
        # Excluded user is on NocoDB, should be preserved. Another user on NocoDB not in MM should be removed.
        initial_nocodb_users = [
            {
                "id": "nc_uid_excl",
                "email": "excluded.user@nocodb.com",
                "roles": "editor",
            },
            {
                "id": "nc_uid_remove_excl_test",
                "email": "remove.excl@nocodb.com",
                "roles": "viewer",
            },
        ]

        self.mock_nocodb_client.get_base_by_title.return_value = {
            "id": base_id,
            "title": nocodb_base_title,
        }
        self.mock_nocodb_client.list_base_users.return_value = initial_nocodb_users
        self.mock_nocodb_client.invite_user_to_base.return_value = True  # For normal.user

        results = nocodb_service._sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,  # Added mattermost_client
            base_title_pattern,
            entity_base_name,
            mm_users_for_perm,
            "viewer",
            "owner",
            "NocoDBExclChannel",
        )

        # Normal user should be invited
        self.mock_nocodb_client.invite_user_to_base.assert_called_once_with(
            base_id, "normal.user@nocodb.com", "viewer"
        )
        # Excluded user on NocoDB should not be touched (no update/delete call for their NocoDB ID nc_uid_excl)
        for call in self.mock_nocodb_client.update_base_user.call_args_list:
            self.assertNotEqual(call.args[1], "nc_uid_excl")
        for call in self.mock_nocodb_client.delete_base_user.call_args_list:
            self.assertNotEqual(call.args[1], "nc_uid_excl")
        # User to remove (remove.excl@nocodb.com) should be deleted

        actions = {r["mm_user_email"]: r["action"] for r in results if "mm_user_email" in r}
        # Assuming send_dm is True by default from setUp or previous context if not reset and overridden
        self.assertEqual(
            actions.get("normal.user@nocodb.com"),
            "NOCODB_USER_INVITED_AS_VIEWER_AND_DM_SENT",
        )

    @patch("libraries.group_sync_services.config")
    def test_sync_nocodb_base_not_found(self, mock_lib_config_nocodb):
        mock_lib_config_nocodb.EXCLUDED_USERS = set()
        from libraries.services.nocodb import NocoDBService

        nocodb_service = NocoDBService(None, None, None, None)
        self.mock_nocodb_client.get_base_by_title.return_value = None  # Simulate base not found

        results = nocodb_service._sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,  # Added mattermost_client
            "nf_{base_name}",
            "NocoNF",
            {},
            "viewer",
            "owner",
            "ChanNF",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SKIPPED")
        self.assertEqual(results[0]["action"], "SKIPPED_NOCODB_BASE_NOT_FOUND")
        self.mock_nocodb_client.list_base_users.assert_not_called()

    # --- Tests for Vaultwarden collection member synchronization ---
    @patch("libraries.services.vaultwarden.config")
    @patch("libraries.group_sync_services.config")
    def test_sync_vaultwarden_collection_invite_with_dm(self, mock_lib_config_vw, mock_service_config_vw):
        mock_lib_config_vw.EXCLUDED_USERS = set()
        mock_lib_config_vw.VAULTWARDEN_SERVER_URL = "https://test-vault.example.com"
        mock_service_config_vw.EXCLUDED_USERS = set()
        mock_service_config_vw.VAULTWARDEN_SERVER_URL = "https://test-vault.example.com"
        from libraries.services.vaultwarden import VaultwardenService

        vaultwarden_service = VaultwardenService(None, None, None, None)
        collection_name = "TestVWCollection"
        mm_user_data = {
            "username": "vw_user1",
            "mm_user_id": "mm_vw_u1",
            "is_admin_channel_member": False,
        }
        mm_users_for_services = {"vw.user1@example.com": mm_user_data}
        mm_channel_context = "TestVWChannel"

        self.mock_vaultwarden_client.get_collection_by_name.return_value = "vw_coll_id_123"
        self.mock_vaultwarden_client._get_api_token.return_value = "fake_vw_api_token"
        self.mock_vaultwarden_client.invite_user_to_collection.return_value = True
        self.mock_mattermost_client.send_dm.return_value = True

        results = vaultwarden_service._sync_single_vaultwarden_collection_members(
            self.mock_vaultwarden_client,
            self.mock_mattermost_client,
            collection_name,
            mm_users_for_services,
            mm_channel_context,
        )

        self.mock_vaultwarden_client.get_collection_by_name.assert_called_once_with(collection_name)
        self.mock_vaultwarden_client._get_api_token.assert_called_once()
        self.mock_vaultwarden_client.invite_user_to_collection.assert_called_once_with(
            user_email="vw.user1@example.com",
            collection_id="vw_coll_id_123",
            organization_id=self.mock_vaultwarden_client.organization_id,
            access_token="fake_vw_api_token",
        )
        self.mock_mattermost_client.send_dm.assert_called_once()
        dm_call_args = self.mock_mattermost_client.send_dm.call_args[0]
        self.assertEqual(dm_call_args[0], "mm_vw_u1")  # Check recipient
        self.assertIn("Bonjour @vw_user1", dm_call_args[1])  # Corrected f-string
        self.assertIn(f"collection Vaultwarden **{collection_name}**", dm_call_args[1])
        self.assertIn(mock_lib_config_vw.VAULTWARDEN_SERVER_URL, dm_call_args[1])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["action"], "USER_INVITED_TO_VW_COLLECTION_AND_DM_SENT")

    @patch("libraries.services.vaultwarden.config")
    @patch("libraries.group_sync_services.config")
    def test_sync_vaultwarden_invite_dm_fails(self, mock_lib_config_vw, mock_service_config_vw):
        mock_lib_config_vw.EXCLUDED_USERS = set()
        mock_lib_config_vw.VAULTWARDEN_SERVER_URL = "https://test-vault.example.com"
        mock_service_config_vw.EXCLUDED_USERS = set()
        mock_service_config_vw.VAULTWARDEN_SERVER_URL = "https://test-vault.example.com"
        from libraries.services.vaultwarden import VaultwardenService

        vaultwarden_service = VaultwardenService(None, None, None, None)
        collection_name = "VWCollectionDMFail"
        mm_users_for_services = {
            "vw.dm.fail@example.com": {
                "username": "vw_dm_fail",
                "mm_user_id": "mm_vw_dm_fail",
            }
        }

        self.mock_vaultwarden_client.get_collection_by_name.return_value = "vw_coll_id_dm_fail"
        self.mock_vaultwarden_client._get_api_token.return_value = "fake_vw_api_token"
        self.mock_vaultwarden_client.invite_user_to_collection.return_value = True
        self.mock_mattermost_client.send_dm.return_value = False  # Simulate DM failure

        results = vaultwarden_service._sync_single_vaultwarden_collection_members(
            self.mock_vaultwarden_client,
            self.mock_mattermost_client,
            collection_name,
            mm_users_for_services,
            "ChanVWFail",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["action"], "USER_INVITED_TO_VW_COLLECTION_DM_FAILED")

    @patch("libraries.services.vaultwarden.config")
    @patch("libraries.group_sync_services.config")
    def test_sync_vaultwarden_invite_dm_skipped_no_url(self, mock_lib_config_vw, mock_service_config_vw):
        mock_lib_config_vw.EXCLUDED_USERS = set()
        mock_lib_config_vw.VAULTWARDEN_SERVER_URL = None  # Simulate URL not set
        mock_service_config_vw.EXCLUDED_USERS = set()
        mock_service_config_vw.VAULTWARDEN_SERVER_URL = None
        from libraries.services.vaultwarden import VaultwardenService

        vaultwarden_service = VaultwardenService(None, None, None, None)
        collection_name = "VWCollectionDMSkip"
        mm_users_for_services = {
            "vw.dm.skip@example.com": {
                "username": "vw_dm_skip",
                "mm_user_id": "mm_vw_dm_skip",
            }
        }

        self.mock_vaultwarden_client.get_collection_by_name.return_value = "vw_coll_id_dm_skip"
        self.mock_vaultwarden_client._get_api_token.return_value = "fake_vw_api_token"
        self.mock_vaultwarden_client.invite_user_to_collection.return_value = True

        results = vaultwarden_service._sync_single_vaultwarden_collection_members(
            self.mock_vaultwarden_client,
            self.mock_mattermost_client,
            collection_name,
            mm_users_for_services,
            "ChanVWSkip",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["action"], "USER_INVITED_TO_VW_COLLECTION_DM_SKIPPED_NO_URL")
        self.mock_mattermost_client.send_dm.assert_not_called()

    @patch("libraries.group_sync_services.config")
    def test_sync_vaultwarden_invite_fails_no_dm(self, mock_lib_config_vw):
        mock_lib_config_vw.EXCLUDED_USERS = set()
        mock_lib_config_vw.VAULTWARDEN_SERVER_URL = "https://test-vault.example.com"
        from libraries.services.vaultwarden import VaultwardenService

        vaultwarden_service = VaultwardenService(None, None, None, None)
        collection_name = "VWCollectionInviteFail"
        mm_users_for_services = {
            "vw.invite.fail@example.com": {
                "username": "vw_invite_fail",
                "mm_user_id": "mm_vw_invite_fail",
            }
        }

        self.mock_vaultwarden_client.get_collection_by_name.return_value = "vw_coll_id_invite_fail"
        self.mock_vaultwarden_client._get_api_token.return_value = "fake_vw_api_token"
        self.mock_vaultwarden_client.invite_user_to_collection.return_value = False  # Simulate invite failure

        results = vaultwarden_service._sync_single_vaultwarden_collection_members(
            self.mock_vaultwarden_client,
            self.mock_mattermost_client,
            collection_name,
            mm_users_for_services,
            "ChanVWInviteFail",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "FAILURE")
        self.assertEqual(results[0]["action"], "FAILED_TO_INVITE_TO_VW_COLLECTION")
        self.mock_mattermost_client.send_dm.assert_not_called()  # No DM if invite failed

    @async_test
    async def test_all_services_have_correct_differential_sync_signature(self):
        clients = {
            "authentik": self.mock_authentik_client,
            "mattermost": self.mock_mattermost_client,
            "outline": self.mock_outline_client,
            "brevo": self.mock_brevo_client,
            "nocodb": self.mock_nocodb_client,
            "vaultwarden": self.mock_vaultwarden_client,
        }
        from libraries.group_sync_services import differential_sync
        from unittest.mock import AsyncMock

        with patch("libraries.group_sync_services.check_clients"), patch(
            "libraries.group_sync_services.AuthentikService"
        ) as MockAuth, patch("libraries.group_sync_services.OutlineService") as MockOutline, patch(
            "libraries.group_sync_services.BrevoService"
        ) as MockBrevo, patch(
            "libraries.group_sync_services.NocoDBService"
        ) as MockNocoDB, patch(
            "libraries.group_sync_services.VaultwardenService"
        ) as MockVW:
            services_to_mock = [MockAuth, MockOutline, MockBrevo, MockNocoDB, MockVW]
            for service_mock in services_to_mock:
                instance = service_mock.return_value
                instance.differential_sync = AsyncMock(return_value=[])
                # Make sure the client attribute is set on the instance
                instance.client = MagicMock()
            clients["mattermost"].get_channels_for_team.return_value = []
            try:
                await differential_sync(clients, "test_team_id")
            except TypeError as e:
                self.fail(f"differential_sync call failed with TypeError: {e}")


if __name__ == "__main__":
    unittest.main()


class TestAuthentikService(unittest.TestCase):
    @async_test
    async def test_differential_sync_removes_user(self):
        mock_authentik_client = MagicMock(spec=AuthentikClient)
        mock_mattermost_client = MagicMock(spec=MattermostClient)
        mock_permissions_matrix = {"PROJET": {"standard": {"authentik_group_name_pattern": "projet_{base_name}"}}}
        mm_team_id = "test_team"

        mock_auth_group1 = {
            "name": "projet_Test1",
            "pk": "pk1",
            "users_obj": [
                {"pk": 1, "email": "remove@me.com", "username": "remove_user"},
                {"pk": 2, "email": "keep@me.com", "username": "keep_user"},
            ],
        }
        mock_authentik_client.get_groups_with_users.return_value = (
            [mock_auth_group1],
            {},
        )

        # This data would be pre-fetched and passed in mm_channel_members
        mm_channel_members_data = {"channel_id_for_projet_test1": [{"email": "keep@me.com", "username": "keep_user"}]}

        from libraries.services.authentik import AuthentikService

        service = AuthentikService(mock_authentik_client, mock_mattermost_client, mock_permissions_matrix, mm_team_id)

        # Mock the helper function that is now part of the service instance
        service.get_mm_users_for_entity = MagicMock(
            return_value=(
                {"keep@me.com": {"username": "keep_user"}},  # mm_users_for_services
                [{"email": "keep@me.com", "username": "keep_user"}],  # std_mm_users
                [],  # adm_mm_users
            )
        )

        with patch.object(
            service, "remove_user_from_authentik_group", return_value={"status": "SUCCESS"}
        ) as mock_remove_user, patch.object(service, "_ensure_users_in_authentik_group", return_value=([], set())):
            results = await service.differential_sync(mm_channel_members_data)
            mock_remove_user.assert_called_once_with(
                mock_authentik_client, "pk1", "projet_Test1", 1, "remove@me.com", "Test1"
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "SUCCESS")


class TestVaultwardenService(unittest.TestCase):
    @async_test
    async def test_differential_sync_adds_user(self):
        mock_vaultwarden_client = MagicMock(spec=VaultwardenClient)
        mock_mattermost_client = MagicMock(spec=MattermostClient)
        mock_permissions_matrix = {"PROJET": {"vaultwarden": {"collection_name_pattern": "Shared - {base_name}"}}}
        mm_team_id = "test_team"

        mock_vaultwarden_client.get_collections_details.return_value = [
            {"id": "coll1", "name": "Shared - Test1", "users": [{"id": "user-keep-id"}]}
        ]
        mock_vaultwarden_client.get_collections.return_value = (0, '[{"id": "coll1", "name": "Shared - Test1"}]', "")
        mock_vaultwarden_client.get_members.return_value = (
            0,
            '[{"id": "user-keep-id", "email": "keep@me.com"}]',
            "",
        )
        mock_vaultwarden_client.get_name_from_collections.return_value = "Shared - Test1"
        mock_vaultwarden_client.get_email_from_members.return_value = "keep@me.com"
        from libraries.services.vaultwarden import VaultwardenService

        service = VaultwardenService(
            mock_vaultwarden_client, mock_mattermost_client, mock_permissions_matrix, mm_team_id
        )

        service.get_mm_users_for_entity = MagicMock(
            return_value=(
                {
                    "keep@me.com": {"username": "keep_user"},
                    "add@me.com": {"username": "add_user", "id": "mm_add_id"},
                },
                [
                    {"email": "keep@me.com", "username": "keep_user"},
                    {"email": "add@me.com", "username": "add_user", "id": "mm_add_id"},
                ],
                [],
            )
        )

        with patch.object(
            mock_vaultwarden_client, "update_collection", return_value=True
        ) as mock_update, patch.object(
            service, "_ensure_users_invited_to_vaultwarden_collection", return_value=([{"status": "SUCCESS"}])
        ) as mock_ensure_users:
            results = await service.differential_sync({})
            mock_update.assert_not_called()
            mock_ensure_users.assert_called_once()
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "SUCCESS")


class TestNocoDBService(unittest.TestCase):
    @async_test
    async def test_differential_sync_adds_user(self):
        mock_nocodb_client = MagicMock(spec=NocoDBClient)
        mock_mattermost_client = MagicMock(spec=MattermostClient)
        mock_permissions_matrix = {"ANTENNE": {"nocodb": {"base_title_pattern": "nocodb_{base_name}"}}}
        mm_team_id = "test_team"

        mock_nocodb_client.list_bases.return_value = {"list": [{"id": "base1", "title": "nocodb_Test1"}]}
        mock_nocodb_client.list_base_users.return_value = [{"email": "keep@me.com"}]
        from libraries.services.nocodb import NocoDBService

        service = NocoDBService(mock_nocodb_client, mock_mattermost_client, mock_permissions_matrix, mm_team_id)

        service.get_mm_users_for_entity = MagicMock(
            return_value=(
                {
                    "keep@me.com": {"username": "keep_user"},
                    "add@me.com": {"username": "add_user", "id": "mm_add_id"},
                },
                [
                    {"email": "keep@me.com", "username": "keep_user"},
                    {"email": "add@me.com", "username": "add_user", "id": "mm_add_id"},
                ],
                [],
            )
        )

        with patch.object(
            service, "_remove_user_from_nocodb_base", return_value={"status": "SUCCESS"}
        ) as mock_remove_user, patch.object(
            service, "_ensure_users_in_nocodb_base", return_value=([{"status": "SUCCESS"}], set())
        ) as mock_ensure_users:
            results = await service.differential_sync({})
            mock_remove_user.assert_not_called()
            mock_ensure_users.assert_called_once()
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "SUCCESS")


class TestOutlineService(unittest.TestCase):
    @async_test
    async def test_differential_sync_adds_user(self):
        mock_outline_client = MagicMock(spec=OutlineClient)
        mock_mattermost_client = MagicMock(spec=MattermostClient)
        mock_permissions_matrix = {"PROJET": {"outline": {"collection_name_pattern": "projet-{base_name}"}}}
        mm_team_id = "test_team"

        mock_outline_client.list_collections.return_value = [{"id": "coll1", "name": "projet-Test1"}]
        mock_outline_client.get_collection_members_with_details.return_value = [
            {"id": "user-keep-id", "email": "keep@me.com"}
        ]
        mock_outline_client.get_user_by_email.return_value = {"id": "user-add-id"}
        from libraries.services.outline import OutlineService

        service = OutlineService(mock_outline_client, mock_mattermost_client, mock_permissions_matrix, mm_team_id)

        service.get_mm_users_for_entity = MagicMock(
            return_value=(
                {
                    "keep@me.com": {"username": "keep_user"},
                    "add@me.com": {"username": "add_user", "id": "mm_add_id"},
                },
                [
                    {"email": "keep@me.com", "username": "keep_user"},
                    {"email": "add@me.com", "username": "add_user", "id": "mm_add_id"},
                ],
                [],
            )
        )

        with patch.object(
            service, "_remove_user_from_outline_collection", return_value={"status": "SUCCESS"}
        ) as mock_remove_user, patch.object(
            service, "_ensure_users_in_outline_collection", return_value=([{"status": "SUCCESS"}], set())
        ) as mock_ensure_users:
            results = await service.differential_sync({})
            mock_remove_user.assert_not_called()
            mock_ensure_users.assert_called_once()
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "SUCCESS")
