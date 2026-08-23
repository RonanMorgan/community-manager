from unittest.mock import MagicMock, patch

import pytest

from backend import authentik_service


def test_get_client_raises_when_not_configured():
    with patch("config.AUTHENTIK_URL", ""), patch("config.AUTHENTIK_TOKEN", ""):
        with pytest.raises(authentik_service.AuthentikError):
            authentik_service.get_client()


def test_create_group_success():
    with patch("backend.authentik_service.get_client") as mock_get_client:
        client = MagicMock()
        client.create_group.return_value = {"pk": "ak-1", "name": "Projet Test"}
        mock_get_client.return_value = client

        result = authentik_service.create_group("Projet Test")

        assert result["pk"] == "ak-1"
        client.create_group.assert_called_once_with("Projet Test")


def test_create_group_raises_on_failure():
    """AuthentikClient.create_group() returns False (not an exception) on
    failure — the service layer must turn that into an explicit error."""
    with patch("backend.authentik_service.get_client") as mock_get_client:
        client = MagicMock()
        client.create_group.return_value = False
        mock_get_client.return_value = client

        with pytest.raises(authentik_service.AuthentikError):
            authentik_service.create_group("Projet Test")
