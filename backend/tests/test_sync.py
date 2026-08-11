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
