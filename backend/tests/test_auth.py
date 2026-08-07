from unittest.mock import MagicMock

import pytest

import config
from backend import auth
from fastapi import HTTPException


def _fake_request(session_user=None):
    request = MagicMock()
    request.session = {"user": session_user} if session_user else {}
    return request


def test_dev_mode_always_returns_fake_admin(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    user = auth.get_current_user(_fake_request())
    assert user is not None
    assert user.is_admin is True


def test_real_mode_no_session_returns_none(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    user = auth.get_current_user(_fake_request(session_user=None))
    assert user is None


def test_real_mode_admin_group_membership_grants_admin(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_GROUP_NAME", "community-manager-admins")
    user = auth.get_current_user(
        _fake_request(session_user={"email": "a@b.com", "name": "A", "groups": ["community-manager-admins"]})
    )
    assert user.is_admin is True


def test_real_mode_non_admin_group_denied(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_GROUP_NAME", "community-manager-admins")
    user = auth.get_current_user(
        _fake_request(session_user={"email": "a@b.com", "name": "A", "groups": ["some-other-group"]})
    )
    assert user.is_admin is False


def test_require_admin_raises_401_when_not_logged_in(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    with pytest.raises(HTTPException) as exc_info:
        auth.require_admin(_fake_request())
    assert exc_info.value.status_code == 401


def test_require_admin_raises_403_when_not_admin(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_GROUP_NAME", "community-manager-admins")
    with pytest.raises(HTTPException) as exc_info:
        auth.require_admin(_fake_request(session_user={"email": "a@b.com", "groups": []}))
    assert exc_info.value.status_code == 403
