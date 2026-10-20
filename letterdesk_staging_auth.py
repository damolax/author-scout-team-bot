"""Stage-only Better Auth bridge for Letter Desk.

Why: first-party application session after email sign-in. Some browsers block
cross-site Neon Auth cookies, leaving a valid Neon session but no web session.
This bridge NEVER stores or logs a password. It validates provider's opaque
session token in the staging Neon DB before issuing a Letter Desk session.

Do not activate outside an isolated, read-only Letter Desk preview.
"""
from __future__ import annotations

import os
import re
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request

_RATE_LIMIT = defaultdict(deque)
_RATE_WINDOW = 15 * 60
_RATE_MAX = 7


def install_staging_email_auth(app: FastAPI, *, neon_session, get_or_create_account, issue_app_session):
    """Wire minimal staging-only email/password login through managed Neon Auth."""
    auth_base = os.getenv("NEON_AUTH_URL", "").rstrip("/")
    frontend_origin = os.getenv("LETTERDESK_STAGING_FRONTEND_ORIGIN", "").rstrip("/")
    target = urlparse(auth_base)
    if target.scheme != "https" or not target.netloc.endswith(".neon.tech") or "/auth" not in target.path:
        raise RuntimeError("NEON_AUTH_URL must be the managed Neon Auth HTTPS endpoint")
    if not frontend_origin.startswith("https://") or urlparse(frontend_origin).path not in ("", "/"):
        raise RuntimeError("LETTERDESK_STAGING_FRONTEND_ORIGIN is invalid")

    @app.post("/api/v2/letterdesk/auth/email")
    async def letterdesk_staging_email_signin(request: Request):
        if request.headers.get("origin", "").rstrip("/") != frontend_origin:
            raise HTTPException(status_code=403, detail="Request origin is not permitted")
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        entry = _RATE_LIMIT[key]
        while entry and now - entry[0] > _RATE_WINDOW:
            entry.popleft()
        if len(entry) >= _RATE_MAX:
            raise HTTPException(status_code=429, detail="Too many login attempts. Please try later.")
        entry.append(now)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid login request")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Invalid login request")
        email = str(body.get("email") or "").strip().lower()
        password = body.get("password")
        if not re.fullmatch(r"[^@\s]{1,120}@[^@\s]{1,120}\.[^@\s]{2,40}", email) or not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise HTTPException(status_code=400, detail="Enter a valid email address and password")
        mode = str(body.get("mode") or "signin")
        if mode not in ("signin", "signup"):
            raise HTTPException(status_code=400, detail="Unknown login mode")
        fields = {"email": email, "password": password}
        if mode == "signup":
            fields["name"] = str(body.get("name") or "").strip()[:100] or email.split("@")[0]

        endpoint = "/sign-in/email" if mode == "signin" else "/sign-up/email"
        try:
            async with httpx.AsyncClient(timeout=28.0, follow_redirects=False) as client:
                response = await client.post(
                    auth_base + endpoint, json=fields,
                    headers={"Origin": frontend_origin, "Content-Type": "application/json"},
                )
        except (httpx.TimeoutException, httpx.RequestError):
            raise HTTPException(status_code=503, detail="The login provider is temporarily unavailable")

        if response.status_code in (400, 401, 403, 422):
            # Do not mirror raw auth response; avoid user enumeration or token leaks.
            raise HTTPException(status_code=401, detail="Email or password was not accepted.")
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="Please wait before trying again.")
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="The login provider did not complete sign-in")

        try:
            provider_data = response.json()
        except ValueError:
            raise HTTPException(status_code=502, detail="The login provider returned an invalid response")
        result = provider_data.get("data") if isinstance(provider_data, dict) and isinstance(provider_data.get("data"), dict) else provider_data
        token = (
            result.get("token") or
            ((result.get("session") or {}).get("token") if isinstance(result.get("session"), dict) else "")
        ) if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise HTTPException(status_code=502, detail="The login provider did not issue a session. Please retry.")
        auth_session = neon_session(token)
        if not auth_session:
            raise HTTPException(status_code=401, detail="The login provider session could not be validated")
        profile = {
            "sub": "neon:" + str(auth_session["user_id"]),
            "email": auth_session["email"],
            "name": auth_session.get("name") or str(auth_session["email"]).split("@")[0],
        }
        account = get_or_create_account(profile)
        signed = issue_app_session(account)
        return {"ok": True, "session": signed, "display_name": account.get("display_name") or ""}
