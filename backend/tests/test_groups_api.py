from unittest.mock import MagicMock, patch


def test_pages_are_reachable(client):
    assert client.get("/groups", follow_redirects=True).status_code == 200
    assert client.get("/applications", follow_redirects=True).status_code == 200


def test_create_group_outline_not_configured_marks_resource_error(client):
    """Outline isn't configured in the test env -> the resource should be
    created with status=error rather than the whole request failing."""
    r = client.post("/api/groups", json={"name": "pole-test", "tools": ["outline"]})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "pole-test"
    assert data["resources"][0]["status"] == "error"
    assert data["resources"][0]["external_id"] is None


def test_create_group_duplicate_name_returns_409(client):
    client.post("/api/groups", json={"name": "pole-test", "tools": ["outline"]})
    r = client.post("/api/groups", json={"name": "pole-test", "tools": ["outline"]})
    assert r.status_code == 409


def test_create_group_success_with_mocked_outline(client):
    with patch("backend.outline_service.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.create_group.return_value = {"id": "col-123", "name": "pole-test"}
        mock_get_client.return_value = mock_client

        r = client.post("/api/groups", json={"name": "pole-test", "tools": ["outline"]})
        assert r.status_code == 201
        resource = r.json()["resources"][0]
        assert resource["status"] == "active"
        assert resource["external_id"] == "col-123"
