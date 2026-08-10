import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import config
from backend.auth import oauth

router = APIRouter(tags=["auth"])


@router.get("/login")
async def login(request: Request):
    if not config.AUTH_ENABLED:
        # Nothing to do: every request is already treated as the dev fake admin.
        return RedirectResponse(url="/groups")
    redirect_uri = config.OIDC_REDIRECT_URI
    return await oauth.authentik.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback")
async def auth_callback(request: Request):
    if not config.AUTH_ENABLED:
        return RedirectResponse(url="/groups")

    token = await oauth.authentik.authorize_access_token(request)
    userinfo = token.get("userinfo") or await oauth.authentik.userinfo(token=token)

    request.session["user"] = {
        "email": userinfo.get("email"),
        "name": userinfo.get("name") or userinfo.get("preferred_username"),
        "groups": userinfo.get("groups", []),
    }
    logging.info(f"User logged in via OIDC: {userinfo.get('email')}")
    return RedirectResponse(url="/groups")


@router.get("/logout")
async def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse(url="/login")
