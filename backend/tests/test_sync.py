from unittest.mock import MagicMock, patch


def test_sync_not_configured_returns_409(client):
    r = client.post("/api/sync")
    assert r.status_code == 409


def test_sync_creates_groups_and_matches_resources(client):
    fake_authentik_groups = [
        {"pk": "ak-1", "name": "pole-communication", "users_obj": []},
        {"pk": "ak-2", "name": "pole-technique", "users_obj": []},
    ]

    with patch("clients.authentik_client.AuthentikClient") as MockAuthentikClient, \
         patch("backend.outline_service.get_client") as mock_get_outline, \
         patch("backend.mattermost_service.get_client") as mock_get_mm, \
         patch("config.AUTHENTIK_URL", "https://authentik.example.org"), \
         patch("config.AUTHENTIK_TOKEN", "token"):

        mock_authentik = MagicMock()
        mock_authentik.get_groups_with_users.return_value = (fake_authentik_groups, {})
        MockAuthentikClient.return_value = mock_authentik

        mock_outline = MagicMock()
        # pole-communication has a matching Outline collection, pole-technique doesn't
        mock_outline.list_collections.side_effect = lambda name: (
            {"id": "col-1", "name": "pole-communication"} if name == "pole-communication" else []
        )
        mock_get_outline.return_value = mock_outline

        mock_mm = MagicMock()
        mock_mm.team_id = "team-1"
        # neither group has a matching Mattermost channel
        mock_mm.get_channel_by_name.return_value = None
        mock_get_mm.return_value = mock_mm

        r = client.post("/api/sync")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["groups_created"] == 2
        assert data["resources_matched"] == 1  # pole-communication / outline
        assert data["resources_not_found"] == 3  # pole-communication/mattermost + pole-technique/outline+mattermost

    r = client.get("/groups")
    assert "pole-communication" in r.text
    assert "pole-technique" in r.text


def test_sync_is_idempotent_on_group_name(client):
    """Running sync twice shouldn't create duplicate groups for the same Authentik group."""
    fake_authentik_groups = [{"pk": "ak-1", "name": "pole-test", "users_obj": []}]

    with patch("clients.authentik_client.AuthentikClient") as MockAuthentikClient, \
         patch("backend.outline_service.get_client") as mock_get_outline, \
         patch("backend.mattermost_service.get_client") as mock_get_mm, \
         patch("config.AUTHENTIK_URL", "https://authentik.example.org"), \
         patch("config.AUTHENTIK_TOKEN", "token"):

        mock_authentik = MagicMock()
        mock_authentik.get_groups_with_users.return_value = (fake_authentik_groups, {})
        MockAuthentikClient.return_value = mock_authentik

        mock_outline = MagicMock()
        mock_outline.list_collections.return_value = []
        mock_get_outline.return_value = mock_outline

        mock_mm = MagicMock()
        mock_mm.team_id = "team-1"
        mock_mm.get_channel_by_name.return_value = None
        mock_get_mm.return_value = mock_mm

        r1 = client.post("/api/sync")
        assert r1.json()["groups_created"] == 1

        r2 = client.post("/api/sync")
        assert r2.json()["groups_created"] == 0
        assert r2.json()["groups_updated"] == 1


def _sync_with(client, authentik_groups, outline_finder=None, mattermost_finder=None):
    """Helper: run /api/sync with the given fake Authentik groups and finder callables."""
    with patch("clients.authentik_client.AuthentikClient") as MockAuthentikClient, \
         patch("backend.outline_service.get_client") as mock_get_outline, \
         patch("backend.mattermost_service.get_client") as mock_get_mm, \
         patch("config.AUTHENTIK_URL", "https://authentik.example.org"), \
         patch("config.AUTHENTIK_TOKEN", "token"):
        mock_authentik = MagicMock()
        mock_authentik.get_groups_with_users.return_value = (authentik_groups, {})
        MockAuthentikClient.return_value = mock_authentik

        mock_outline = MagicMock()
        mock_outline.list_collections.side_effect = outline_finder or (lambda name: [])
        mock_get_outline.return_value = mock_outline

        mock_mm = MagicMock()
        mock_mm.team_id = "team-1"
        mock_mm.get_channel_by_name.side_effect = mattermost_finder or (lambda team, slug: None)
        mock_get_mm.return_value = mock_mm

        return client.post("/api/sync")


