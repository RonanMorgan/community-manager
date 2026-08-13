from unittest.mock import MagicMock, patch


def _create_outline_group(client, name="pole-test"):
    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.create_group.return_value = {"id": "col-1", "name": name}
        mock_get_client.return_value = mock_client
        r = client.post("/api/groups", json={"name": name, "tools": ["outline"]})
        return r.json()["resources"][0]["id"]


def test_search_candidates_outline(client):
    resource_id = _create_outline_group(client)

    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.search_collections.return_value = [
            {"id": "col-99", "name": "Projet 14_IFP"},
            {"id": "col-100", "name": "Projet 14 bis"},
        ]
        mock_get_client.return_value = mock_client

        r = client.get(f"/api/group-resources/{resource_id}/search-candidates", params={"q": "Projet 14"})
        assert r.status_code == 200
        names = {c["name"] for c in r.json()}
        assert names == {"Projet 14_IFP", "Projet 14 bis"}


def test_search_candidates_empty_query_returns_empty_list(client):
    resource_id = _create_outline_group(client)
    r = client.get(f"/api/group-resources/{resource_id}/search-candidates", params={"q": ""})
    assert r.status_code == 200
    assert r.json() == []


def test_search_candidates_unknown_resource_returns_404(client):
    r = client.get("/api/group-resources/does-not-exist/search-candidates", params={"q": "foo"})
    assert r.status_code == 404


def test_relink_resource_updates_external_id_and_status(client):
    resource_id = _create_outline_group(client, name="Projet 14_IndexFeminisationPouvoir")

    r = client.post(
        f"/api/group-resources/{resource_id}/relink",
        json={"external_id": "col-99", "display_name": "Projet 14_IFP"},
    )
    assert r.status_code == 200
    resource = r.json()["resources"][0]
    assert resource["external_id"] == "col-99"
    assert resource["display_name"] == "Projet 14_IFP"
    assert resource["status"] == "active"


def test_relink_unknown_resource_returns_404(client):
    r = client.post(
        "/api/group-resources/does-not-exist/relink",
        json={"external_id": "x", "display_name": "y"},
    )
    assert r.status_code == 404
