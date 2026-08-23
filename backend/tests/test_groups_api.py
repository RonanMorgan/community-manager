from unittest.mock import MagicMock, patch

import pytest


def test_pages_are_reachable(client):
    assert client.get("/groups", follow_redirects=True).status_code == 200
    assert client.get("/applications", follow_redirects=True).status_code == 200


@pytest.fixture()
def mock_authentik_create():
    """Authentik group creation is mandatory for every /api/groups call —
    this fixture provides a working mock so tests can focus on what they're
    actually testing (Outline/Mattermost provisioning, duplicate names, etc.)."""
    with patch("backend.authentik_service.get_client") as mock_get_client:
        client = MagicMock()
        client.create_group.side_effect = lambda name: {"pk": f"ak-{name}", "name": name}
        mock_get_client.return_value = client
        yield client


def test_create_group_requires_authentik(client):
    """Authentik group creation is mandatory (source of truth, CLAUDE.md
    §4-bis) — if it fails, the whole request must fail, with no group
    created at all (no orphan app-only group)."""
    with patch("backend.authentik_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.create_group.return_value = False  # AuthentikClient's failure sentinel
        mock_get_client.return_value = mock_client

        r = client.post("/api/groups", json={"name": "pole-test", "tools": []})
        assert r.status_code == 502

    assert "pole-test" not in client.get("/groups").text


def test_create_group_creates_authentik_group_and_links_it(client, mock_authentik_create):
    r = client.post("/api/groups", json={"name": "pole-test", "tools": []})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "pole-test"
    mock_authentik_create.create_group.assert_called_once_with("pole-test")

    from backend.database import SessionLocal
    from backend.models import Group

    db = SessionLocal()
    group = db.query(Group).filter(Group.name == "pole-test").first()
    assert group.authentik_group_id == "ak-pole-test"
    db.close()


def test_create_group_outline_not_configured_marks_resource_error(client, mock_authentik_create):
    """Outline isn't configured in the test env -> the resource should be
    created with status=error rather than the whole request failing."""
    r = client.post("/api/groups", json={"name": "pole-test", "tools": ["outline"]})
    assert r.status_code == 201
    data = r.json()
    assert data["resources"][0]["status"] == "error"
    assert data["resources"][0]["external_id"] is None


def test_create_group_duplicate_name_returns_409(client, mock_authentik_create):
    client.post("/api/groups", json={"name": "pole-test", "tools": []})
    r = client.post("/api/groups", json={"name": "pole-test", "tools": []})
    assert r.status_code == 409
    # Only one Authentik group creation attempt — the duplicate check happens first.
    mock_authentik_create.create_group.assert_called_once()


def test_create_group_success_with_mocked_outline(client, mock_authentik_create):
    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.create_group.return_value = {"id": "col-123", "name": "pole-test"}
        mock_get_client.return_value = mock_client

        r = client.post("/api/groups", json={"name": "pole-test", "tools": ["outline"]})
        assert r.status_code == 201
        resource = r.json()["resources"][0]
        assert resource["status"] == "active"
        assert resource["external_id"] == "col-123"


def test_create_group_success_with_mocked_mattermost(client, mock_authentik_create):
    with patch("backend.mattermost_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.create_channel.return_value = {"id": "chan-123", "name": "pole-test"}
        mock_get_client.return_value = mock_client

        r = client.post("/api/groups", json={"name": "pole-test", "tools": ["mattermost"]})
        assert r.status_code == 201
        resource = r.json()["resources"][0]
        assert resource["tool"] == "mattermost"
        assert resource["status"] == "active"
        assert resource["external_id"] == "chan-123"


def test_create_group_creates_outline_and_mattermost_together(client, mock_authentik_create):
    with patch("backend.outline_service.get_client") as mock_ol, \
         patch("backend.mattermost_service.get_client") as mock_mm:
        outline_client = MagicMock()
        outline_client.create_group.return_value = {"id": "col-1", "name": "Antenne Test"}
        mock_ol.return_value = outline_client

        mm_client = MagicMock()
        mm_client.create_channel.return_value = {"id": "chan-1", "name": "antenne-test"}
        mock_mm.return_value = mm_client

        r = client.post("/api/groups", json={"name": "Antenne Test", "tools": ["outline", "mattermost"]})
        assert r.status_code == 201
        data = r.json()
        assert data["category"] == "antenne"
        resources = {res["tool"]: res for res in data["resources"]}
        assert resources["outline"]["external_id"] == "col-1"
        assert resources["mattermost"]["external_id"] == "chan-1"
        assert "mattermost_admin" not in resources


class TestProjetAdminChannel:
    """A Projet's admin channel is mandatory (not a checkbox) whenever
    Mattermost is selected — unlike Pôles/Antennes, which never have this
    concept at all. See CLAUDE.md §6-octies/§6-nonies and
    config/resource_templates.yml."""

    def test_created_alongside_mattermost_for_a_projet(self, client, mock_authentik_create):
        with patch("backend.mattermost_service.get_client") as mock_mm:
            mm_client = MagicMock()
            mm_client.create_channel.side_effect = lambda name: {
                "id": f"chan-{name}", "name": name, "display_name": name
            }
            mock_mm.return_value = mm_client

            r = client.post("/api/groups", json={"name": "Projet Test", "tools": ["mattermost"]})
            assert r.status_code == 201
            resources = {res["tool"]: res for res in r.json()["resources"]}

            assert "mattermost_admin" in resources
            assert resources["mattermost_admin"]["status"] == "active"
            assert resources["mattermost_admin"]["display_name"] == "Projet Test Admin"
            mock_authentik_create.create_group.assert_any_call("Projet Test Admin")
            mm_client.create_channel.assert_any_call("Projet Test Admin")

    def test_not_created_for_a_pole(self, client, mock_authentik_create):
        with patch("backend.mattermost_service.get_client") as mock_mm:
            mock_mm.return_value = MagicMock(create_channel=MagicMock(return_value={"id": "chan-1", "name": "x"}))

            r = client.post("/api/groups", json={"name": "Pole Test", "tools": ["mattermost"]})
            assert r.status_code == 201
            resources = {res["tool"] for res in r.json()["resources"]}

            assert "mattermost_admin" not in resources
            # Only the main group's Authentik group was created, no "... Admin" one.
            assert mock_authentik_create.create_group.call_count == 1

    def test_not_created_for_a_projet_without_mattermost_selected(self, client, mock_authentik_create):
        with patch("backend.outline_service.get_client") as mock_ol:
            mock_ol.return_value = MagicMock(create_group=MagicMock(return_value={"id": "col-1", "name": "x"}))

            r = client.post("/api/groups", json={"name": "Projet Test", "tools": ["outline"]})
            assert r.status_code == 201
            resources = {res["tool"] for res in r.json()["resources"]}

            assert "mattermost_admin" not in resources
            assert mock_authentik_create.create_group.call_count == 1

    def test_authentik_failure_marks_resource_error_without_aborting_group_creation(self, client):
        with patch("backend.authentik_service.get_client") as mock_ak, \
             patch("backend.mattermost_service.get_client") as mock_mm:
            ak_client = MagicMock()

            def create_group_side_effect(name):
                if name.endswith("Admin"):
                    return False  # the admin Authentik group creation fails
                return {"pk": f"ak-{name}", "name": name}

            ak_client.create_group.side_effect = create_group_side_effect
            mock_ak.return_value = ak_client
            mm_client = MagicMock(create_channel=MagicMock(return_value={"id": "chan-1", "name": "x"}))
            mock_mm.return_value = mm_client

            r = client.post("/api/groups", json={"name": "Projet Test", "tools": ["mattermost"]})
            assert r.status_code == 201  # the main group still succeeds
            resources = {res["tool"]: res for res in r.json()["resources"]}
            assert resources["mattermost_admin"]["status"] == "error"
            # The main channel is still created; only the admin channel
            # creation was skipped, since the admin Authentik group failed first.
            called_names = [call.args[0] for call in mm_client.create_channel.call_args_list]
            assert "Projet Test Admin" not in called_names

    def test_mattermost_failure_marks_resource_error(self, client, mock_authentik_create):
        with patch("backend.mattermost_service.get_client") as mock_mm:
            mm_client = MagicMock()

            def create_channel_side_effect(name):
                if name.endswith("Admin"):
                    return None  # only the admin channel creation fails
                return {"id": f"chan-{name}", "name": name}

            mm_client.create_channel.side_effect = create_channel_side_effect
            mock_mm.return_value = mm_client

            r = client.post("/api/groups", json={"name": "Projet Test", "tools": ["mattermost"]})
            assert r.status_code == 201
            resources = {res["tool"]: res for res in r.json()["resources"]}
            assert resources["mattermost"]["status"] == "active"  # the main channel is unaffected
            assert resources["mattermost_admin"]["status"] == "error"
            # The admin Authentik group itself WAS created successfully.
            mock_authentik_create.create_group.assert_any_call("Projet Test Admin")
