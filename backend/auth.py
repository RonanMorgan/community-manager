"""
Authentication.

- If config.AUTH_ENABLED is False (default): every request is treated as an
  authenticated admin (config.DEV_FAKE_ADMIN_EMAIL). Useful for local dev /
  running the app without an Authentik instance at hand. NOT for production.
- If config.AUTH_ENABLED is True: real OIDC login against Authentik via
  Authlib. Admin status is determined by membership in the Authentik group
  named `config.ADMIN_GROUP_NAME` (read from the `groups` claim).

V0 scope note: only the admin pages are implemented, so `require_admin` is
the only dependency used by routes today. A non-admin authenticated user
currently gets a 403. Extending this to a "normal user" view is future work
(see CLAUDE.md).
"""
import logging

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request, status

import config

oauth = OAuth()

if config.AUTH_ENABLED:
    if not (config.OIDC_CLIENT_ID and config.OIDC_CLIENT_SECRET and config.OIDC_SERVER_METADATA_URL):
        raise RuntimeError(
            "AUTH_ENABLED=true but OIDC_CLIENT_ID / OIDC_CLIENT_SECRET / OIDC_SERVER_METADATA_URL "
            "are not fully configured. Set them in your .env (see .env.example)."
        )
    oauth.register(
        name="authentik",
        client_id=config.OIDC_CLIENT_ID,
        client_secret=config.OIDC_CLIENT_SECRET,
        server_metadata_url=config.OIDC_SERVER_METADATA_URL,
        client_kwargs={"scope": "openid profile email"},
    )


class CurrentUser:
    def __init__(self, email: str, name: str, is_admin: bool):
        self.email = email
        self.name = name
        self.is_admin = is_admin


def _dev_fake_admin() -> CurrentUser:
    return CurrentUser(email=config.DEV_FAKE_ADMIN_EMAIL, name="Dev Admin (AUTH_ENABLED=false)", is_admin=True)


def get_current_user(request: Request) -> CurrentUser | None:
    """Returns the current user (from session) or None if not logged in.
    Always returns a fake admin when AUTH_ENABLED=false."""
    if not config.AUTH_ENABLED:
        return _dev_fake_admin()

    user_session = request.session.get("user")
    if not user_session:
        return None

    groups = user_session.get("groups") or []
    is_admin = config.ADMIN_GROUP_NAME in groups
    return CurrentUser(
        email=user_session.get("email", ""),
        name=user_session.get("name", user_session.get("email", "")),
        is_admin=is_admin,
    )


def require_admin(request: Request) -> CurrentUser:
    """FastAPI dependency: raises 401/403 if the request isn't from a logged-in admin."""
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated. Go to /login.")
    if not user.is_admin:
        logging.info(f"Access denied (not admin) for {user.email}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return user
