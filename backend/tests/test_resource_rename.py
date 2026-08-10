from unittest.mock import MagicMock, patch


def _create_active_group(client, mock_client_holder):
    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.create_group.return_value = {"id": "col-123", "name": "pole-test"}
        mock_get_client.return_value = mock_client
        mock_client_holder["client"] = mock_client
        r = client.post("/api/groups", json={"name": "pole-test", "tools": ["outline"]})
        return r.json()["resources"][0]["id"]


def test_rename_resource_success(client):
    holder = {}
    resource_id = _create_active_group(client, holder)

    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_get_client.return_value = holder["client"]
        holder["client"].update_collection_name.return_value = True

        r = client.patch(f"/api/group-resources/{resource_id}", json={"display_name": "nouveau-nom"})
        assert r.status_code == 200
        assert r.json()["resources"][0]["display_name"] == "nouveau-nom"
        holder["client"].update_collection_name.assert_called_once_with("col-123", "nouveau-nom")


def test_rename_resource_outline_failure_returns_502(client):
    holder = {}
    resource_id = _create_active_group(client, holder)

    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_get_client.return_value = holder["client"]
        holder["client"].update_collection_name.return_value = False

        r = client.patch(f"/api/group-resources/{resource_id}", json={"display_name": "nouveau-nom"})
        assert r.status_code == 502


def test_rename_unknown_resource_returns_404(client):
    r = client.patch("/api/group-resources/does-not-exist", json={"display_name": "x"})
    assert r.status_code == 404
