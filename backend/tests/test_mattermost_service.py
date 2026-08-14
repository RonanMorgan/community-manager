from unittest.mock import MagicMock, patch

import pytest

from backend import mattermost_service


@pytest.fixture()
def mock_client():
    with patch("backend.mattermost_service.get_client") as mock_get_client:
        client = MagicMock()
        client.team_id = "team-1"
        mock_get_client.return_value = client
        yield client


def test_find_channel_by_name_matches_by_corrected_slug_first(mock_client):
    """Primary strategy: Mattermost auto-derives (and keeps up to date on
    rename) a channel's slug from its display name, using its own
    accent-dropping conversion rules — mirrored by clients.mattermost_client
    .slugify(). A direct slug lookup should succeed without needing the
    fallback search at all."""
    mock_client.get_channel_by_name.return_value = {"id": "chan-1", "name": "projet-basta-admin"}

    result = mattermost_service.find_channel_by_name("Projet Basta Admin")

    assert result["id"] == "chan-1"
    mock_client.get_channel_by_name.assert_called_once_with("team-1", "projet-basta-admin")
    mock_client.search_channels_for_team.assert_not_called()


def test_find_channel_by_name_falls_back_to_display_name_search(mock_client):
    """Fallback: a channel whose handle was manually customized away from
    the auto-derived slug (or a Mattermost deployment with 'anonymous URLs'
    enabled) won't be found by slug — search by exact display name instead."""
    mock_client.get_channel_by_name.return_value = None
    mock_client.search_channels_for_team.return_value = [
        {"id": "chan-2", "name": "some-custom-handle", "display_name": "Projet Basta Admin"},
    ]

    result = mattermost_service.find_channel_by_name("Projet Basta Admin")

    assert result["id"] == "chan-2"


def test_find_channel_by_name_fallback_requires_exact_display_name_match(mock_client):
    mock_client.get_channel_by_name.return_value = None
    mock_client.search_channels_for_team.return_value = [
        {"id": "chan-3", "name": "projet-basta-social", "display_name": "Projet Basta Social"},
    ]

    result = mattermost_service.find_channel_by_name("Projet Basta")

    assert result is None


def test_find_channel_by_name_returns_none_when_neither_strategy_finds_it(mock_client):
    mock_client.get_channel_by_name.return_value = None
    mock_client.search_channels_for_team.return_value = []

    assert mattermost_service.find_channel_by_name("Nonexistent") is None


def test_find_channel_by_name_raises_if_fallback_search_errors(mock_client):
    mock_client.get_channel_by_name.return_value = None
    mock_client.search_channels_for_team.return_value = None  # client signals an API error this way

    with pytest.raises(mattermost_service.MattermostError):
        mattermost_service.find_channel_by_name("Projet Basta Admin")
