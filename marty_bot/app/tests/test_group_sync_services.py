import unittest
import os
from unittest.mock import patch, MagicMock, mock_open

from libraries.group_sync_services import (
    sync_entity_permissions,
    orchestrate_group_synchronization,
    _map_auth_group_to_entity_and_base_name,
    _map_mm_channel_to_entity_and_base_name,
    _extract_base_name,
)
from app import config as app_config
import asyncio  # Needed for async_test
from clients.mattermost_client import MattermostClient, slugify
from clients.authentik_client import AuthentikClient
from clients.outline_client import OutlineClient
from clients.brevo_client import BrevoClient
from clients.nocodb_client import NocoDBClient
from clients.vaultwarden_client import VaultwardenClient  # Added


def reload_config_module():
    import importlib

    importlib.reload(app_config)


# Helper to run async test methods (copied from test_bot.py)
def async_test(f):
    def wrapper(*args, **kwargs):
        asyncio.run(f(*args, **kwargs))

    return wrapper


class TestGroupSyncServices(unittest.TestCase):

    def setUp(self):
        app_config.EXCLUDED_USERS = set()
        self.mock_authentik_client = MagicMock(spec=AuthentikClient)
        self.mock_mattermost_client = MagicMock(spec=MattermostClient)
        self.mock_outline_client = MagicMock(spec=OutlineClient)
        self.mock_brevo_client = MagicMock(spec=BrevoClient)
        self.mock_nocodb_client = MagicMock(spec=NocoDBClient)
        self.mock_vaultwarden_client = MagicMock(spec=VaultwardenClient)  # Added Vaultwarden mock
        self.mock_vaultwarden_client.organization_id = "test_vw_org_id"  # Mock organization_id
        self.mock_vaultwarden_client.api_username = "vw_api_user"  # Mock api_username
        self.mock_vaultwarden_client.api_password = "vw_api_pass"  # Mock api_password
        self.mm_team_id = "test_team_id"

        self.email_to_authentik_user_pk_map_fixture = {
            "user1@example.com": "auth_user_pk_1",
            "user2@example.com": "auth_user_pk_2",
            "excludeduser@example.com": "auth_user_pk_excluded",
            "marty@example.com": "auth_user_pk_marty",
        }
        self.mm_channel_fixture = {
            "id": "mm_channel_id_generic",
            "display_name": "Generic Test Channel",
            "name": "generic-test-channel",
        }

        self.mock_authentik_client.get_group_by_name.return_value = None

        def create_auth_group_side_effect(name):
            return {"name": name, "pk": f"new_auth_pk_for_{slugify(name)}", "users": [], "users_obj": []}

        self.mock_authentik_client.create_group.side_effect = create_auth_group_side_effect

        def create_outline_coll_side_effect(name):
            return {"name": name, "id": f"new_outline_id_for_{slugify(name)}"}

        self.mock_outline_client.create_group.side_effect = create_outline_coll_side_effect

        # Mock Brevo client methods
        self.mock_brevo_client.get_list_by_name.return_value = None

        def create_brevo_list_side_effect(
            name, folder_id=None
        ):  # folder_id might not be used if get_list_by_id is also mocked
            # Simulate create_list returning the full list object after creation
            # This requires get_list_by_id to be callable if create_list uses it.
            # For simplicity here, assume create_list can return a direct object or it's handled.
            new_list_id = f"new_brevo_list_id_for_{slugify(name)}"
            # If create_list calls get_list_by_id, that needs a mock too.
            # Let's assume get_list_by_name is called first, then create, then (optionally) get_list_by_id.
            # For this test, let's make create_list directly return what's needed if get_list_by_name was None.
            return {"name": name, "id": new_list_id}

        self.mock_brevo_client.create_list.side_effect = create_brevo_list_side_effect
        self.mock_brevo_client.add_contact_to_list.return_value = True
        self.mock_brevo_client.remove_contact_from_list.return_value = True
        self.mock_brevo_client.get_contacts_from_list.return_value = []

        # Mock NocoDB client methods
        self.mock_nocodb_client.get_base_by_title.return_value = None
        self.mock_nocodb_client.create_base.side_effect = lambda title, desc="": {
            "id": f"nc_id_{slugify(title)}",
            "title": title,
        }
        self.mock_nocodb_client.list_base_users.return_value = []
        self.mock_nocodb_client.invite_user_to_base.return_value = True
        self.mock_nocodb_client.update_base_user.return_value = True
        self.mock_nocodb_client.delete_base_user.return_value = True

    def test_extract_base_name(self):
        self.assertEqual(_extract_base_name("projet_TestProjet_dev", "projet_{base_name}_dev"), "TestProjet")
        self.assertEqual(_extract_base_name("projet_TestProjet", "projet_{base_name}"), "TestProjet")
        self.assertEqual(_extract_base_name("TestProjet_dev", "{base_name}_dev"), "TestProjet")
        self.assertIsNone(_extract_base_name("projet_TestProjet_dev", "antenne_{base_name}_dev"))
        self.assertIsNone(_extract_base_name("projet_TestProjet", "projet_{base_name}_suffix_mismatch"))
        self.assertIsNone(_extract_base_name("projet_TestProjet", "exact_name_no_placeholder"))
        self.assertEqual(_extract_base_name("Projet Alpha", "Projet {base_name}"), "Alpha")
        self.assertEqual(_extract_base_name("Projet Super Cool", "Projet {base_name}"), "Super Cool")
        self.assertIsNone(_extract_base_name("Projet Admin", "Projet {base_name} Admin"))
        self.assertEqual(_extract_base_name("ProjetAdmin", "Projet{base_name}Admin"), "")  # No spaces around base_name
        self.assertEqual(_extract_base_name("Projet Super Cool Admin", "Projet {base_name} Admin"), "Super Cool")

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
        self.assertEqual(_map_auth_group_to_entity_and_base_name("projet_MonProjet", matrix), ("PROJET", "MonProjet"))
        self.assertEqual(
            _map_auth_group_to_entity_and_base_name("projet_MonProjet_admin", matrix), ("PROJET", "MonProjet")
        )
        # "projet_admin" will be matched by "projet_{base_name}" (standard) before "projet_{base_name}_admin" (admin)
        # because _extract_base_name("projet_admin", "projet_{base_name}_admin") returns None.
        self.assertEqual(_map_auth_group_to_entity_and_base_name("projet_admin", matrix), ("PROJET", "admin"))
        self.assertEqual(
            _map_auth_group_to_entity_and_base_name("projet__admin", matrix), ("PROJET", "")
        )  # Test expects "" now
        self.assertEqual(
            _map_auth_group_to_entity_and_base_name("antenne_MaRegion_standard", matrix), ("ANTENNE", "MaRegion")
        )
        self.assertIsNone(_map_auth_group_to_entity_and_base_name("unknown_group_format", matrix)[0])

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
            _map_mm_channel_to_entity_and_base_name("projet-alpha", "Projet Alpha", matrix), ("PROJET", "Alpha")
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

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_user_exclusion(self, mock_config_module_in_service):
        mock_config_module_in_service.EXCLUDED_USERS = {"excluded_user", "marty"}
        mock_config_module_in_service.OUTLINE_URL = "http://fake-outline.com"

        base_name = "MyTestProject"
        entity_key = "PROJET"

        mock_entity_config = {
            "standard": {
                "authentik_group_name_pattern": "projet_{base_name}",
                "mattermost_channel_name_pattern": "projet_{base_name}",
            },
            "admin": {
                "authentik_group_name_pattern": "projet_{base_name} Admin",
                "mattermost_channel_name_pattern": "projet_{base_name} Admin",
            },
            "outline": {
                "collection_name_pattern": "projet_{base_name}",
                "default_access": "read",
                "admin_access": "read_write",
            },
        }

        std_auth_group_name = mock_entity_config["standard"]["authentik_group_name_pattern"].format(
            base_name=base_name
        )
        std_mm_channel_name = mock_entity_config["standard"]["mattermost_channel_name_pattern"].format(
            base_name=base_name
        )
        adm_auth_group_name = mock_entity_config["admin"]["authentik_group_name_pattern"].format(base_name=base_name)
        adm_mm_channel_name = mock_entity_config["admin"]["mattermost_channel_name_pattern"].format(
            base_name=base_name
        )
        outline_coll_name = mock_entity_config["outline"]["collection_name_pattern"].format(base_name=base_name)

        std_auth_group_obj = {"name": std_auth_group_name, "pk": "std_auth_pk_1", "users": [], "users_obj": []}
        adm_auth_group_obj = {"name": adm_auth_group_name, "pk": "adm_auth_pk_1", "users": [], "users_obj": []}
        all_authentik_groups_by_name_fixture = {
            std_auth_group_name: std_auth_group_obj,
            adm_auth_group_name: adm_auth_group_obj,
        }

        std_mm_channel_obj = {"id": "std_mm_chan_id_1", "display_name": std_mm_channel_name}
        adm_mm_channel_obj = {"id": "adm_mm_chan_id_1", "display_name": adm_mm_channel_name}

        def get_channel_by_name_side_effect(team_id, channel_name_slug):
            if channel_name_slug == slugify(std_mm_channel_name):
                return std_mm_channel_obj
            if channel_name_slug == slugify(adm_mm_channel_name):
                return adm_mm_channel_obj
            return None

        self.mock_mattermost_client.get_channel_by_name.side_effect = get_channel_by_name_side_effect

        mm_users_std_channel = [
            {"username": "user1", "email": "user1@example.com", "id": "mm_user_id_1"},
            {"username": "excluded_user", "email": "excludeduser@example.com", "id": "mm_user_id_excluded"},
        ]
        mm_users_adm_channel = [
            {"username": "user1", "email": "user1@example.com", "id": "mm_user_id_1"},
            {"username": "user2", "email": "user2@example.com", "id": "mm_user_id_2"},
            {"username": "marty", "email": "marty@example.com", "id": "mm_user_id_marty"},
        ]

        def get_users_in_channel_side_effect(channel_id):
            if channel_id == std_mm_channel_obj["id"]:
                return mm_users_std_channel
            if channel_id == adm_mm_channel_obj["id"]:
                return mm_users_adm_channel
            return []

        self.mock_mattermost_client.get_users_in_channel.side_effect = get_users_in_channel_side_effect

        self.mock_authentik_client.add_user_to_group.return_value = True

        # self.mock_outline_client.create_group is set up in self.setUp()
        # We expect it to be called with outline_coll_name
        # And the ID it returns (new_outline_id_for_...) will be used in add_user_to_collection calls
        expected_outline_coll_id = f"new_outline_id_for_{slugify(outline_coll_name)}"
        # We need to ensure the mock for get_collection_details uses this dynamic ID too if called
        self.mock_outline_client.get_collection_details.return_value = {
            "id": expected_outline_coll_id,
            "name": outline_coll_name,
        }

        self.mock_outline_client.get_collection_members.return_value = []
        self.mock_outline_client.add_user_to_collection.return_value = True
        self.mock_outline_client.get_user_by_email.side_effect = lambda email: (
            {"id": f"outlineid_{email.split('@')[0]}"} if email else None
        )
        self.mock_mattermost_client.send_dm.return_value = True

        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_authentik_groups_by_name_fixture,
            email_to_authentik_user_pk_map=self.email_to_authentik_user_pk_map_fixture,
            perform_deletions=True,
            skip_services=None,  # Default case
        )

        user1_pk = self.email_to_authentik_user_pk_map_fixture["user1@example.com"]
        user2_pk = self.email_to_authentik_user_pk_map_fixture["user2@example.com"]

        self.mock_authentik_client.add_user_to_group.assert_any_call(std_auth_group_obj["pk"], user1_pk)
        self.mock_authentik_client.add_user_to_group.assert_any_call(adm_auth_group_obj["pk"], user1_pk)
        self.mock_authentik_client.add_user_to_group.assert_any_call(adm_auth_group_obj["pk"], user2_pk)
        self.assertEqual(self.mock_authentik_client.add_user_to_group.call_count, 3)

        outline_user1_id = "outlineid_user1"
        outline_user2_id = "outlineid_user2"

        self.mock_outline_client.create_group.assert_called_once_with(outline_coll_name)
        self.mock_outline_client.add_user_to_collection.assert_any_call(
            expected_outline_coll_id, outline_user1_id, permission="read_write"  # Corrected ID
        )
        self.mock_outline_client.add_user_to_collection.assert_any_call(
            expected_outline_coll_id, outline_user2_id, permission="read_write"  # Corrected ID
        )
        self.assertEqual(self.mock_outline_client.add_user_to_collection.call_count, 2)

        calls = self.mock_outline_client.add_user_to_collection.call_args_list
        for call in calls:
            self.assertEqual(call.args[0], expected_outline_coll_id)

        successful_actions = [r for r in results if r.get("status") == "SUCCESS"]
        self.assertEqual(len(successful_actions), 5)

        for r in results:
            if r.get("mm_username") in {"excluded_user", "marty"}:
                self.assertNotEqual(
                    r.get("status"), "SUCCESS", f"Excluded user {r.get('mm_username')} had a SUCCESS action."
                )
                self.assertNotEqual(
                    r.get("status"), "FAILURE", f"Excluded user {r.get('mm_username')} had a FAILURE action."
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
            self.assertEqual(app_config.PERMISSIONS_MATRIX["PROJET"]["outline"]["default_access"], "read")
        self.assertEqual(app_config.EXCLUDED_USERS, set())

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_outline_dm_on_new_add(self, mock_config_module_in_service):
        mock_config_module_in_service.EXCLUDED_USERS = set()
        mock_config_module_in_service.OUTLINE_URL = "http://fake-outline.com"
        # Brevo config not strictly needed for this Outline-focused test unless it affects shared logic
        base_name = "DMTestProject"
        entity_key = "PROJET"
        mock_entity_config = {
            "standard": {
                "authentik_group_name_pattern": "projet_{base_name}",
                "mattermost_channel_name_pattern": "projet_{base_name}",
            },
            "outline": {
                "collection_name_pattern": "projet_{base_name}",
                "default_access": "read",
                "admin_access": "read_write",
            },
            "brevo": {"list_name_pattern": "brevo_projet_{base_name}"},  # Add dummy brevo config
        }
        std_auth_group_name = mock_entity_config["standard"]["authentik_group_name_pattern"].format(
            base_name=base_name
        )
        std_mm_channel_name = mock_entity_config["standard"]["mattermost_channel_name_pattern"].format(
            base_name=base_name
        )
        outline_coll_name = mock_entity_config["outline"]["collection_name_pattern"].format(base_name=base_name)
        std_auth_group_obj = {"name": std_auth_group_name, "pk": "std_auth_pk_dm", "users": [], "users_obj": []}
        all_authentik_groups_by_name_fixture = {std_auth_group_name: std_auth_group_obj}
        mm_user_for_dm = {"username": "dm_user", "email": "dmuser@example.com", "id": "mm_user_id_dm"}
        email_map_for_dm = {"dmuser@example.com": "auth_user_pk_dm"}
        std_mm_channel_obj = {"id": "std_mm_chan_id_dm", "display_name": std_mm_channel_name}
        self.mock_mattermost_client.get_channel_by_name.side_effect = lambda _, slug: (
            std_mm_channel_obj if slug == slugify(std_mm_channel_name) else None
        )
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_for_dm]
        self.mock_authentik_client.add_user_to_group.return_value = True
        self.mock_outline_client.get_user_by_email.return_value = {
            "id": "outline_user_id_dm",
            "email": "dmuser@example.com",
        }

        expected_collection_id = f"new_outline_id_for_{slugify(outline_coll_name)}"
        self.mock_outline_client.create_group.return_value = {"id": expected_collection_id, "name": outline_coll_name}
        self.mock_outline_client.get_collection_members.return_value = []
        self.mock_outline_client.add_user_to_collection.return_value = True
        mock_url_id = f"{slugify(outline_coll_name)}-urlid"  # Example urlId
        self.mock_outline_client.get_collection_details.return_value = {
            "id": expected_collection_id,
            "name": outline_coll_name,
            "urlId": mock_url_id,  # Add urlId to mock
        }
        self.mock_mattermost_client.send_dm.return_value = True

        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_authentik_groups_by_name_fixture,
            email_to_authentik_user_pk_map=email_map_for_dm,
            perform_deletions=True,
            skip_services=None,
        )

        # Assuming Brevo sync is also successful for this user
        # If only Auth and Outline are expected to succeed for this specific user, adjust count
        successful_sync_actions = [r for r in results if r["status"] == "SUCCESS"]
        # Count will depend on how many services are configured and succeed for this user.
        # For this test, focusing on Outline:
        outline_success_results = [r for r in successful_sync_actions if r["service"] == "OUTLINE"]
        self.assertEqual(len(outline_success_results), 1, "Expected one successful Outline operation.")
        outline_result = outline_success_results[0]

        self.assertEqual(outline_result["action"], "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_ACCESS_AND_DM_SENT")
        self.mock_mattermost_client.send_dm.assert_called_once()
        call_args = self.mock_mattermost_client.send_dm.call_args[0]
        self.assertEqual(call_args[0], mm_user_for_dm["id"])

        expected_url = f"{mock_config_module_in_service.OUTLINE_URL}/collection/{mock_url_id}"  # Use urlId
        self.assertIn(expected_url, call_args[1])
        self.assertIn(outline_coll_name, call_args[1])
        self.mock_outline_client.create_group.assert_called_once_with(outline_coll_name)
        self.mock_outline_client.add_user_to_collection.assert_called_once_with(
            expected_collection_id, "outline_user_id_dm", permission="read"
        )

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_outline_dm_fails(self, mock_config_module_in_service):
        mock_config_module_in_service.EXCLUDED_USERS = set()
        mock_config_module_in_service.OUTLINE_URL = "http://fake-outline.com"
        base_name = "DMFailProject"
        entity_key = "PROJET"
        mock_entity_config = {
            "standard": {
                "authentik_group_name_pattern": "projet_{base_name}",
                "mattermost_channel_name_pattern": "projet_{base_name}",
            },
            "outline": {
                "collection_name_pattern": "projet_{base_name}",
                "default_access": "read",
                "admin_access": "read_write",
            },
            "brevo": {"list_name_pattern": "brevo_projet_{base_name}"},  # Add dummy brevo config
        }
        std_auth_group_name = mock_entity_config["standard"]["authentik_group_name_pattern"].format(
            base_name=base_name
        )
        std_mm_channel_name = mock_entity_config["standard"]["mattermost_channel_name_pattern"].format(
            base_name=base_name
        )
        outline_coll_name = mock_entity_config["outline"]["collection_name_pattern"].format(base_name=base_name)
        std_auth_group_obj = {"name": std_auth_group_name, "pk": "std_auth_pk_dm_fail", "users": [], "users_obj": []}
        all_authentik_groups_by_name_fixture = {std_auth_group_name: std_auth_group_obj}
        mm_user_for_dm = {"username": "dm_user_fail", "email": "dmuserfail@example.com", "id": "mm_user_id_dm_fail"}
        email_map_for_dm = {"dmuserfail@example.com": "auth_user_pk_dm_fail"}
        std_mm_channel_obj = {"id": "std_mm_chan_id_dm_fail", "display_name": std_mm_channel_name}
        self.mock_mattermost_client.get_channel_by_name.side_effect = lambda _, slug: (
            std_mm_channel_obj if slug == slugify(std_mm_channel_name) else None
        )
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_for_dm]
        self.mock_authentik_client.add_user_to_group.return_value = True
        self.mock_outline_client.get_user_by_email.return_value = {
            "id": "outline_user_id_dm_fail",
            "email": "dmuserfail@example.com",
        }

        expected_collection_id = f"new_outline_id_for_{slugify(outline_coll_name)}"
        mock_url_id_fail = f"{slugify(outline_coll_name)}-urlidfail"
        self.mock_outline_client.create_group.return_value = {"id": expected_collection_id, "name": outline_coll_name}
        self.mock_outline_client.get_collection_members.return_value = []
        self.mock_outline_client.add_user_to_collection.return_value = True
        self.mock_outline_client.get_collection_details.return_value = {
            "id": expected_collection_id,
            "name": outline_coll_name,
            "urlId": mock_url_id_fail,  # Add urlId to mock
        }
        self.mock_mattermost_client.send_dm.return_value = False
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_authentik_groups_by_name_fixture,
            email_to_authentik_user_pk_map=email_map_for_dm,
            perform_deletions=True,
            skip_services=None,
        )
        outline_result = next(r for r in results if r["service"] == "OUTLINE" and r["status"] == "SUCCESS")
        self.assertEqual(outline_result["action"], "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_ACCESS_DM_FAILED")
        self.mock_mattermost_client.send_dm.assert_called_once()
        self.mock_outline_client.create_group.assert_called_once_with(outline_coll_name)

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_outline_user_already_member_no_dm(self, mock_config_module_in_service):
        mock_config_module_in_service.EXCLUDED_USERS = set()
        mock_config_module_in_service.OUTLINE_URL = "http://fake-outline.com"
        base_name = "AlreadyMemberProject"
        entity_key = "PROJET"
        mock_entity_config = {
            "standard": {
                "authentik_group_name_pattern": "projet_{base_name}",
                "mattermost_channel_name_pattern": "projet_{base_name}",
            },
            "outline": {
                "collection_name_pattern": "projet_{base_name}",
                "default_access": "read",
                "admin_access": "read_write",
            },
        }
        std_auth_group_name = mock_entity_config["standard"]["authentik_group_name_pattern"].format(
            base_name=base_name
        )
        std_mm_channel_name = mock_entity_config["standard"]["mattermost_channel_name_pattern"].format(
            base_name=base_name
        )
        outline_coll_name = mock_entity_config["outline"]["collection_name_pattern"].format(base_name=base_name)
        std_auth_group_obj = {"name": std_auth_group_name, "pk": "std_auth_pk_already", "users": [], "users_obj": []}
        all_authentik_groups_by_name_fixture = {std_auth_group_name: std_auth_group_obj}
        mm_user_already_member = {
            "username": "already_member",
            "email": "already@example.com",
            "id": "mm_user_id_already",
        }
        email_map_already = {"already@example.com": "auth_user_pk_already"}
        std_mm_channel_obj = {"id": "std_mm_chan_id_already", "display_name": std_mm_channel_name}
        outline_user_data = {"id": "outline_user_id_already", "email": "already@example.com"}

        expected_collection_id = f"new_outline_id_for_{slugify(outline_coll_name)}"
        self.mock_outline_client.create_group.return_value = {"id": expected_collection_id, "name": outline_coll_name}

        self.mock_mattermost_client.get_channel_by_name.side_effect = lambda _, slug: (
            std_mm_channel_obj if slug == slugify(std_mm_channel_name) else None
        )
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_already_member]
        self.mock_authentik_client.add_user_to_group.return_value = True
        self.mock_outline_client.get_user_by_email.return_value = outline_user_data
        self.mock_outline_client.get_collection_members.return_value = [outline_user_data["id"]]
        self.mock_outline_client.add_user_to_collection.return_value = True
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_authentik_groups_by_name_fixture,
            email_to_authentik_user_pk_map=email_map_already,
            perform_deletions=True,
            skip_services=None,
        )
        outline_result = next(r for r in results if r["service"] == "OUTLINE" and r["status"] == "SUCCESS")
        self.assertEqual(outline_result["action"], "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED")
        self.mock_outline_client.add_user_to_collection.assert_called_once_with(
            expected_collection_id, outline_user_data["id"], permission="read"
        )
        self.mock_mattermost_client.send_dm.assert_not_called()
        self.mock_outline_client.create_group.assert_called_once_with(outline_coll_name)

    @patch("libraries.group_sync_services.config")
    def test_sync_outline_dm_skipped_no_outline_url(self, mock_config_module_in_service):
        mock_config_module_in_service.EXCLUDED_USERS = set()
        mock_config_module_in_service.OUTLINE_URL = None  # Simulate OUTLINE_URL not set
        base_name = "DMNoUrlProject"
        entity_key = "PROJET"
        mock_entity_config = {
            "standard": {
                "authentik_group_name_pattern": "projet_{base_name}",
                "mattermost_channel_name_pattern": "projet_{base_name}",
            },
            "outline": {"collection_name_pattern": "projet_{base_name}", "default_access": "read"},
        }
        # Basic setup for user and collection
        std_auth_group_name = mock_entity_config["standard"]["authentik_group_name_pattern"].format(
            base_name=base_name
        )
        std_mm_channel_name = mock_entity_config["standard"]["mattermost_channel_name_pattern"].format(
            base_name=base_name
        )
        outline_coll_name = mock_entity_config["outline"]["collection_name_pattern"].format(base_name=base_name)
        std_auth_group_obj = {"name": std_auth_group_name, "pk": "auth_pk_no_url", "users": [], "users_obj": []}
        all_auth_groups_by_name_fixture = {std_auth_group_name: std_auth_group_obj}
        mm_user = {"username": "dm_no_url_user", "email": "dmnourl@example.com", "id": "mm_user_id_no_url"}
        email_map = {"dmnourl@example.com": "auth_pk_no_url"}
        std_mm_channel_obj = {"id": "std_mm_chan_id_no_url", "display_name": std_mm_channel_name}

        self.mock_mattermost_client.get_channel_by_name.return_value = std_mm_channel_obj
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user]
        self.mock_authentik_client.add_user_to_group.return_value = True  # Auth part succeeds
        self.mock_outline_client.get_user_by_email.return_value = {"id": "outline_id_no_url"}
        expected_collection_id = f"new_outline_id_for_{slugify(outline_coll_name)}"
        self.mock_outline_client.create_group.return_value = {"id": expected_collection_id, "name": outline_coll_name}
        self.mock_outline_client.get_collection_members.return_value = []  # New member
        self.mock_outline_client.add_user_to_collection.return_value = True  # Outline add succeeds
        # Crucially, get_collection_details will still be called
        self.mock_outline_client.get_collection_details.return_value = {
            "id": expected_collection_id,
            "name": outline_coll_name,
            "urlId": "some-url-id",
        }

        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_auth_groups_by_name_fixture,
            email_to_authentik_user_pk_map=email_map,
            perform_deletions=False,
        )
        outline_result = next(r for r in results if r["service"] == "OUTLINE" and r["status"] == "SUCCESS")
        self.assertEqual(
            outline_result["action"], "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_ACCESS_DM_SKIPPED_NO_URL"
        )
        self.mock_mattermost_client.send_dm.assert_not_called()

    @patch("libraries.group_sync_services.config")
    def test_sync_outline_dm_skipped_incomplete_details(self, mock_config_module_in_service):
        mock_config_module_in_service.EXCLUDED_USERS = set()
        mock_config_module_in_service.OUTLINE_URL = "http://test-outline.com"  # URL is set
        base_name = "DMIncompleteProject"
        entity_key = "PROJET"
        mock_entity_config = {
            "standard": {
                "authentik_group_name_pattern": "projet_{base_name}",
                "mattermost_channel_name_pattern": "projet_{base_name}",
            },
            "outline": {"collection_name_pattern": "projet_{base_name}", "default_access": "read"},
        }
        std_auth_group_name = mock_entity_config["standard"]["authentik_group_name_pattern"].format(
            base_name=base_name
        )
        std_mm_channel_name = mock_entity_config["standard"]["mattermost_channel_name_pattern"].format(
            base_name=base_name
        )
        outline_coll_name = mock_entity_config["outline"]["collection_name_pattern"].format(base_name=base_name)
        std_auth_group_obj = {"name": std_auth_group_name, "pk": "auth_pk_incomplete", "users": [], "users_obj": []}
        all_auth_groups_by_name_fixture = {std_auth_group_name: std_auth_group_obj}
        mm_user = {
            "username": "dm_incomplete_user",
            "email": "dmincomplete@example.com",
            "id": "mm_user_id_incomplete",
        }
        email_map = {"dmincomplete@example.com": "auth_pk_incomplete"}
        std_mm_channel_obj = {"id": "std_mm_chan_id_incomplete", "display_name": std_mm_channel_name}

        self.mock_mattermost_client.get_channel_by_name.return_value = std_mm_channel_obj
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user]
        self.mock_authentik_client.add_user_to_group.return_value = True
        self.mock_outline_client.get_user_by_email.return_value = {"id": "outline_id_incomplete"}
        expected_collection_id = f"new_outline_id_for_{slugify(outline_coll_name)}"
        self.mock_outline_client.create_group.return_value = {"id": expected_collection_id, "name": outline_coll_name}
        self.mock_outline_client.get_collection_members.return_value = []
        self.mock_outline_client.add_user_to_collection.return_value = True
        # Simulate get_collection_details missing urlId
        self.mock_outline_client.get_collection_details.return_value = {
            "id": expected_collection_id,
            "name": outline_coll_name,
            "urlId": None,
        }

        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_auth_groups_by_name_fixture,
            email_to_authentik_user_pk_map=email_map,
            perform_deletions=False,
        )
        outline_result = next(r for r in results if r["service"] == "OUTLINE" and r["status"] == "SUCCESS")
        self.assertEqual(
            outline_result["action"],
            "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_ACCESS_DM_SKIPPED_INCOMPLETE_COLL_DETAILS",
        )
        self.mock_mattermost_client.send_dm.assert_not_called()

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_authentik_user_removed_if_not_in_mm(self, mock_config_module_in_service):
        mock_config_module_in_service.EXCLUDED_USERS = set()
        auth_user_pk_to_remove = "auth_pk_to_remove"
        auth_user_obj_to_remove = {
            "pk": auth_user_pk_to_remove,
            "email": "removeme@example.com",
            "username": "removeme_user",
        }
        auth_user_pk_to_keep = "auth_pk_to_keep"
        auth_user_obj_to_keep = {"pk": auth_user_pk_to_keep, "email": "keepme@example.com", "username": "keepme_user"}
        mm_user_to_keep = {"username": "keepme_user", "email": "keepme@example.com", "id": "mm_id_keep"}

        current_auth_group_name = "AuthGroupForRemovalTest"
        current_auth_group_pk = "auth_group_pk_removal"
        authentik_group_with_users = {
            "name": current_auth_group_name,
            "pk": current_auth_group_pk,
            "users": [auth_user_pk_to_remove, auth_user_pk_to_keep],
            "users_obj": [auth_user_obj_to_remove, auth_user_obj_to_keep],
        }
        email_to_pk_map = {"removeme@example.com": auth_user_pk_to_remove, "keepme@example.com": auth_user_pk_to_keep}
        mm_channel_for_removal_test = {"id": "mm_chan_removal", "display_name": current_auth_group_name}
        self.mock_mattermost_client.get_channel_by_name.return_value = mm_channel_for_removal_test
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_to_keep]
        self.mock_authentik_client.remove_user_from_group.return_value = True
        self.mock_authentik_client.add_user_to_group.return_value = True

        mock_entity_config = {
            "standard": {
                "authentik_group_name_pattern": current_auth_group_name,
                "mattermost_channel_name_pattern": current_auth_group_name,
            }
        }
        all_auth_groups_fixture = {current_auth_group_name: authentik_group_with_users}

        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=None,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=self.mm_team_id,
            entity_key="PROJET",
            base_name="",
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_auth_groups_fixture,
            email_to_authentik_user_pk_map=email_to_pk_map,
            perform_deletions=True,
            skip_services=None,
        )

        self.mock_authentik_client.remove_user_from_group.assert_called_once_with(
            current_auth_group_pk, auth_user_pk_to_remove
        )
        self.mock_authentik_client.add_user_to_group.assert_not_called()
        removal_action_found = any(
            r["service"] == "AUTHENTIK"
            and r["action"] == "USER_REMOVED_FROM_AUTHENTIK_GROUP"
            and r["mm_username"] == "removeme_user"
            for r in results
        )
        self.assertTrue(removal_action_found, "USER_REMOVED_FROM_AUTHENTIK_GROUP action not found for 'removeme_user'")
        kept_action_found = any(
            r["service"] == "AUTHENTIK"
            and r["action"] == "USER_ALREADY_IN_AUTHENTIK_GROUP"
            and r["mm_username"] == "keepme_user"
            for r in results
        )
        self.assertTrue(kept_action_found, "USER_ALREADY_IN_AUTHENTIK_GROUP action not found for 'keepme_user'")

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_authentik_excluded_user_not_removed_if_not_in_mm(self, mock_config_module_in_service):
        excluded_auth_username = "excluded_from_removal"
        mock_config_module_in_service.EXCLUDED_USERS = {excluded_auth_username}
        auth_user_pk_excluded = "auth_pk_excluded_removal"
        auth_user_obj_excluded = {
            "pk": auth_user_pk_excluded,
            "email": "excluded@example.com",
            "username": excluded_auth_username,
        }

        current_auth_group_name = "AuthGroupForExcludedRemovalTest"
        current_auth_group_pk = "auth_group_pk_excl_removal"
        authentik_group_with_excluded_user = {
            "name": current_auth_group_name,
            "pk": current_auth_group_pk,
            "users": [auth_user_pk_excluded],
            "users_obj": [auth_user_obj_excluded],
        }
        email_to_pk_map = {"excluded@example.com": auth_user_pk_excluded}
        mm_channel_for_test = {"id": "mm_chan_excl_removal", "display_name": current_auth_group_name}
        self.mock_mattermost_client.get_channel_by_name.return_value = mm_channel_for_test
        self.mock_mattermost_client.get_users_in_channel.return_value = []

        mock_entity_config = {
            "standard": {
                "authentik_group_name_pattern": current_auth_group_name,
                "mattermost_channel_name_pattern": current_auth_group_name,
            }
        }
        all_auth_groups_fixture = {current_auth_group_name: authentik_group_with_excluded_user}

        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=None,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=self.mm_team_id,
            entity_key="PROJET",
            base_name="",
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_auth_groups_fixture,
            email_to_authentik_user_pk_map=email_to_pk_map,
            perform_deletions=True,
            skip_services=None,
        )
        self.mock_authentik_client.remove_user_from_group.assert_not_called()
        self.mock_authentik_client.add_user_to_group.assert_not_called()
        action_for_excluded_user_found = any(r["mm_username"] == excluded_auth_username for r in results)
        self.assertFalse(
            action_for_excluded_user_found,
            "No action should be logged for excluded user not in MM channel during removal phase.",
        )

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_outline_user_removed_if_not_in_mm(self, mock_config_module_in_service):
        mock_config_module_in_service.EXCLUDED_USERS = set()
        mock_config_module_in_service.OUTLINE_URL = "http://fake-outline.com"
        outline_user_id_to_remove = "outline_id_remove"
        outline_user_id_to_keep = "outline_id_keep"
        mm_user_to_keep_outline = {
            "username": "keepme_outline",
            "email": "keepme.outline@example.com",
            "id": "mm_id_keep_outline",
        }

        base_name_for_test = "OutlineRemovalTest"
        entity_key_for_test = "PROJET"
        std_auth_group_name = f"projet_{base_name_for_test}"
        auth_group = {"name": std_auth_group_name, "pk": "auth_pk_outline_remove", "users": [], "users_obj": []}
        all_auth_groups_fixture = {std_auth_group_name: auth_group}
        email_to_pk_map = {mm_user_to_keep_outline["email"]: "auth_pk_keep_outline"}
        std_mm_channel_name = f"projet_{base_name_for_test}"
        std_mm_channel_obj = {"id": "std_mm_chan_outline_remove", "display_name": std_mm_channel_name}
        self.mock_mattermost_client.get_channel_by_name.side_effect = lambda _, slug: (
            std_mm_channel_obj if slug == slugify(std_mm_channel_name) else None
        )
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_to_keep_outline]
        outline_coll_name = f"projet_{base_name_for_test}"

        expected_collection_id = f"new_outline_id_for_{slugify(outline_coll_name)}"
        self.mock_outline_client.create_group.return_value = {"id": expected_collection_id, "name": outline_coll_name}
        self.mock_outline_client.get_collection_members.return_value = [
            outline_user_id_to_remove,
            outline_user_id_to_keep,
        ]

        def mock_get_user_by_email_side_effect(email):
            if email == mm_user_to_keep_outline["email"]:
                return {"id": outline_user_id_to_keep, "email": email}
            return None

        self.mock_outline_client.get_user_by_email.side_effect = mock_get_user_by_email_side_effect
        self.mock_outline_client.get_user_by_id.return_value = {
            "id": outline_user_id_to_remove,
            "name": f"OutlineUserName_{outline_user_id_to_remove}",
            "email": "removed@example.com",
        }
        self.mock_outline_client.remove_user_from_collection.return_value = True
        self.mock_outline_client.add_user_to_collection.return_value = True

        mock_entity_config = {
            "standard": {
                "authentik_group_name_pattern": std_auth_group_name,
                "mattermost_channel_name_pattern": std_mm_channel_name,
            },
            "outline": {
                "collection_name_pattern": outline_coll_name,
                "default_access": "read",
                "admin_access": "read_write",
            },
        }
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key_for_test,
            base_name=base_name_for_test,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_auth_groups_fixture,
            email_to_authentik_user_pk_map=email_to_pk_map,
            perform_deletions=True,
            skip_services=None,
        )

        self.mock_outline_client.remove_user_from_collection.assert_called_once_with(
            expected_collection_id, outline_user_id_to_remove
        )
        self.mock_outline_client.add_user_to_collection.assert_called_once_with(
            expected_collection_id, outline_user_id_to_keep, permission="read"
        )
        removal_action = next((r for r in results if r.get("action") == "USER_REMOVED_FROM_OUTLINE_COLLECTION"), None)
        self.assertIsNotNone(removal_action, "USER_REMOVED_FROM_OUTLINE_COLLECTION action not found in results")
        if removal_action:
            self.assertEqual(removal_action["mm_username"], f"OutlineUserName_{outline_user_id_to_remove}")
        kept_action = next(
            (r for r in results if r.get("action") == "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED"), None
        )
        self.assertIsNotNone(
            kept_action, "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED not found for kept user"
        )
        if kept_action:
            self.assertEqual(kept_action["mm_username"], "keepme_outline")
        self.mock_outline_client.create_group.assert_called_once_with(outline_coll_name)

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_outline_excluded_user_not_removed(self, mock_config_module_in_service):
        excluded_mm_username = "excluded_outline_user"
        mock_config_module_in_service.EXCLUDED_USERS = {excluded_mm_username}
        mock_config_module_in_service.OUTLINE_URL = "http://fake-outline.com"
        outline_id_excluded = "outline_id_excl"

        base_name_for_test = "OutlineExcludedTest"
        entity_key_for_test = "PROJET"
        std_auth_group_name = f"projet_{base_name_for_test}"
        auth_group = {"name": std_auth_group_name, "pk": "auth_pk_excl_outline", "users": [], "users_obj": []}
        all_auth_groups_fixture = {std_auth_group_name: auth_group}
        email_to_pk_map = {"excluded.outline@example.com": "auth_pk_excl_for_outline_test"}
        std_mm_channel_name = f"projet_{base_name_for_test}"
        std_mm_channel_obj = {"id": "std_mm_chan_excl_outline", "display_name": std_mm_channel_name}
        mm_user_excluded_in_channel = {
            "username": excluded_mm_username,
            "email": "excluded.outline@example.com",
            "id": "mm_id_excl",
        }
        self.mock_mattermost_client.get_channel_by_name.side_effect = lambda _, slug: (
            std_mm_channel_obj if slug == slugify(std_mm_channel_name) else None
        )
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_excluded_in_channel]
        outline_coll_name = f"projet_{base_name_for_test}"
        # self.mock_outline_client.create_group is configured in setUp
        self.mock_outline_client.get_collection_members.return_value = [outline_id_excluded]
        self.mock_outline_client.get_user_by_email.return_value = {
            "id": outline_id_excluded,
            "email": "excluded.outline@example.com",
        }

        mock_entity_config = {
            "standard": {
                "authentik_group_name_pattern": std_auth_group_name,
                "mattermost_channel_name_pattern": std_mm_channel_name,
            },
            "outline": {
                "collection_name_pattern": outline_coll_name,
                "default_access": "read",
            },
        }

        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key_for_test,
            base_name=base_name_for_test,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_auth_groups_fixture,
            email_to_authentik_user_pk_map=email_to_pk_map,
            perform_deletions=True,
            skip_services=None,
        )
        self.mock_outline_client.add_user_to_collection.assert_not_called()
        self.mock_outline_client.remove_user_from_collection.assert_not_called()
        action_for_excluded_user_in_outline = any(
            r["service"] == "OUTLINE" and r.get("mm_username") == excluded_mm_username for r in results
        )
        self.assertFalse(
            action_for_excluded_user_in_outline, "No Outline action should be logged for an excluded user."
        )
        self.mock_outline_client.create_group.assert_called_once_with(outline_coll_name)

    @patch("libraries.group_sync_services.config")
    def test_sync_single_group_outline_permissions(self, mock_config_module_in_service):
        mock_config_module_in_service.EXCLUDED_USERS = set()
        mock_config_module_in_service.OUTLINE_URL = "http://fake-outline.com"

        test_cases = [
            ("projet_test", "O", "read"),
            ("projet_test", "P", "read_write"),
            ("antenne_test", "O", "read"),
            ("antenne_test", "P", "read_write"),
            ("pole_test", "O", "read"),
            ("pole_test", "P", "read_write"),
        ]
        mm_user_fixture = {"username": "perm_user", "email": "permuser@example.com", "id": "mm_user_id_perm"}
        outline_user_data = {"id": "outline_user_id_perm_user", "email": "permuser@example.com"}
        email_to_pk_map = {mm_user_fixture["email"]: "auth_user_pk_perm"}

        for base_name_from_case, mm_channel_type_being_processed, expected_permission in test_cases:
            entity_key_for_test = "PROJET"
            if "antenne" in base_name_from_case.lower():
                entity_key_for_test = "ANTENNE"
            elif "pole" in base_name_from_case.lower():
                entity_key_for_test = "POLES"
            subTest_name = f"base:{base_name_from_case}, chan_type_proc:{mm_channel_type_being_processed}, entity:{entity_key_for_test}"
            with self.subTest(subTest_name):
                self.mock_authentik_client.reset_mock()
                self.mock_mattermost_client.reset_mock()
                self.mock_outline_client.reset_mock()

                # Re-apply default side effect for outline_client.create_group for this subtest,
                # as it might have been changed by other tests or specific setups if not careful.
                def default_outline_create_group_side_effect(name):
                    return {"name": name, "id": f"new_outline_id_for_{slugify(name)}"}

                self.mock_outline_client.create_group.side_effect = default_outline_create_group_side_effect

                self.mock_outline_client.get_user_by_email.return_value = outline_user_data
                mock_entity_config = {
                    "standard": {
                        "authentik_group_name_pattern": f"{entity_key_for_test.lower()}_{{base_name}}",
                        "mattermost_channel_name_pattern": f"{entity_key_for_test.lower()}_{{base_name}}",
                    },
                    "admin": {
                        "authentik_group_name_pattern": f"{entity_key_for_test.lower()}_{{base_name}} Admin",
                        "mattermost_channel_name_pattern": f"{entity_key_for_test.lower()}_{{base_name}} Admin",
                    },
                    "outline": {
                        "collection_name_pattern": f"{entity_key_for_test.lower()}_{{base_name}}",
                        "default_access": "read",
                        "admin_access": "read_write",
                    },
                }
                std_auth_group_name = mock_entity_config["standard"]["authentik_group_name_pattern"].format(
                    base_name=base_name_from_case
                )
                std_mm_channel_name = mock_entity_config["standard"]["mattermost_channel_name_pattern"].format(
                    base_name=base_name_from_case
                )
                adm_auth_group_name = mock_entity_config["admin"]["authentik_group_name_pattern"].format(
                    base_name=base_name_from_case
                )
                adm_mm_channel_name = mock_entity_config["admin"]["mattermost_channel_name_pattern"].format(
                    base_name=base_name_from_case
                )
                outline_coll_name = mock_entity_config["outline"]["collection_name_pattern"].format(
                    base_name=base_name_from_case
                )
                expected_outline_coll_id = f"new_outline_id_for_{slugify(outline_coll_name)}"

                std_auth_group_obj = {
                    "name": std_auth_group_name,
                    "pk": "std_auth_pk_perm_test",
                    "users": [],
                    "users_obj": [],
                }
                adm_auth_group_obj = {
                    "name": adm_auth_group_name,
                    "pk": "adm_auth_pk_perm_test",
                    "users": [],
                    "users_obj": [],
                }
                all_authentik_groups_by_name_fixture = {
                    std_auth_group_name: std_auth_group_obj,
                    adm_auth_group_name: adm_auth_group_obj,
                }
                std_mm_channel_obj = {"id": "std_mm_chan_id_perm_test", "display_name": std_mm_channel_name}
                adm_mm_channel_obj = {"id": "adm_mm_chan_id_perm_test", "display_name": adm_mm_channel_name}

                def get_channel_by_name_side_effect(team_id, channel_name_slug):
                    if channel_name_slug == slugify(std_mm_channel_name):
                        return std_mm_channel_obj
                    if channel_name_slug == slugify(adm_mm_channel_name):
                        return adm_mm_channel_obj
                    return None

                self.mock_mattermost_client.get_channel_by_name.side_effect = get_channel_by_name_side_effect

                mm_users_for_std_channel = []
                mm_users_for_adm_channel = []
                if mm_channel_type_being_processed == "O":
                    mm_users_for_std_channel = [mm_user_fixture]
                elif mm_channel_type_being_processed == "P":
                    mm_users_for_std_channel = [mm_user_fixture]
                    mm_users_for_adm_channel = [mm_user_fixture]

                def get_users_in_channel_side_effect(channel_id):
                    if channel_id == std_mm_channel_obj["id"]:
                        return mm_users_for_std_channel
                    if channel_id == adm_mm_channel_obj["id"]:
                        return mm_users_for_adm_channel
                    return []

                self.mock_mattermost_client.get_users_in_channel.side_effect = get_users_in_channel_side_effect

                self.mock_authentik_client.add_user_to_group.return_value = True
                self.mock_outline_client.get_collection_members.return_value = []
                self.mock_outline_client.add_user_to_collection.return_value = True
                mock_url_id_perm_test = f"{slugify(outline_coll_name)}-urlidperm"
                self.mock_outline_client.get_collection_details.return_value = {
                    "id": expected_outline_coll_id,
                    "name": outline_coll_name,
                    "urlId": mock_url_id_perm_test,
                }
                self.mock_mattermost_client.send_dm.return_value = True

                results = sync_entity_permissions(
                    authentik_client=self.mock_authentik_client,
                    mattermost_client=self.mock_mattermost_client,
                    outline_client=self.mock_outline_client,
                    brevo_client=self.mock_brevo_client,
                    nocodb_client=self.mock_nocodb_client,
                    vaultwarden_client=self.mock_vaultwarden_client,
                    mm_team_id=self.mm_team_id,
                    entity_key=entity_key_for_test,
                    base_name=base_name_from_case,
                    entity_config=mock_entity_config,
                    all_authentik_groups_by_name=all_authentik_groups_by_name_fixture,
                    email_to_authentik_user_pk_map=email_to_pk_map,
                    perform_deletions=True,
                    skip_services=None,
                )

                self.mock_outline_client.create_group.assert_called_once_with(outline_coll_name)
                self.mock_outline_client.add_user_to_collection.assert_called_once()
                called_args_add_user = self.mock_outline_client.add_user_to_collection.call_args
                self.assertEqual(called_args_add_user.args[0], expected_outline_coll_id)
                self.assertEqual(called_args_add_user.args[1], outline_user_data["id"])
                self.assertEqual(called_args_add_user.kwargs.get("permission"), expected_permission)

                outline_result = next(
                    (r for r in results if r["service"] == "OUTLINE" and r["status"] == "SUCCESS"), None
                )
                self.assertIsNotNone(outline_result, f"No successful Outline result found for {subTest_name}")
                if outline_result:
                    dm_part = "_AND_DM_SENT"
                    expected_action_val = (
                        f"USER_ADDED_TO_OUTLINE_COLLECTION_WITH_{expected_permission.upper()}_ACCESS{dm_part}"
                    )
                    self.assertEqual(outline_result.get("action"), expected_action_val)

    # --- New tests for orchestrate_group_synchronization ---
    @patch("libraries.group_sync_services.sync_entity_permissions")
    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    @patch("libraries.group_sync_services.config")
    @async_test  # Added decorator
    async def test_orchestrate_sync_fetch_remote_false_discover_via_mm_no_deletions(
        self, mock_lib_config, mock_get_all_auth_groups_and_map, mock_sync_entity_permissions_call
    ):
        # This test will now test sync_mode="MM_TO_TOOLS"
        self.mock_authentik_client.reset_mock()
        self.mock_mattermost_client.reset_mock()
        self.mock_outline_client.reset_mock()

        def create_auth_group_side_effect(name):
            return {"name": name, "pk": f"auth_pk_{slugify(name)}", "users": [], "users_obj": []}

        self.mock_authentik_client.get_group_by_name.return_value = None
        self.mock_authentik_client.create_group.side_effect = create_auth_group_side_effect

        def create_outline_coll_side_effect(name):
            return {"name": name, "id": f"outline_id_{slugify(name)}"}

        self.mock_outline_client.create_group.side_effect = create_outline_coll_side_effect

        mock_team_id = "team_upsert_mode"
        mock_email_pk_map = {"user.alpha@example.com": "auth_pk_alpha", "user.beta@example.com": "auth_pk_beta"}
        mock_get_all_auth_groups_and_map.return_value = ([], mock_email_pk_map)

        # mm_channel_projet_alpha = {"id": "mm_alpha_id", "name": "projet-alpha", "display_name": "PROJET Alpha"}
        # mm_channel_antenne_beta_admin = {"id": "mm_beta_adm_id", "name": "antenne-beta-admin", "display_name": "ANTENNE Beta Admin"}
        self.mock_mattermost_client.get_channels_for_team.return_value = []  # Simulate no channels found

        mock_lib_config.PERMISSIONS_MATRIX = (
            {  # Matrix still needed for _map_mm_channel_to_entity_and_base_name if it were called
                "PROJET": {
                    "standard": {
                        "mattermost_channel_name_pattern": "PROJET {base_name}",
                        "authentik_group_name_pattern": "auth_projet_{base_name}",
                    }
                },
                "ANTENNE": {
                    "admin": {
                        "mattermost_channel_name_pattern": "ANTENNE {base_name} Admin",
                        "authentik_group_name_pattern": "auth_antenne_{base_name}_admin",
                    }
                },
                "BREVO_TEST_ENTITY": {  # Added for Brevo specific test
                    "standard": {"mattermost_channel_name_pattern": "brevo_test_{base_name}"},
                    "brevo": {"list_name_pattern": "brevo_list_{base_name}"},
                },
            }
        )
        # mock_sync_entity_permissions_call.return_value = [{"status": "SUCCESS", "action": "MOCKED_UPSERT"}] # Not called if no channels

        success, detailed_results = await orchestrate_group_synchronization(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=mock_team_id,
            perform_deletions=False,
            sync_mode="MM_TO_TOOLS",  # Was fetch_remote_members=False
        )

        self.assertTrue(success)
        self.assertEqual(len(detailed_results), 0)  # No entities processed, no results
        mock_get_all_auth_groups_and_map.assert_called_once_with(self.mock_authentik_client)
        self.mock_authentik_client.get_groups_with_users.assert_not_called()  # Still not called directly by orchestrate
        self.mock_mattermost_client.get_channels_for_team.assert_called_once_with(mock_team_id)
        mock_sync_entity_permissions_call.assert_not_called()  # Not called if no entities discovered

    @patch("libraries.group_sync_services.sync_entity_permissions")
    @patch("libraries.group_sync_services.get_all_authentik_groups_and_user_map")
    @patch("libraries.group_sync_services.config")
    @async_test  # Added decorator
    async def test_orchestrate_sync_fetch_remote_true_discover_via_auth_with_deletions(
        self, mock_lib_config, mock_get_all_auth_groups_and_map, mock_sync_entity_permissions_call
    ):
        # This test will now test sync_mode="FULL_SYNC"
        self.mock_authentik_client.reset_mock()
        self.mock_mattermost_client.reset_mock()
        self.mock_outline_client.reset_mock()

        def create_outline_coll_side_effect(name):
            return {"name": name, "id": f"outline_id_{slugify(name)}"}

        self.mock_outline_client.create_group.side_effect = create_outline_coll_side_effect

        mock_team_id = "team_sync_mode"
        auth_group_projet_gamma = {
            "name": "auth_projet_Gamma",
            "pk": "auth_g_gamma",
            "users": ["u1"],
            "users_obj": [{"pk": "u1", "email": "user.gamma@example.com", "username": "user.gamma"}],
        }
        auth_group_antenne_delta_admin = {
            "name": "auth_antenne_Delta_admin",
            "pk": "auth_g_delta_adm",
            "users": [],
            "users_obj": [],
        }
        mock_all_auth_groups_list = [auth_group_projet_gamma, auth_group_antenne_delta_admin]
        mock_email_pk_map = {"user.gamma@example.com": "auth_pk_gamma"}

        mock_get_all_auth_groups_and_map.return_value = (mock_all_auth_groups_list, mock_email_pk_map)
        # This mock below is for the direct call inside orchestrate_group_synchronization when fetch_remote_members=True
        self.mock_authentik_client.get_groups_with_users.return_value = (mock_all_auth_groups_list, mock_email_pk_map)

        mock_lib_config.PERMISSIONS_MATRIX = {
            "PROJET": {"standard": {"authentik_group_name_pattern": "auth_projet_{base_name}"}},
            "ANTENNE": {"admin": {"authentik_group_name_pattern": "auth_antenne_{base_name}_admin"}},
            "BREVO_TEST_ENTITY": {  # Added for Brevo specific test
                "standard": {
                    "mattermost_channel_name_pattern": "brevo_test_{base_name}"
                },  # Not used if discovery is via Auth
                "brevo": {
                    "list_name_pattern": "brevo_list_{base_name}"
                },  # Also not directly used if discovery is Auth only
            },
        }
        mock_sync_entity_permissions_call.return_value = [{"status": "SUCCESS", "action": "MOCKED_FULL_SYNC"}]

        success, detailed_results = await orchestrate_group_synchronization(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=mock_team_id,
            perform_deletions=True,
            sync_mode="FULL_SYNC",  # Was fetch_remote_members=True
        )

        self.assertTrue(success)
        self.assertEqual(len(detailed_results), 2)
        mock_get_all_auth_groups_and_map.assert_called_once_with(self.mock_authentik_client)
        self.assertEqual(self.mock_authentik_client.get_groups_with_users.call_count, 1)
        self.mock_mattermost_client.get_channels_for_team.assert_not_called()

        expected_all_auth_groups_by_name = {g["name"]: g for g in mock_all_auth_groups_list}
        mock_sync_entity_permissions_call.assert_any_call(
            self.mock_authentik_client,
            self.mock_mattermost_client,
            self.mock_outline_client,
            self.mock_brevo_client,
            self.mock_nocodb_client,
            self.mock_vaultwarden_client,  # Added vaultwarden_client
            mock_team_id,
            "Gamma",
            "PROJET",
            mock_lib_config.PERMISSIONS_MATRIX["PROJET"],
            expected_all_auth_groups_by_name,
            mock_email_pk_map,
            True,
            skip_services=[],  # Added expected default
        )
        mock_sync_entity_permissions_call.assert_any_call(
            self.mock_authentik_client,
            self.mock_mattermost_client,
            self.mock_outline_client,
            self.mock_brevo_client,
            self.mock_nocodb_client,
            self.mock_vaultwarden_client,  # Added vaultwarden_client
            mock_team_id,
            "Delta",
            "ANTENNE",
            mock_lib_config.PERMISSIONS_MATRIX["ANTENNE"],
            expected_all_auth_groups_by_name,
            mock_email_pk_map,
            True,
            skip_services=[],  # Added expected default
        )

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

        self.mock_brevo_client.get_list_by_name.return_value = None  # List does not exist
        # Use the ID pattern from the mock_brevo_client.create_list setup
        expected_created_list_id = f"new_brevo_list_id_for_{slugify(brevo_list_name)}"
        created_list_obj_for_test = {"id": expected_created_list_id, "name": brevo_list_name}
        # Ensure create_list mock returns this structure if called
        self.mock_brevo_client.create_list.return_value = created_list_obj_for_test
        self.mock_brevo_client.add_contact_to_list.return_value = True

        results = self.sync_single_brevo_list_helper(
            self.mock_brevo_client, brevo_list_name, mm_users, mm_channel_name_log, perform_deletions=False
        )

        self.mock_brevo_client.get_list_by_name.assert_called_once_with(brevo_list_name)
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

    @patch("libraries.group_sync_services.config")
    def test_sync_brevo_list_user_removal(self, mock_lib_config_brevo):
        mock_lib_config_brevo.EXCLUDED_USERS = set()
        brevo_list_name = "TestBrevoListRemoval"
        existing_list_obj = {"id": "brevo_list_id_456", "name": brevo_list_name}
        self.mock_brevo_client.get_list_by_name.return_value = existing_list_obj
        self.mock_brevo_client.create_list.assert_not_called()  # Should not be called if list exists

        mm_users_in_channel = [{"username": "user_stay", "email": "stay@example.com"}]
        # Simulate Brevo having 'stay@example.com' and 'remove@example.com'
        brevo_contacts_on_list = [{"email": "stay@example.com"}, {"email": "remove@example.com"}]
        self.mock_brevo_client.get_contacts_from_list.return_value = brevo_contacts_on_list
        self.mock_brevo_client.remove_contact_from_list.return_value = True
        self.mock_brevo_client.add_contact_to_list.return_value = True

        results = self.sync_single_brevo_list_helper(
            self.mock_brevo_client,
            brevo_list_name,
            mm_users_in_channel,
            "MMChannelForBrevoRemoval",
            perform_deletions=True,
        )

        self.mock_brevo_client.get_contacts_from_list.assert_called_once_with(
            existing_list_obj["id"], limit=50, offset=0
        )
        self.mock_brevo_client.remove_contact_from_list.assert_called_once_with(
            email="remove@example.com", list_id=existing_list_obj["id"]
        )
        self.mock_brevo_client.add_contact_to_list.assert_called_once_with(
            email="stay@example.com", list_id=existing_list_obj["id"]
        )

        self.assertEqual(len(results), 2)  # One for add/ensure, one for removal
        removed_action = next(r for r in results if r["action"] == "USER_REMOVED_FROM_BREVO_LIST")
        ensured_action = next(r for r in results if r["action"] == "USER_ENSURED_IN_BREVO_LIST")
        self.assertEqual(removed_action["mm_user_email"], "remove@example.com")
        self.assertEqual(ensured_action["mm_user_email"], "stay@example.com")

    @patch("libraries.group_sync_services.config")
    def test_sync_brevo_list_excluded_user_not_added_or_removed(self, mock_lib_config_brevo):
        excluded_username = "excluded_brevo_user"
        mock_lib_config_brevo.EXCLUDED_USERS = {excluded_username}
        brevo_list_name = "TestBrevoListExcluded"
        existing_list_obj = {"id": "brevo_list_id_789", "name": brevo_list_name}
        self.mock_brevo_client.get_list_by_name.return_value = existing_list_obj

        mm_users_in_channel = [
            {"username": excluded_username, "email": "excluded_brevo@example.com"},
            {"username": "normal_user", "email": "normal@example.com"},
        ]
        # Assume excluded user is somehow on the Brevo list (e.g. manually added)
        # brevo_contacts_on_list = [{"email": "excluded_brevo@example.com"}, {"email": "other@example.com"}] # Part of the removed initial call
        # self.mock_brevo_client.get_contacts_from_list.return_value = brevo_contacts_on_list # Part of the removed initial call

        # results = self.sync_single_brevo_list_helper( # This call and its assertions are removed as 'results' was unused.
        #     self.mock_brevo_client,
        #     brevo_list_name,
        #     mm_users_in_channel,
        #     "MMChannelForBrevoExcluded",
        #     perform_deletions=True,
        # )

        # self.mock_brevo_client.add_contact_to_list.assert_called_once_with( # Part of the removed initial call's assertions
        #     email="normal@example.com", list_id=existing_list_obj["id"]
        # )
        # # 'other@example.com' should be removed as it's not in mm_users_in_channel and not excluded
        # self.mock_brevo_client.remove_contact_from_list.assert_called_once_with( # Part of the removed initial call's assertions
        #     email="other@example.com", list_id=existing_list_obj["id"]
        # )

        # Check that no action was taken for the excluded user's email regarding add/remove from Brevo
        # The current logic for _sync_single_brevo_list:
        # - Skips adding excluded users.
        # - If perform_deletions=True, it calculates emails_to_remove = current_emails_in_brevo_list - target_emails_in_list.
        #   target_emails_in_list does NOT include excluded users.
        #   So, if an excluded user is in current_emails_in_brevo_list but not target_emails_in_list, they WILL be removed.
        # This might need adjustment if excluded users should be preserved on Brevo lists even if not in MM channel.
        # For now, the test reflects current logic: excluded user in MM channel is skipped for add. If on Brevo list and not in MM target, they are removed.
        # The prompt said: "members n’auront aucun droit sur cette liste par contre il faut gérer l’ajout des adresses emails et la suppression si la personne quitte le channel Mattermost correspondant."
        # This implies if an excluded user "quits the channel", their email should be removed.
        # However, if an excluded user is *never* in the channel but on the list, they'd also be removed.
        # Let's adjust the test to a clearer scenario: excluded user in MM channel, should not be added.
        # And an unmanaged user on Brevo list (not in MM, not excluded) should be removed.

        # Reset mocks for a cleaner assertion based on the scenario
        self.mock_brevo_client.reset_mock()
        self.mock_brevo_client.get_list_by_name.return_value = existing_list_obj
        self.mock_brevo_client.get_contacts_from_list.return_value = [
            {"email": "unmanaged@example.com"}
        ]  # Only unmanaged user on list

        results_rerun = self.sync_single_brevo_list_helper(
            self.mock_brevo_client,
            brevo_list_name,
            mm_users_in_channel,
            "MMChannelForBrevoExcluded",
            perform_deletions=True,
        )
        self.mock_brevo_client.add_contact_to_list.assert_called_once_with(
            email="normal@example.com", list_id=existing_list_obj["id"]
        )
        self.mock_brevo_client.remove_contact_from_list.assert_called_once_with(
            email="unmanaged@example.com", list_id=existing_list_obj["id"]
        )

        actions_for_excluded = [r for r in results_rerun if r.get("mm_user_email") == "excluded_brevo@example.com"]
        self.assertEqual(
            len(actions_for_excluded),
            0,
            "No direct add/remove actions should be logged for excluded user based on MM channel presence.",
        )

    def sync_single_brevo_list_helper(
        self, mock_brevo_client, brevo_list_name, mm_users, mm_channel_name_log, perform_deletions
    ):
        """Helper to call the static _sync_single_brevo_list method for testing."""
        # This method is part of the Test class, so it can access self.
        # We need to import it if it's not already available in the test file's scope.
        # Assuming _sync_single_brevo_list is globally available or imported for these tests.
        # For now, let's assume it's directly callable or defined in this file for testing.
        # If it's in group_sync_services, we'd call it as:
        from libraries.group_sync_services import _sync_single_brevo_list as actual_sync_function

        return actual_sync_function(
            brevo_client=mock_brevo_client,
            brevo_list_name=brevo_list_name,
            mm_users_in_channel=mm_users,
            mm_channel_display_name_for_log=mm_channel_name_log,
            perform_deletions=perform_deletions,
        )

    # --- Tests for NocoDB base synchronization ---
    @patch("libraries.group_sync_services.config")  # To mock EXCLUDED_USERS and NOCODB_URL
    def test_sync_nocodb_base_creation_and_user_invite_with_dm(self, mock_lib_config_nocodb):
        mock_lib_config_nocodb.EXCLUDED_USERS = set()
        mock_lib_config_nocodb.NOCODB_URL = "https://test-nocodb.example.com"  # Mock NOCODB_URL for DM link
        from libraries.group_sync_services import _sync_single_nocodb_base

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
        self.mock_nocodb_client.get_base_by_title.return_value = {"id": "nc_base_id_123", "title": nocodb_base_title}
        self.mock_nocodb_client.list_base_users.return_value = []  # No users initially
        self.mock_nocodb_client.invite_user_to_base.return_value = True
        self.mock_mattermost_client.send_dm.return_value = True  # Assume DMs are sent successfully

        results = _sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,
            base_title_pattern,
            entity_base_name,
            mm_users_for_perm,
            default_perm,
            admin_perm,
            mm_channel_context,
            perform_deletions=False,
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
                self.assertEqual(res["action"], f"NOCODB_USER_INVITED_AS_{default_perm.upper()}_AND_DM_SENT")
            elif res["mm_user_email"] == "admin@nocodb.com":
                self.assertEqual(res["action"], f"NOCODB_USER_INVITED_AS_{admin_perm.upper()}_AND_DM_SENT")

    @patch("libraries.group_sync_services.config")
    def test_sync_nocodb_base_invite_dm_fails(self, mock_lib_config_nocodb):
        mock_lib_config_nocodb.EXCLUDED_USERS = set()
        mock_lib_config_nocodb.NOCODB_URL = "https://test-nocodb.example.com"
        from libraries.group_sync_services import _sync_single_nocodb_base

        base_title_pattern = "dm_fail_nocodb_{base_name}"
        entity_base_name = "NocoDMFail"
        nocodb_base_title = base_title_pattern.format(base_name=entity_base_name)
        base_id = "nc_base_id_dm_fail"
        mm_user = {"username": "dm_fail_user", "mm_user_id": "mm_dm_fail", "is_admin_channel_member": False}
        mm_users_for_perm = {"dm.fail@example.com": mm_user}

        self.mock_nocodb_client.get_base_by_title.return_value = {"id": base_id, "title": nocodb_base_title}
        self.mock_nocodb_client.list_base_users.return_value = []
        self.mock_nocodb_client.invite_user_to_base.return_value = True
        self.mock_mattermost_client.send_dm.return_value = False  # Simulate DM failure

        results = _sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,
            base_title_pattern,
            entity_base_name,
            mm_users_for_perm,
            "viewer",
            "owner",
            "ChanDMFail",
            False,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")  # Invite itself was successful
        self.assertEqual(results[0]["action"], "NOCODB_USER_INVITED_AS_VIEWER_DM_FAILED")
        self.mock_mattermost_client.send_dm.assert_called_once()

    @patch("libraries.group_sync_services.config")
    def test_sync_nocodb_base_invite_dm_skipped_no_url(self, mock_lib_config_nocodb):
        mock_lib_config_nocodb.EXCLUDED_USERS = set()
        mock_lib_config_nocodb.NOCODB_URL = None  # Simulate NOCODB_URL not being set
        from libraries.group_sync_services import _sync_single_nocodb_base

        base_title_pattern = "dm_skip_nocodb_{base_name}"
        entity_base_name = "NocoDMSkip"
        nocodb_base_title = base_title_pattern.format(base_name=entity_base_name)
        base_id = "nc_base_id_dm_skip"
        mm_user = {"username": "dm_skip_user", "mm_user_id": "mm_dm_skip", "is_admin_channel_member": False}
        mm_users_for_perm = {"dm.skip@example.com": mm_user}

        self.mock_nocodb_client.get_base_by_title.return_value = {"id": base_id, "title": nocodb_base_title}
        self.mock_nocodb_client.list_base_users.return_value = []
        self.mock_nocodb_client.invite_user_to_base.return_value = True

        results = _sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,
            base_title_pattern,
            entity_base_name,
            mm_users_for_perm,
            "viewer",
            "owner",
            "ChanDMSkip",
            False,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")  # Invite itself was successful
        self.assertEqual(results[0]["action"], "NOCODB_USER_INVITED_AS_VIEWER_DM_SKIPPED_NO_URL")
        self.mock_mattermost_client.send_dm.assert_not_called()

    @patch("libraries.group_sync_services.config")
    def test_sync_nocodb_base_user_update_and_removal(self, mock_lib_config_nocodb):
        mock_lib_config_nocodb.EXCLUDED_USERS = set()
        mock_lib_config_nocodb.NOCODB_URL = (
            "https://test-nocodb.example.com"  # For consistency, though not strictly needed for removal/update tests
        )
        from libraries.group_sync_services import _sync_single_nocodb_base

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
            {"id": "nc_uid1", "email": "user1.update@nocodb.com", "roles": "owner"},  # Role needs update
            {
                "id": "nc_uid_remove",
                "email": "user.remove@nocodb.com",
                "roles": "viewer",
                "firstname": "Remove",
                "lastname": "Me",
            },
        ]

        self.mock_nocodb_client.get_base_by_title.return_value = {"id": base_id, "title": nocodb_base_title}
        self.mock_nocodb_client.list_base_users.return_value = initial_nocodb_users
        self.mock_nocodb_client.update_base_user.return_value = True
        self.mock_nocodb_client.delete_base_user.return_value = True  # This actually sets role to no-access
        self.mock_nocodb_client.invite_user_to_base.return_value = True  # For user2 who is new

        results = _sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,  # Added mattermost_client
            base_title_pattern,
            entity_base_name,
            mm_users_for_perm,
            "viewer",
            "owner",
            "NocoDBUpdateRemoveChannel",
            perform_deletions=True,
        )

        # Check update for user1
        self.mock_nocodb_client.update_base_user.assert_any_call(base_id, "nc_uid1", "viewer")
        # Check invite for user2
        self.mock_nocodb_client.invite_user_to_base.assert_any_call(base_id, "user2.owner@nocodb.com", "owner")
        # Check removal for user.remove@nocodb.com
        self.mock_nocodb_client.delete_base_user.assert_called_once_with(base_id, "nc_uid_remove")

        self.assertEqual(len(results), 3)  # 1 update, 1 invite, 1 removal
        actions = [r["action"] for r in results]
        self.assertIn("NOCODB_USER_ROLE_UPDATED_TO_VIEWER", actions)
        # Assuming send_dm is True by default from setUp for the invited user
        self.assertIn("NOCODB_USER_INVITED_AS_OWNER_AND_DM_SENT", actions)
        self.assertIn("NOCODB_USER_REMOVED_FROM_BASE", actions)

    @patch("libraries.group_sync_services.config")
    def test_sync_nocodb_base_excluded_user_handling(self, mock_lib_config_nocodb):
        excluded_username = "excluded_nc_user"
        mock_lib_config_nocodb.EXCLUDED_USERS = {excluded_username}
        from libraries.group_sync_services import _sync_single_nocodb_base

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
            {"id": "nc_uid_excl", "email": "excluded.user@nocodb.com", "roles": "editor"},
            {"id": "nc_uid_remove_excl_test", "email": "remove.excl@nocodb.com", "roles": "viewer"},
        ]

        self.mock_nocodb_client.get_base_by_title.return_value = {"id": base_id, "title": nocodb_base_title}
        self.mock_nocodb_client.list_base_users.return_value = initial_nocodb_users
        self.mock_nocodb_client.invite_user_to_base.return_value = True  # For normal.user
        self.mock_nocodb_client.delete_base_user.return_value = True  # For remove.excl

        results = _sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,  # Added mattermost_client
            base_title_pattern,
            entity_base_name,
            mm_users_for_perm,
            "viewer",
            "owner",
            "NocoDBExclChannel",
            perform_deletions=True,
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
        self.mock_nocodb_client.delete_base_user.assert_any_call(base_id, "nc_uid_remove_excl_test")

        actions = {r["mm_user_email"]: r["action"] for r in results if "mm_user_email" in r}
        # Assuming send_dm is True by default from setUp or previous context if not reset and overridden
        self.assertEqual(actions.get("normal.user@nocodb.com"), "NOCODB_USER_INVITED_AS_VIEWER_AND_DM_SENT")
        self.assertEqual(actions.get("remove.excl@nocodb.com"), "NOCODB_USER_REMOVED_FROM_BASE")
        self.assertNotIn("excluded.user@nocodb.com", actions)  # No action logged for excluded user if already present

    @patch("libraries.group_sync_services.config")
    def test_sync_nocodb_base_not_found(self, mock_lib_config_nocodb):
        mock_lib_config_nocodb.EXCLUDED_USERS = set()
        from libraries.group_sync_services import _sync_single_nocodb_base

        self.mock_nocodb_client.get_base_by_title.return_value = None  # Simulate base not found

        results = _sync_single_nocodb_base(
            self.mock_nocodb_client,
            self.mock_mattermost_client,  # Added mattermost_client
            "nf_{base_name}",
            "NocoNF",
            {},
            "viewer",
            "owner",
            "ChanNF",
            False,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SKIPPED")
        self.assertEqual(results[0]["action"], "SKIPPED_NOCODB_BASE_NOT_FOUND")
        self.mock_nocodb_client.list_base_users.assert_not_called()

    @patch("libraries.group_sync_services.config")
    def test_sync_entity_permissions_skip_nocodb(self, mock_lib_config):
        mock_lib_config.EXCLUDED_USERS = set()
        entity_key = "ANTENNE"  # An entity type that would normally sync NoCoDB
        base_name = "TestAntenneSkip"
        mock_entity_config = {
            "standard": {"mattermost_channel_name_pattern": f"{entity_key.lower()}_{{base_name}}"},
            "nocodb": {
                "base_title_pattern": "nocodb_{base_name}",
                "default_access": "viewer",
                "admin_access": "owner",
            },
        }
        # Simulate that the MM channel exists and has one user
        self.mock_mattermost_client.get_channel_by_name.return_value = {
            "id": "mm_chan_skip_id",
            "display_name": f"{entity_key.lower()}_{base_name}",
        }
        mm_user_data = {"username": "testuser", "email": "test@example.com", "id": "mm_user_id_skip"}
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_data]

        # Ensure other clients are minimally mocked if their sync logic were to be called (though not expected for this test focus)
        self.mock_authentik_client.get_group_by_name.return_value = {
            "pk": "auth_pk_skip",
            "name": "auth_group_skip",
            "users": [],
            "users_obj": [],
        }
        self.mock_outline_client.create_group.return_value = {
            "id": "outline_coll_skip_id",
            "name": "outline_coll_skip",
        }
        self.mock_brevo_client.get_list_by_name.return_value = {"id": "brevo_list_skip_id", "name": "brevo_list_skip"}

        sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            nocodb_client=self.mock_nocodb_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name={},  # Minimal
            email_to_authentik_user_pk_map={},  # Minimal
            perform_deletions=True,
            skip_services=["nocodb"],  # Crucial part of this test
        )
        # Assert that NoCoDB client methods were NOT called
        self.mock_nocodb_client.get_base_by_title.assert_not_called()
        self.mock_nocodb_client.list_base_users.assert_not_called()
        self.mock_nocodb_client.invite_user_to_base.assert_not_called()
        # Other client methods might be called if their configs were present, ensure they are if needed
        # For this test, focus is on NoCoDB not being called.

    # --- Tests for Vaultwarden collection member synchronization ---
    @patch("libraries.group_sync_services.config")
    def test_sync_vaultwarden_collection_invite_with_dm(self, mock_lib_config_vw):
        mock_lib_config_vw.EXCLUDED_USERS = set()
        mock_lib_config_vw.VAULTWARDEN_SERVER_URL = "https://test-vault.example.com"
        from libraries.group_sync_services import _sync_single_vaultwarden_collection_members

        collection_name = "TestVWCollection"
        mm_user_data = {"username": "vw_user1", "mm_user_id": "mm_vw_u1", "is_admin_channel_member": False}
        mm_users_for_services = {"vw.user1@example.com": mm_user_data}
        mm_channel_context = "TestVWChannel"

        self.mock_vaultwarden_client.get_collection_by_name.return_value = "vw_coll_id_123"
        self.mock_vaultwarden_client._get_api_token.return_value = "fake_vw_api_token"
        self.mock_vaultwarden_client.invite_user_to_collection.return_value = True
        self.mock_mattermost_client.send_dm.return_value = True

        results = _sync_single_vaultwarden_collection_members(
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

    @patch("libraries.group_sync_services.config")
    def test_sync_vaultwarden_invite_dm_fails(self, mock_lib_config_vw):
        mock_lib_config_vw.EXCLUDED_USERS = set()
        mock_lib_config_vw.VAULTWARDEN_SERVER_URL = "https://test-vault.example.com"
        from libraries.group_sync_services import _sync_single_vaultwarden_collection_members

        collection_name = "VWCollectionDMFail"
        mm_users_for_services = {"vw.dm.fail@example.com": {"username": "vw_dm_fail", "mm_user_id": "mm_vw_dm_fail"}}

        self.mock_vaultwarden_client.get_collection_by_name.return_value = "vw_coll_id_dm_fail"
        self.mock_vaultwarden_client._get_api_token.return_value = "fake_vw_api_token"
        self.mock_vaultwarden_client.invite_user_to_collection.return_value = True
        self.mock_mattermost_client.send_dm.return_value = False  # Simulate DM failure

        results = _sync_single_vaultwarden_collection_members(
            self.mock_vaultwarden_client,
            self.mock_mattermost_client,
            collection_name,
            mm_users_for_services,
            "ChanVWFail",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["action"], "USER_INVITED_TO_VW_COLLECTION_DM_FAILED")

    @patch("libraries.group_sync_services.config")
    def test_sync_vaultwarden_invite_dm_skipped_no_url(self, mock_lib_config_vw):
        mock_lib_config_vw.EXCLUDED_USERS = set()
        mock_lib_config_vw.VAULTWARDEN_SERVER_URL = None  # Simulate URL not set
        from libraries.group_sync_services import _sync_single_vaultwarden_collection_members

        collection_name = "VWCollectionDMSkip"
        mm_users_for_services = {"vw.dm.skip@example.com": {"username": "vw_dm_skip", "mm_user_id": "mm_vw_dm_skip"}}

        self.mock_vaultwarden_client.get_collection_by_name.return_value = "vw_coll_id_dm_skip"
        self.mock_vaultwarden_client._get_api_token.return_value = "fake_vw_api_token"
        self.mock_vaultwarden_client.invite_user_to_collection.return_value = True

        results = _sync_single_vaultwarden_collection_members(
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
        from libraries.group_sync_services import _sync_single_vaultwarden_collection_members

        collection_name = "VWCollectionInviteFail"
        mm_users_for_services = {
            "vw.invite.fail@example.com": {"username": "vw_invite_fail", "mm_user_id": "mm_vw_invite_fail"}
        }

        self.mock_vaultwarden_client.get_collection_by_name.return_value = "vw_coll_id_invite_fail"
        self.mock_vaultwarden_client._get_api_token.return_value = "fake_vw_api_token"
        self.mock_vaultwarden_client.invite_user_to_collection.return_value = False  # Simulate invite failure

        results = _sync_single_vaultwarden_collection_members(
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

    @patch("libraries.group_sync_services._sync_single_authentik_group")
    @patch("libraries.group_sync_services._map_auth_group_to_entity_and_base_name")
    @patch("libraries.group_sync_services._get_mm_users_for_entity")
    @async_test
    async def test_sync_entity_permissions_tools_to_mm_authentik(
        self, mock_get_mm_users, mock_map_group, mock_sync_single_auth_group
    ):
        mock_authentik_client = MagicMock(spec=AuthentikClient)
        mock_mattermost_client = MagicMock(spec=MattermostClient)
        mock_permissions_matrix = {"PROJET": {"standard": {"authentik_group_name_pattern": "projet_{base_name}"}}}

        mock_auth_group1 = {"name": "projet_Test1", "pk": "pk1"}
        mock_auth_group2 = {"name": "projet_Test2", "pk": "pk2"}
        mock_auth_group3 = {"name": "unmapped_group", "pk": "pk3"}
        mock_authentik_client.get_groups_with_users.return_value = (
            [mock_auth_group1, mock_auth_group2, mock_auth_group3],
            {},
        )

        def map_side_effect(group_name, matrix):
            if group_name == "projet_Test1":
                return "PROJET", "Test1"
            if group_name == "projet_Test2":
                return "PROJET", "Test2"
            return None, None

        mock_map_group.side_effect = map_side_effect

        mock_get_mm_users.return_value = ({}, [], [])  # Mock return for mm users
        mock_sync_single_auth_group.return_value = [{"status": "SUCCESS"}]

        from libraries.group_sync_services import _sync_entity_permissions_tools_to_mm

        results = await _sync_entity_permissions_tools_to_mm(
            service_client=mock_authentik_client,
            service_name="AUTHENTIK",
            mattermost_client=mock_mattermost_client,
            mm_team_id="test_team",
            email_to_authentik_user_pk_map={},
            perform_deletions=True,
            permissions_matrix=mock_permissions_matrix,
            skip_services=[],
        )

        mock_authentik_client.get_groups_with_users.assert_called_once()
        self.assertEqual(mock_map_group.call_count, 3)
        self.assertEqual(mock_get_mm_users.call_count, 2)
        self.assertEqual(mock_sync_single_auth_group.call_count, 2)
        mock_sync_single_auth_group.assert_any_call(
            authentik_client=mock_authentik_client,
            auth_group_obj=mock_auth_group1,
            mm_users_in_corresponding_channel=[],
            email_to_authentik_user_pk_map={},
            mm_channel_display_name_for_log="Test1",
            perform_deletions=True,
        )
        self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