def test_sync_categorizes_groups_by_name_prefix(client):
    groups = [
        {"pk": "1", "name": "Projet Refonte Site", "users_obj": []},
        {"pk": "2", "name": "Pole Communication", "users_obj": []},
        {"pk": "3", "name": "Antenne Rennes", "users_obj": []},
        {"pk": "4", "name": "Legacy Group", "users_obj": []},
    ]
    r = _sync_with(client, groups)
    assert r.status_code == 200
    assert r.json()["groups_created"] == 4

    page = client.get("/groups").text
    assert "Projet Refonte Site" in page
    assert "Pole Communication" in page
    assert "Antenne Rennes" in page
    assert "Legacy Group" in page
    assert "Non catégorisés" in page


def test_sync_admin_suffixed_projet_group_becomes_admin_channel_not_a_new_group(client):
    groups = [
        {"pk": "1", "name": "Projet Refonte Site", "users_obj": []},
        {"pk": "2", "name": "Projet Refonte Site Admin", "users_obj": []},
    ]

    def mm_finder(team, slug):
        if slug == "projet-refonte-site-admin":
            return {"id": "chan-admin", "display_name": "Projet Refonte Site Admin"}
        return None

    r = _sync_with(client, groups, mattermost_finder=mm_finder)
    assert r.status_code == 200
    data = r.json()
    # Only ONE group created (the admin-suffixed one must not get its own Group row)
    assert data["groups_created"] == 1
    assert data["warnings"] == []

    page = client.get("/groups").text
    assert "Channel Admin" in page
    assert "Projet Refonte Site Admin" in page  # the admin channel's name, shown in that column


def test_sync_admin_suffixed_group_without_parent_produces_a_warning(client):
    groups = [{"pk": "2", "name": "Projet Orphan Admin", "users_obj": []}]

    r = _sync_with(client, groups)
    assert r.status_code == 200
    data = r.json()
    assert data["groups_created"] == 0  # no parent -> nothing created
    assert len(data["warnings"]) == 1
    assert "Orphan" in data["warnings"][0]


def test_sync_deletes_groups_no_longer_in_authentik(client):
    r1 = _sync_with(client, [
        {"pk": "1", "name": "Antenne Rennes", "users_obj": []},
        {"pk": "2", "name": "Legacy Group", "users_obj": []},
    ])
    assert r1.json()["groups_created"] == 2

    # Second run: both groups gone from Authentik.
    r2 = _sync_with(client, [])
    assert r2.status_code == 200
    assert r2.json()["groups_deleted"] == 2

    page = client.get("/groups").text
    assert "Antenne Rennes" not in page
    assert "Legacy Group" not in page


def test_sync_does_not_delete_manually_created_groups(client):
    """A group created via POST /api/groups (no authentik_group_id) must never
    be deleted by sync reconciliation, even if Authentik has nothing matching it."""
    r = client.post("/api/groups", json={"name": "Manually Made", "tools": []})
    assert r.status_code == 201

    sync_result = _sync_with(client, [])  # no Authentik groups at all
    assert sync_result.json()["groups_deleted"] == 0

    page = client.get("/groups").text
    assert "Manually Made" in page


def test_update_group_category_manually(client):
    _sync_with(client, [{"pk": "1", "name": "Unrecognized Name", "users_obj": []}])
    page = client.get("/groups").text
    assert "Unrecognized Name" in page

    from backend.database import SessionLocal
    from backend.models import Group

    db = SessionLocal()
    group = db.query(Group).filter(Group.name == "Unrecognized Name").first()
    group_id = group.id
    db.close()

    r = client.patch(f"/api/groups/{group_id}/category", json={"category": "pole"})
    assert r.status_code == 200
    assert r.json()["category"] == "pole"

    page = client.get("/groups").text
    assert "Pôles" in page


def test_prefix_detection_overrides_manual_category_on_next_sync(client):
    _sync_with(client, [{"pk": "1", "name": "Pole Communication", "users_obj": []}])
    from backend.database import SessionLocal
    from backend.models import Group, Category

    db = SessionLocal()
    group = db.query(Group).filter(Group.name == "Pole Communication").first()
    group_id = group.id
    db.close()

    client.patch(f"/api/groups/{group_id}/category", json={"category": "antenne"})

    _sync_with(client, [{"pk": "1", "name": "Pole Communication", "users_obj": []}])

    db2 = SessionLocal()
    group2 = db2.query(Group).filter(Group.name == "Pole Communication").first()
    assert group2.category == Category.POLE
    db2.close()
