import unittest
import os
from unittest.mock import patch, MagicMock, mock_open

from libraries.group_sync_services import sync_entity_permissions

from app import config as app_config
from clients.mattermost_client import slugify


def reload_config_module():
    import importlib

    importlib.reload(app_config)


class TestGroupSyncServices(unittest.TestCase):

    def setUp(self):
        app_config.EXCLUDED_USERS = set()
        self.mock_authentik_client = MagicMock()
        self.mock_mattermost_client = MagicMock()
        self.mock_outline_client = MagicMock()
        self.mm_team_id = "test_team_id"

        self.email_to_authentik_user_pk_map_fixture = {
            "user1@example.com": "auth_user_pk_1",
            "user2@example.com": "auth_user_pk_2",
            "excludeduser@example.com": "auth_user_pk_excluded",
            "marty@example.com": "auth_user_pk_marty",
        }
        # General fixture for a channel, specific tests might override display_name or id
        self.mm_channel_fixture = {
            "id": "mm_channel_id_generic",
            "display_name": "Generic Test Channel",
            "name": "generic-test-channel",
        }

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
        self.mock_outline_client.get_collection_by_name.return_value = {
            "id": "outline_coll_id_1",
            "name": outline_coll_name,
        }
        self.mock_outline_client.get_collection_members.return_value = []
        self.mock_outline_client.add_user_to_collection.return_value = True
        self.mock_outline_client.get_user_by_email.side_effect = lambda email: (
            {"id": f"outlineid_{email.split('@')[0]}"} if email else None
        )
        self.mock_outline_client.get_collection_details.return_value = {
            "id": "outline_coll_id_1",
            "name": outline_coll_name,
        }
        self.mock_mattermost_client.send_dm.return_value = True

        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_authentik_groups_by_name_fixture,
            email_to_authentik_user_pk_map=self.email_to_authentik_user_pk_map_fixture,
            perform_deletions=True,
        )

        user1_pk = self.email_to_authentik_user_pk_map_fixture["user1@example.com"]
        user2_pk = self.email_to_authentik_user_pk_map_fixture["user2@example.com"]

        self.mock_authentik_client.add_user_to_group.assert_any_call(std_auth_group_obj["pk"], user1_pk)
        self.mock_authentik_client.add_user_to_group.assert_any_call(adm_auth_group_obj["pk"], user1_pk)
        self.mock_authentik_client.add_user_to_group.assert_any_call(adm_auth_group_obj["pk"], user2_pk)
        self.assertEqual(self.mock_authentik_client.add_user_to_group.call_count, 3)

        outline_user1_id = "outlineid_user1"
        outline_user2_id = "outlineid_user2"

        self.mock_outline_client.add_user_to_collection.assert_any_call(
            "outline_coll_id_1", outline_user1_id, permission="read_write"
        )
        self.mock_outline_client.add_user_to_collection.assert_any_call(
            "outline_coll_id_1", outline_user2_id, permission="read_write"
        )
        self.assertEqual(self.mock_outline_client.add_user_to_collection.call_count, 2)

        successful_actions = [r for r in results if r.get("status") == "SUCCESS"]
        self.assertEqual(len(successful_actions), 5)  # 3 auth + 2 outline

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
        self.mock_outline_client.get_collection_by_name.return_value = {
            "id": "outline_coll_id_dm",
            "name": outline_coll_name,
        }
        self.mock_outline_client.get_collection_members.return_value = []
        self.mock_outline_client.add_user_to_collection.return_value = True
        self.mock_outline_client.get_collection_details.return_value = {
            "id": "outline_coll_id_dm",
            "name": outline_coll_name,
        }
        self.mock_mattermost_client.send_dm.return_value = True
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_authentik_groups_by_name_fixture,
            email_to_authentik_user_pk_map=email_map_for_dm,
            perform_deletions=True,
        )
        self.assertEqual(len([r for r in results if r["status"] == "SUCCESS"]), 2)
        outline_result = next(r for r in results if r["service"] == "OUTLINE" and r["status"] == "SUCCESS")
        self.assertEqual(outline_result["action"], "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_ACCESS_AND_DM_SENT")
        self.mock_mattermost_client.send_dm.assert_called_once()
        call_args = self.mock_mattermost_client.send_dm.call_args[0]
        self.assertEqual(call_args[0], mm_user_for_dm["id"])
        collection_slug = slugify(outline_coll_name)
        collection_id = "outline_coll_id_dm"
        expected_url = f"{mock_config_module_in_service.OUTLINE_URL}/collection/{collection_slug}-{collection_id}"
        self.assertIn(expected_url, call_args[1])
        self.assertIn(outline_coll_name, call_args[1])

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
        self.mock_outline_client.get_collection_by_name.return_value = {
            "id": "outline_coll_id_dm_fail",
            "name": outline_coll_name,
        }
        self.mock_outline_client.get_collection_members.return_value = []
        self.mock_outline_client.add_user_to_collection.return_value = True
        self.mock_outline_client.get_collection_details.return_value = {
            "id": "outline_coll_id_dm_fail",
            "name": outline_coll_name,
        }
        self.mock_mattermost_client.send_dm.return_value = False
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_authentik_groups_by_name_fixture,
            email_to_authentik_user_pk_map=email_map_for_dm,
            perform_deletions=True,
        )
        outline_result = next(r for r in results if r["service"] == "OUTLINE" and r["status"] == "SUCCESS")
        self.assertEqual(outline_result["action"], "USER_ADDED_TO_OUTLINE_COLLECTION_WITH_READ_ACCESS_DM_FAILED")
        self.mock_mattermost_client.send_dm.assert_called_once()

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
        outline_collection_data = {"id": "outline_coll_id_already", "name": outline_coll_name}
        self.mock_mattermost_client.get_channel_by_name.side_effect = lambda _, slug: (
            std_mm_channel_obj if slug == slugify(std_mm_channel_name) else None
        )
        self.mock_mattermost_client.get_users_in_channel.return_value = [mm_user_already_member]
        self.mock_authentik_client.add_user_to_group.return_value = True
        self.mock_outline_client.get_user_by_email.return_value = outline_user_data
        self.mock_outline_client.get_collection_by_name.return_value = outline_collection_data
        self.mock_outline_client.get_collection_members.return_value = [outline_user_data["id"]]
        self.mock_outline_client.add_user_to_collection.return_value = True
        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_authentik_groups_by_name_fixture,
            email_to_authentik_user_pk_map=email_map_already,
            perform_deletions=True,
        )
        outline_result = next(r for r in results if r["service"] == "OUTLINE" and r["status"] == "SUCCESS")
        self.assertEqual(outline_result["action"], "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED")
        self.mock_outline_client.add_user_to_collection.assert_called_once_with(
            outline_collection_data["id"], outline_user_data["id"], permission="read"
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
            mm_team_id=self.mm_team_id,
            entity_key="PROJET",
            base_name="",  # base_name not used if pattern is exact
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_auth_groups_fixture,
            email_to_authentik_user_pk_map=email_to_pk_map,
            perform_deletions=True,
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
        self.assertTrue(removal_action_found, "USER_REMOVED_FROM_AUTHENTIK_GROUP action not found")
        kept_action_found = any(
            r["service"] == "AUTHENTIK"
            and r["action"] == "USER_ALREADY_IN_AUTHENTIK_GROUP"
            and r["mm_username"] == "keepme_user"
            for r in results
        )
        self.assertTrue(kept_action_found, "USER_ALREADY_IN_AUTHENTIK_GROUP action not found")

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
            mm_team_id=self.mm_team_id,
            entity_key="PROJET",
            base_name="",
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_auth_groups_fixture,
            email_to_authentik_user_pk_map=email_to_pk_map,
            perform_deletions=True,
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
        self.mock_outline_client.get_collection_by_name.return_value = {
            "id": "outline_coll_1",
            "name": outline_coll_name,
        }
        self.mock_outline_client.get_collection_members.return_value = [
            outline_user_id_to_remove,
            outline_user_id_to_keep,
        ]

        def mock_get_user_by_email_side_effect(email):
            if email == mm_user_to_keep_outline["email"]:
                return {"id": outline_user_id_to_keep, "email": email}
            return None

        self.mock_outline_client.get_user_by_email.side_effect = mock_get_user_by_email_side_effect
        # Mock get_user_by_id for the user to be removed
        self.mock_outline_client.get_user_by_id.return_value = {"id": outline_user_id_to_remove, "name": f"OutlineUserName_{outline_user_id_to_remove}", "email": "removed@example.com"}
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
            mm_team_id=self.mm_team_id,
            entity_key=entity_key_for_test,
            base_name=base_name_for_test,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_auth_groups_fixture,
            email_to_authentik_user_pk_map=email_to_pk_map,
            perform_deletions=True,
        )
        self.mock_outline_client.remove_user_from_collection.assert_called_once_with(
            "outline_coll_1", outline_user_id_to_remove
        )
        self.mock_outline_client.add_user_to_collection.assert_called_once_with(
            "outline_coll_1", outline_user_id_to_keep, permission="read"
        )
        removal_action = next((r for r in results if r.get("action") == "USER_REMOVED_FROM_OUTLINE_COLLECTION"), None)
        self.assertIsNotNone(removal_action)
        # This should match the "name" field from the mocked get_user_by_id if the user is not in MM channels
        self.assertEqual(removal_action["mm_username"], f"OutlineUserName_{outline_user_id_to_remove}")
        kept_action = next(
            (r for r in results if r.get("action") == "USER_ALREADY_IN_OUTLINE_COLLECTION_PERMISSION_ENSURED"), None
        )
        self.assertIsNotNone(kept_action)
        self.assertEqual(kept_action["mm_username"], "keepme_outline")

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
        email_to_pk_map = {"excluded.outline@example.com": "auth_pk_excl"}

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
        self.mock_outline_client.get_collection_by_name.return_value = {
            "id": "outline_coll_excl",
            "name": outline_coll_name,
        }
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
                "admin_access": "read_write",
            },
        }
        sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            mm_team_id=self.mm_team_id,
            entity_key=entity_key_for_test,
            base_name=base_name_for_test,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_auth_groups_fixture,
            email_to_authentik_user_pk_map=email_to_pk_map,
            perform_deletions=True,
        )
        self.mock_outline_client.remove_user_from_collection.assert_not_called()
        self.mock_outline_client.add_user_to_collection.assert_not_called()

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
                self.mock_outline_client.get_user_by_email.return_value = outline_user_data

                # The patterns should only use {base_name} as that's what sync_entity_permissions uses for .format()
                # The entity_key_for_test is used to select the correct top-level key from a larger mocked PERMISSIONS_MATRIX if needed,
                # or to construct parts of the name if the pattern itself doesn't include the entity type (e.g. "projet_").
                # For this specific test, the base_name_from_case already implies the entity type (e.g., "projet_test").
                mock_entity_config = {
                    "standard": {
                        "authentik_group_name_pattern": f"{entity_key_for_test.lower()}_{{base_name}}",  # Pattern uses {base_name}
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
                # Names are now formatted by the function under test using the patterns above and base_name_from_case
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
                self.mock_outline_client.get_collection_by_name.return_value = {
                    "id": "outline_coll_id_perm_test",
                    "name": outline_coll_name,
                }
                self.mock_outline_client.get_collection_members.return_value = []
                self.mock_outline_client.add_user_to_collection.return_value = True
                self.mock_outline_client.get_collection_details.return_value = {
                    "id": "outline_coll_id_perm_test",
                    "name": outline_coll_name,
                }
                self.mock_mattermost_client.send_dm.return_value = True

                results = sync_entity_permissions(
                    authentik_client=self.mock_authentik_client,
                    mattermost_client=self.mock_mattermost_client,
                    outline_client=self.mock_outline_client,
                    mm_team_id=self.mm_team_id,
                    entity_key=entity_key_for_test,
                    base_name=base_name_from_case,
                    entity_config=mock_entity_config,
                    all_authentik_groups_by_name=all_authentik_groups_by_name_fixture,
                    email_to_authentik_user_pk_map=email_to_pk_map,
            perform_deletions=True,
                )

                self.mock_outline_client.add_user_to_collection.assert_called_once()
                call_args = self.mock_outline_client.add_user_to_collection.call_args
                called_with_permission = call_args.kwargs.get("permission")
                self.assertEqual(called_with_permission, expected_permission)

                outline_result = next(
                    (r for r in results if r["service"] == "OUTLINE" and r["status"] == "SUCCESS"), None
                )
                self.assertIsNotNone(outline_result)
                if outline_result:
                    dm_part = "_AND_DM_SENT"
                    expected_action_val = (
                        f"USER_ADDED_TO_OUTLINE_COLLECTION_WITH_{expected_permission.upper()}_ACCESS{dm_part}"
                    )
                    self.assertEqual(outline_result.get("action"), expected_action_val)


if __name__ == "__main__":
    unittest.main()
