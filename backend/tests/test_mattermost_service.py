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


def test_find_channel_by_name_matches_by_display_name_search_first(mock_client):
    """Primary strategy: search by exact display name. Doesn't depend on
    guessing a slug, so it's robust regardless of how the channel's slug
    was actually generated (see module docstring for why that varies)."""
    mock_client.search_channels_for_team.return_value = [
        {"id": "chan-1", "display_name": "Projet 14_RelaxesPourVivant"},
    ]

    result = mattermost_service.find_channel_by_name("Projet 14_RelaxesPourVivant")

    assert result["id"] == "chan-1"
    mock_client.get_channel_by_name.assert_not_called()


def test_find_channel_by_name_falls_back_to_slug_with_underscores_preserved(mock_client):
    """Regression test for a real bug: 'Projet 14_RelaxesPourVivant' has a
    Mattermost slug that KEEPS the underscore ('projet-14_relaxespourvivant'),
    unlike the standard slugify() which turns it into a hyphen."""
    mock_client.search_channels_for_team.return_value = []  # not found by search (e.g. private channel)

    def fake_get_channel_by_name(team_id, slug):
        if slug == "projet-14_relaxespourvivant":
            return {"id": "chan-2", "name": slug}
        return None

    mock_client.get_channel_by_name.side_effect = fake_get_channel_by_name

    result = mattermost_service.find_channel_by_name("Projet 14_RelaxesPourVivant")

    assert result["id"] == "chan-2"


def test_find_channel_by_name_falls_back_to_standard_slug(mock_client):
    """The other real example: 'Projet 13_démocratiser_sobriete' has a slug
    where BOTH underscores and the accented letter became hyphens —
    matches the standard (non-underscore-preserving) slugify() variant."""
    mock_client.search_channels_for_team.return_value = []

    def fake_get_channel_by_name(team_id, slug):
        if slug == "projet-13-d-mocratiser-sobriete":
            return {"id": "chan-3", "name": slug}
        return None

    mock_client.get_channel_by_name.side_effect = fake_get_channel_by_name

    result = mattermost_service.find_channel_by_name("Projet 13_démocratiser_sobriete")

    assert result["id"] == "chan-3"


def test_find_channel_by_name_fallback_requires_exact_display_name_match(mock_client):
    mock_client.search_channels_for_team.return_value = [
        {"id": "chan-4", "name": "projet-basta-social", "display_name": "Projet Basta Social"},
    ]
    mock_client.get_channel_by_name.return_value = None

    result = mattermost_service.find_channel_by_name("Projet Basta")

    assert result is None


def test_find_channel_by_name_returns_none_when_neither_strategy_finds_it(mock_client):
    mock_client.search_channels_for_team.return_value = []
    mock_client.get_channel_by_name.return_value = None

    assert mattermost_service.find_channel_by_name("Nonexistent") is None


def test_find_channel_by_name_raises_if_search_itself_errors(mock_client):
    mock_client.search_channels_for_team.return_value = None  # client signals an API error this way

    with pytest.raises(mattermost_service.MattermostError):
        mattermost_service.find_channel_by_name("Projet Basta")
