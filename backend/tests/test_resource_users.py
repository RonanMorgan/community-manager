from unittest.mock import MagicMock, patch


def _create_active_group(client):
    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.create_group.return_value = {"id": "col-123", "name": "pole-test"}
        mock_get_client.return_value = mock_client
        r = client.post("/api/groups", json={"name": "pole-test", "tools": ["outline"]})
        return r.json()["resources"][0]["id"]


def test_list_resource_users_returns_live_data(client):
    resource_id = _create_active_group(client)

    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.get_collection_memberships_with_permission.return_value = [
            {"user": {"id": "u1", "name": "Alice", "email": "alice@example.org"}, "permission": "read"},
            {"user": {"id": "u2", "name": "Bob", "email": "bob@example.org"}, "permission": "read_write"},
        ]
        mock_get_client.return_value = mock_client

        r = client.get(f"/api/group-resources/{resource_id}/users")
        assert r.status_code == 200
        emails = {u["email"] for u in r.json()}
        assert emails == {"alice@example.org", "bob@example.org"}


def test_add_user_success_defaults_to_read(client):
    resource_id = _create_active_group(client)

    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.get_user_by_email.return_value = {"id": "u2", "name": "Bob"}
        mock_client.add_user_to_collection.return_value = True
        mock_get_client.return_value = mock_client

        r = client.post(f"/api/group-resources/{resource_id}/users", json={"email": "bob@example.org"})
        assert r.status_code == 201
        mock_client.add_user_to_collection.assert_called_once_with("col-123", "u2", permission="read")


def test_add_user_not_provisioned_in_outline_returns_explicit_422(client):
    """Product decision: adding an email that doesn't exist yet in Outline
    must fail with a clear, explicit error rather than silently no-op."""
    resource_id = _create_active_group(client)

    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.get_user_by_email.return_value = None
        mock_get_client.return_value = mock_client

        r = client.post(f"/api/group-resources/{resource_id}/users", json={"email": "ghost@example.org"})
        assert r.status_code == 422
        assert "ghost@example.org" in r.json()["detail"]


def test_remove_user_success(client):
    resource_id = _create_active_group(client)

    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.remove_user_from_collection.return_value = True
        mock_get_client.return_value = mock_client

        r = client.delete(f"/api/group-resources/{resource_id}/users/u2")
        assert r.status_code == 204
