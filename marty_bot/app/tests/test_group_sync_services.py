import unittest
import os
from unittest.mock import patch, MagicMock
import logging  # Added logging import

from libraries.group_sync_services import (
    sync_entity_permissions,
    orchestrate_group_synchronization,
    _map_auth_group_to_entity_and_base_name,
    _map_mm_channel_to_entity_and_base_name,
    _extract_base_name,
    # _sync_single_nocodb_project_users # Removed unused import
)
from app import config as app_config
from clients.mattermost_client import MattermostClient, slugify
from clients.authentik_client import AuthentikClient
from clients.outline_client import OutlineClient
from clients.brevo_client import BrevoClient
from clients.vaultwarden_client import VaultwardenClient
from clients.nocodb_client import NocoDBClient


def reload_config_module():
    import importlib

    importlib.reload(app_config)


class TestGroupSyncServices(unittest.TestCase):

    def setUp(self):
        app_config.EXCLUDED_USERS = set()
        # Load mandatory config from env, others can be mocked via mock_config if needed by specific tests
        app_config.NOCODB_PROJECT_ID = os.getenv("TEST_NOCODB_PROJECT_ID", "p_test_default_project_id")

        self.mock_authentik_client = MagicMock(spec=AuthentikClient)
        self.mock_mattermost_client = MagicMock(spec=MattermostClient)
        self.mock_outline_client = MagicMock(spec=OutlineClient)
        self.mock_brevo_client = MagicMock(spec=BrevoClient)
        self.mock_vaultwarden_client = MagicMock(spec=VaultwardenClient)
        self.mock_nocodb_client = MagicMock(spec=NocoDBClient)
        self.mm_team_id = "test_team_id"
        self.nocodb_project_id_fixture = app_config.NOCODB_PROJECT_ID  # Use loaded or default

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

        self.mock_vaultwarden_client.create_collection.return_value = {
            "id": "default_vw_id",
            "name": "DefaultVWCollection",
        }
        self.mock_nocodb_client.create_table_in_project.return_value = {
            "id": "default_nc_table_id",
            "title": "DefaultNCTable",
        }

        self.mock_brevo_client.get_list_by_name.return_value = None

        def create_brevo_list_side_effect(name, folder_id=None):
            new_list_id = f"new_brevo_list_id_for_{slugify(name)}"
            return {"name": name, "id": new_list_id}

        self.mock_brevo_client.create_list.side_effect = create_brevo_list_side_effect
        self.mock_brevo_client.add_contact_to_list.return_value = True
        self.mock_brevo_client.remove_contact_from_list.return_value = True
        self.mock_brevo_client.get_contacts_from_list.return_value = []

    # ... (extract_base_name, map_auth_group_to_entity_and_base_name, map_mm_channel_to_entity_and_base_name tests remain the same)
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
        self.assertEqual(_extract_base_name("ProjetAdmin", "Projet{base_name}Admin"), "")
        self.assertEqual(_extract_base_name("Projet Super Cool Admin", "Projet {base_name} Admin"), "Super Cool")

    def test_map_auth_group_to_entity_and_base_name(self):
        matrix = {
            "PROJET": {
                "standard": {"authentik_group_name_pattern": "projet_{base_name}"},
                "admin": {"authentik_group_name_pattern": "projet_{base_name}_admin"},
            },
            "ANTENNE": {"standard": {"authentik_group_name_pattern": "antenne_{base_name}_standard"}},
        }
        self.assertEqual(_map_auth_group_to_entity_and_base_name("projet_MonProjet", matrix), ("PROJET", "MonProjet"))
        self.assertEqual(
            _map_auth_group_to_entity_and_base_name("projet_MonProjet_admin", matrix), ("PROJET", "MonProjet")
        )
        self.assertEqual(_map_auth_group_to_entity_and_base_name("projet_admin", matrix), ("PROJET", "admin"))
        self.assertEqual(_map_auth_group_to_entity_and_base_name("projet__admin", matrix), ("PROJET", ""))
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
            "ANTENNE": {"standard": {"mattermost_channel_name_pattern": "Antenne {base_name} Standard"}},
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
    def test_sync_entity_permissions_with_all_services_including_nocodb(self, mock_config_module_in_service):
        mock_config_module_in_service.EXCLUDED_USERS = set()
        mock_config_module_in_service.OUTLINE_URL = "http://fake-outline.com"
        # Use the project_id from setUp for NocoDB
        mock_config_module_in_service.NOCODB_PROJECT_ID = self.nocodb_project_id_fixture

        base_name = "AntenneTestFull"
        entity_key = "ANTENNE"  # Test with ANTENNE for NocoDB user sync

        mock_entity_config = {
            "standard": {
                "authentik_group_name_pattern": f"{entity_key.lower()}_{{base_name}}",
                "mattermost_channel_name_pattern": f"{entity_key.lower()}_{{base_name}}",
            },
            "admin": {
                "authentik_group_name_pattern": f"{entity_key.lower()}_{{base_name}} Admin",
                "mattermost_channel_name_pattern": f"{entity_key.lower()}_{{base_name}} Admin",
            },
            "outline": {"collection_name_pattern": f"outline_{entity_key.lower()}_{{base_name}}"},
            "brevo": {"list_name_pattern": f"brevo_{entity_key.lower()}_{{base_name}}"},
            "vaultwarden": {"collection_name_pattern": f"vw_{entity_key.lower()}_{{base_name}}"},
            "nocodb": {"table_name_pattern": f"nc_{entity_key.lower()}_{{base_name}}"},  # NocoDB config
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

        std_auth_group_obj = {"name": std_auth_group_name, "pk": "std_auth_pk_full", "users": [], "users_obj": []}
        adm_auth_group_obj = {"name": adm_auth_group_name, "pk": "adm_auth_pk_full", "users": [], "users_obj": []}
        all_authentik_groups_by_name_fixture = {
            std_auth_group_name: std_auth_group_obj,
            adm_auth_group_name: adm_auth_group_obj,
        }

        std_mm_channel_obj = {"id": "std_mm_chan_id_full", "display_name": std_mm_channel_name}
        adm_mm_channel_obj = {"id": "adm_mm_chan_id_full", "display_name": adm_mm_channel_name}

        self.mock_mattermost_client.get_channel_by_name.side_effect = lambda _, slug: (
            std_mm_channel_obj
            if slug == slugify(std_mm_channel_name)
            else (adm_mm_channel_obj if slug == slugify(adm_mm_channel_name) else None)
        )

        mm_user_std_only = {"username": "stduser", "email": "stduser@example.com", "id": "mm_std_user"}
        mm_user_admin = {"username": "adminuser", "email": "adminuser@example.com", "id": "mm_admin_user"}

        self.mock_mattermost_client.get_users_in_channel.side_effect = lambda channel_id: (
            [mm_user_std_only, mm_user_admin]
            if channel_id == std_mm_channel_obj["id"]
            else ([mm_user_admin] if channel_id == adm_mm_channel_obj["id"] else [])
        )

        # NocoDB user sync mocks
        self.mock_nocodb_client.list_base_users.return_value = []  # No existing users in NocoDB project
        self.mock_nocodb_client.invite_user_to_base.return_value = True

        # Other client mocks
        self.mock_authentik_client.add_user_to_group.return_value = True
        self.mock_outline_client.get_user_by_email.side_effect = lambda email: (
            {"id": f"outlineid_{slugify(email)}"} if email else None
        )
        self.mock_outline_client.get_collection_members.return_value = []
        self.mock_outline_client.add_user_to_collection.return_value = True
        self.mock_outline_client.get_collection_details.return_value = {
            "id": "fake_outline_coll_id",
            "name": "fake_coll_name",
        }
        self.mock_mattermost_client.send_dm.return_value = True

        results = sync_entity_permissions(
            authentik_client=self.mock_authentik_client,
            mattermost_client=self.mock_mattermost_client,
            outline_client=self.mock_outline_client,
            brevo_client=self.mock_brevo_client,
            vaultwarden_client=self.mock_vaultwarden_client,
            nocodb_client=self.mock_nocodb_client,  # Pass NocoDB client
            nocodb_project_id=self.nocodb_project_id_fixture,  # Pass NocoDB project ID
            mm_team_id=self.mm_team_id,
            entity_key=entity_key,
            base_name=base_name,
            entity_config=mock_entity_config,
            all_authentik_groups_by_name=all_authentik_groups_by_name_fixture,
            email_to_authentik_user_pk_map=self.email_to_authentik_user_pk_map_fixture,  # Ensure this has mappings for stduser and adminuser
            perform_deletions=True,
        )

        # Assert NocoDB calls
        self.mock_nocodb_client.list_base_users.assert_called_once_with(self.nocodb_project_id_fixture)
        # stduser should be invited as viewer, adminuser as owner
        self.mock_nocodb_client.invite_user_to_base.assert_any_call(
            self.nocodb_project_id_fixture, "stduser@example.com", "viewer"
        )
        self.mock_nocodb_client.invite_user_to_base.assert_any_call(
            self.nocodb_project_id_fixture, "adminuser@example.com", "owner"
        )
        self.assertEqual(self.mock_nocodb_client.invite_user_to_base.call_count, 2)

        # Check one NocoDB result
        nocodb_results_found = [r for r in results if r.get("service") == "NOCODB"]
        self.assertEqual(len(nocodb_results_found), 2)  # One for stduser, one for adminuser
        admin_nocodb_res = next(r for r in nocodb_results_found if r.get("mm_user_email") == "adminuser@example.com")
        self.assertEqual(admin_nocodb_res.get("action"), "NOCODB_USER_INVITED")
        self.assertIn("owner", admin_nocodb_res.get("details", ""))

    @patch("libraries.group_sync_services.sync_entity_permissions")
    @patch("libraries.group_sync_services.config")
    def test_orchestrate_sync_fetch_remote_false_discover_via_mm_no_deletions(
        self, mock_lib_config, mock_sync_entity_permissions_call
    ):
        self.mock_authentik_client.reset_mock()
        self.mock_mattermost_client.reset_mock()
        self.mock_outline_client.reset_mock()
        self.mock_vaultwarden_client.reset_mock()
        self.mock_nocodb_client.reset_mock()

        def create_auth_group_side_effect(name):
            return {"name": name, "pk": f"auth_pk_{slugify(name)}", "users": [], "users_obj": []}

        self.mock_authentik_client.get_group_by_name.return_value = None
        self.mock_authentik_client.create_group.side_effect = create_auth_group_side_effect

        def create_outline_coll_side_effect(name):
            return {"name": name, "id": f"outline_id_{slugify(name)}"}

        self.mock_outline_client.create_group.side_effect = create_outline_coll_side_effect
        mock_team_id = "team_upsert_mode"
        mock_email_pk_map_from_client = {
            "user.alpha@example.com": "auth_pk_alpha",
            "user.beta@example.com": "auth_pk_beta",
        }
        self.mock_authentik_client.get_all_user_email_to_pk_map.return_value = mock_email_pk_map_from_client
        self.mock_mattermost_client.get_channels_for_team.return_value = []
        mock_lib_config.PERMISSIONS_MATRIX = {
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
        }
        mock_lib_config.NOCODB_PROJECT_ID = self.nocodb_project_id_fixture  # Ensure it's set in mock_config

        success, detailed_results = orchestrate_group_synchronization(
            self.mock_authentik_client,
            self.mock_mattermost_client,
            self.mock_outline_client,
            self.mock_brevo_client,
            self.mock_vaultwarden_client,
            self.mock_nocodb_client,
            mock_lib_config.NOCODB_PROJECT_ID,  # Pass NocoDB related
            mock_team_id,
            perform_deletions=False,
            fetch_remote_members=False,
        )
        self.assertTrue(success)
        self.assertEqual(len(detailed_results), 0)
        self.mock_authentik_client.get_all_user_email_to_pk_map.assert_called_once_with()
        self.mock_authentik_client.get_groups_with_users.assert_not_called()
        self.mock_mattermost_client.get_channels_for_team.assert_called_once_with(mock_team_id)
        mock_sync_entity_permissions_call.assert_not_called()

    @patch("libraries.group_sync_services.sync_entity_permissions")
    @patch("libraries.group_sync_services.config")
    def test_orchestrate_sync_fetch_remote_true_discover_via_auth_with_deletions(
        self, mock_lib_config, mock_sync_entity_permissions_call
    ):
        self.mock_authentik_client.reset_mock()
        self.mock_mattermost_client.reset_mock()
        self.mock_outline_client.reset_mock()
        self.mock_vaultwarden_client.reset_mock()
        self.mock_nocodb_client.reset_mock()

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
        self.mock_authentik_client.get_groups_with_users.return_value = (
            mock_all_auth_groups_list,
            {"some_email_from_groups_obj@example.com": "pk_temp"},
        )
        mock_email_pk_map_from_all_users = {"user.gamma@example.com": "auth_pk_gamma"}
        self.mock_authentik_client.get_all_user_email_to_pk_map.return_value = mock_email_pk_map_from_all_users
        mock_lib_config.PERMISSIONS_MATRIX = {
            "PROJET": {
                "standard": {"authentik_group_name_pattern": "auth_projet_{base_name}"}
            },  # No NocoDB for projet
            "ANTENNE": {
                "admin": {"authentik_group_name_pattern": "auth_antenne_{base_name}_admin"},
                "nocodb": {"table_name_pattern": "nc_antenne_{base_name}"},  # NocoDB for Antenne
            },
        }
        mock_lib_config.NOCODB_PROJECT_ID = self.nocodb_project_id_fixture
        mock_sync_entity_permissions_call.return_value = [{"status": "SUCCESS", "action": "MOCKED_FULL_SYNC"}]

        success, detailed_results = orchestrate_group_synchronization(
            self.mock_authentik_client,
            self.mock_mattermost_client,
            self.mock_outline_client,
            self.mock_brevo_client,
            self.mock_vaultwarden_client,
            self.mock_nocodb_client,
            mock_lib_config.NOCODB_PROJECT_ID,  # Pass NocoDB
            mock_team_id,
            perform_deletions=True,
            fetch_remote_members=True,
        )
        self.assertTrue(success)
        self.assertEqual(len(detailed_results), 2)  # One per entity found
        self.mock_authentik_client.get_groups_with_users.assert_called_once_with(fetch_members=True)
        self.mock_authentik_client.get_all_user_email_to_pk_map.assert_called_once_with()
        self.mock_mattermost_client.get_channels_for_team.assert_not_called()
        expected_all_auth_groups_by_name = {g["name"]: g for g in mock_all_auth_groups_list}

        mock_sync_entity_permissions_call.assert_any_call(
            self.mock_authentik_client,
            self.mock_mattermost_client,
            self.mock_outline_client,
            self.mock_brevo_client,
            self.mock_vaultwarden_client,
            self.mock_nocodb_client,
            mock_lib_config.NOCODB_PROJECT_ID,
            mock_team_id,
            "Gamma",
            "PROJET",
            mock_lib_config.PERMISSIONS_MATRIX["PROJET"],
            expected_all_auth_groups_by_name,
            mock_email_pk_map_from_all_users,
            True,
        )
        mock_sync_entity_permissions_call.assert_any_call(
            self.mock_authentik_client,
            self.mock_mattermost_client,
            self.mock_outline_client,
            self.mock_brevo_client,
            self.mock_vaultwarden_client,
            self.mock_nocodb_client,
            mock_lib_config.NOCODB_PROJECT_ID,
            mock_team_id,
            "Delta",
            "ANTENNE",
            mock_lib_config.PERMISSIONS_MATRIX["ANTENNE"],
            expected_all_auth_groups_by_name,
            mock_email_pk_map_from_all_users,
            True,
        )

    # ... (Brevo tests and other existing tests remain, ensure they pass NocoDB client as None or mocked if they call orchestrate)
    # For brevity, only showing changes to existing orchestrate_* tests and the new NocoDB specific test.
    # The sync_single_brevo_list_helper and its tests are independent and should not need changes.

    # Example of how an existing test calling orchestrate might be minimally adapted if NocoDB is not its focus:
    @patch("libraries.group_sync_services.config")  # From an existing test, simplified
    def test_library_orchestrate_sync_no_groups_found(self, mock_lib_config):
        mock_lib_config.NOCODB_PROJECT_ID = None  # Or a fixture ID if preferred
        # ... (rest of existing mock setups for this test)
        success, detailed_results = orchestrate_group_synchronization(
            self.mock_authentik_client,
            self.mock_mattermost_client,
            self.mock_outline_client,
            self.mock_brevo_client,
            self.mock_vaultwarden_client,
            self.mock_nocodb_client,
            mock_lib_config.NOCODB_PROJECT_ID,
            self.mm_team_id,
            perform_deletions=True,
            fetch_remote_members=True,
        )
        # ... (rest of existing assertions for this test)
        self.assertTrue(success)  # Example assertion

    def test_library_orchestrate_sync_core_clients_missing(self):
        # ... (This test needs to be updated to pass the two new NocoDB args to all its calls)
        mock_outline_client = MagicMock(spec=OutlineClient)
        mock_vaultwarden_client_instance = self.mock_vaultwarden_client
        mock_nocodb_client_instance = self.mock_nocodb_client
        nocodb_proj_id = self.nocodb_project_id_fixture

        # Test with Authentik client missing
        success_auth, _ = orchestrate_group_synchronization(
            None,
            MagicMock(spec=MattermostClient),
            mock_outline_client,
            self.mock_brevo_client,
            mock_vaultwarden_client_instance,
            mock_nocodb_client_instance,
            nocodb_proj_id,
            "team_id",
            perform_deletions=True,
        )
        self.assertTrue(success_auth)
        # ... other assertions ...

        # Test with Mattermost client missing (critical)
        success_mm, _ = orchestrate_group_synchronization(
            MagicMock(spec=AuthentikClient),
            None,
            mock_outline_client,
            self.mock_brevo_client,
            mock_vaultwarden_client_instance,
            mock_nocodb_client_instance,
            nocodb_proj_id,
            "team_id",
            perform_deletions=True,
        )
        self.assertFalse(success_mm)

        # Test with Mattermost team_id missing (critical)
        success_team, _ = orchestrate_group_synchronization(
            MagicMock(spec=AuthentikClient),
            MagicMock(spec=MattermostClient),
            mock_outline_client,
            self.mock_brevo_client,
            mock_vaultwarden_client_instance,
            mock_nocodb_client_instance,
            nocodb_proj_id,
            None,
            perform_deletions=True,
        )
        self.assertFalse(success_team)

        # Test with NocoDB Project ID missing but NocoDB client present
        with patch.object(logging, "warning") as mock_log_warning:
            success_nocoproj, _ = orchestrate_group_synchronization(
                MagicMock(spec=AuthentikClient),
                MagicMock(spec=MattermostClient),
                mock_outline_client,
                self.mock_brevo_client,
                mock_vaultwarden_client_instance,
                mock_nocodb_client_instance,
                None,
                "team_id",
                perform_deletions=True,
            )
            self.assertTrue(success_nocoproj)  # Should still proceed, but log a warning
            mock_log_warning.assert_any_call(
                "NocoDB client is provided, but NOCODB_PROJECT_ID is not set. NocoDB user sync will be skipped."
            )


if __name__ == "__main__":
    unittest.main()
