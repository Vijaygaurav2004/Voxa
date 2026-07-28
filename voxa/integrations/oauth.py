"""
OAuth Flows for Voxa Integrations.
Google (identity + Calendar + Gmail via incremental auth) and GitHub, using
loopback redirects on the existing FastAPI server (config.API_SERVER_PORT).
Zero extra dependencies — all HTTP via requests.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
from typing import Optional

import requests

from voxa.config import config
from voxa.utils.logger import get_logger

log = get_logger("integrations.oauth")

# All known provider ids (order = display order in the UI)
PROVIDERS = ("google", "google_calendar", "gmail", "github")

PROVIDER_NAMES = {
    "google": "Google Account",
    "google_calendar": "Google Calendar",
    "gmail": "Gmail",
    "github": "GitHub",
}

# Google scopes
GOOGLE_IDENTITY_SCOPES = ["openid", "email", "profile"]
GOOGLE_SERVICE_SCOPES = {
    "google_calendar": ["https://www.googleapis.com/auth/calendar.events"],
    "gmail": [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
    ],
}
GITHUB_SCOPES = ["read:user", "repo", "notifications"]

# Pending OAuth states: {state: {provider, code_verifier, created}}
_pending_states: dict[str, dict] = {}
_STATE_TTL_SECONDS = 600  # 10 minutes


def _redirect_uri(provider_family: str) -> str:
    """Loopback redirect URI on the existing API server."""
    return f"http://127.0.0.1:{config.API_SERVER_PORT}/api/auth/{provider_family}/callback"


def _prune_states():
    now = time.time()
    for state in [s for s, p in _pending_states.items() if now - p["created"] > _STATE_TTL_SECONDS]:
        del _pending_states[state]


def _pop_state(state: str) -> Optional[dict]:
    """Validate and consume a pending OAuth state. Returns pending info or None."""
    _prune_states()
    return _pending_states.pop(state, None) if state else None


# ─── Status ──────────────────────────────────────────────────────────────────────

def _google_service_connected(record: Optional[dict], service: str) -> bool:
    """A Google service is connected when the google record exists, its scope
    was granted, and the service hasn't been disabled locally."""
    if not record:
        return False
    if service in record.get("disabled_services", []):
        return False
    scopes = record.get("scopes", [])
    return any(s in scopes for s in GOOGLE_SERVICE_SCOPES[service])


def provider_status() -> dict:
    """Build the GET /api/integrations payload. Never includes tokens/secrets."""
    from voxa.integrations.token_store import token_store

    google_record = token_store.get("google")
    github_record = token_store.get("github")
    google_configured = bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)
    github_configured = bool(config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET)

    google_account = (google_record or {}).get("account", {})
    google_email = google_account.get("email")
    google_name = google_account.get("name")
    google_label = None
    if google_record:
        google_label = f"{google_name} ({google_email})" if google_name and google_email else google_email

    providers = []

    providers.append({
        "id": "google",
        "name": PROVIDER_NAMES["google"],
        "connected": bool(google_record),
        "configured": google_configured,
        "account_label": google_label,
        "avatar_url": google_account.get("picture") if google_record else None,
        "detail": None if google_record else (
            "Not signed in" if google_configured else "Add GOOGLE_CLIENT_ID to ~/.voxa/.env"
        ),
    })

    for service in ("google_calendar", "gmail"):
        connected = _google_service_connected(google_record, service)
        providers.append({
            "id": service,
            "name": PROVIDER_NAMES[service],
            "connected": connected,
            "configured": google_configured,
            "account_label": google_email if connected else None,
            "avatar_url": None,
            "detail": None if connected else (
                "Not connected" if google_configured else "Add GOOGLE_CLIENT_ID to ~/.voxa/.env"
            ),
        })

    github_account = (github_record or {}).get("account", {})
    providers.append({
        "id": "github",
        "name": PROVIDER_NAMES["github"],
        "connected": bool(github_record),
        "configured": github_configured,
        "account_label": github_account.get("login") if github_record else None,
        "avatar_url": github_account.get("avatar_url") if github_record else None,
        "detail": None if github_record else (
            "Not connected" if github_configured else "Add GITHUB_CLIENT_ID to ~/.voxa/.env"
        ),
    })

    return {"providers": providers}


def integrations_context() -> str:
    """One-line summary of connected integrations for the LLM system prompt."""
    from voxa.integrations.token_store import token_store

    google_record = token_store.get("google")
    connected = []
    for service in ("google_calendar", "gmail"):
        if _google_service_connected(google_record, service):
            connected.append(PROVIDER_NAMES[service])
    if token_store.get("github"):
        connected.append(PROVIDER_NAMES["github"])
    if not connected:
        return "No integrations connected."
    return "Connected integrations: " + ", ".join(connected)


# ─── Connect ─────────────────────────────────────────────────────────────────────

def begin_connect(provider: str) -> dict:
    """
    Start an OAuth flow for a provider. Returns {success, auth_url} or a
    not_configured error the UI can show.
    """
    from voxa.integrations.token_store import token_store

    if provider not in PROVIDERS:
        return {"success": False, "error": "unknown_provider",
                "message": f"Unknown provider '{provider}'"}

    state = secrets.token_urlsafe(24)

    if provider == "github":
        if not (config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET):
            return {
                "success": False,
                "error": "not_configured",
                "message": "Add GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET to ~/.voxa/.env (see README)",
            }
        _pending_states[state] = {"provider": "github", "code_verifier": None, "created": time.time()}
        params = {
            "client_id": config.GITHUB_CLIENT_ID,
            "redirect_uri": _redirect_uri("github"),
            "scope": " ".join(GITHUB_SCOPES),
            "state": state,
        }
        auth_url = "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(params)
        return {"success": True, "auth_url": auth_url}

    # Google family (google / google_calendar / gmail)
    if not (config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET):
        return {
            "success": False,
            "error": "not_configured",
            "message": "Add GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET to ~/.voxa/.env (see README)",
        }

    # PKCE: S256 challenge from a random verifier
    code_verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    _pending_states[state] = {"provider": provider, "code_verifier": code_verifier, "created": time.time()}

    # Scope = identity scopes + requested service scopes + already-granted scopes
    scopes = list(GOOGLE_IDENTITY_SCOPES)
    for s in GOOGLE_SERVICE_SCOPES.get(provider, []):
        if s not in scopes:
            scopes.append(s)
    existing = token_store.get("google") or {}
    for s in existing.get("scopes", []):
        if s not in scopes:
            scopes.append(s)

    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": _redirect_uri("google"),
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return {"success": True, "auth_url": auth_url}


# ─── Callbacks ───────────────────────────────────────────────────────────────────

def handle_google_callback(code: str, state: str) -> dict:
    """Exchange a Google auth code for tokens, fetch account info, store record."""
    from voxa.integrations.token_store import token_store

    pending = _pop_state(state)
    if not pending or pending["provider"] == "github":
        return {"success": False, "error": "invalid_state",
                "message": "Invalid or expired sign-in attempt. Try connecting again from Voxa."}

    try:
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "redirect_uri": _redirect_uri("google"),
                "code_verifier": pending["code_verifier"],
            },
            timeout=20,
        )
        if resp.status_code != 200:
            log.error("Google token exchange failed (%d): %s", resp.status_code, resp.text[:200])
            return {"success": False, "message": "Google sign-in failed during token exchange."}
        payload = resp.json()

        access_token = payload.get("access_token", "")
        scopes = [s for s in (payload.get("scope") or "").split(" ") if s]

        userinfo_resp = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        account = userinfo_resp.json() if userinfo_resp.status_code == 200 else {}

        # Google may omit refresh_token on re-consent — keep the previous one.
        previous = token_store.get("google") or {}
        refresh_token = payload.get("refresh_token") or previous.get("refresh_token", "")
        for s in previous.get("scopes", []):
            if s not in scopes:
                scopes.append(s)

        record = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": time.time() + float(payload.get("expires_in", 3600)),
            "scopes": scopes,
            "account": {
                "email": account.get("email", ""),
                "name": account.get("name", ""),
                "picture": account.get("picture", ""),
            },
            "disabled_services": previous.get("disabled_services", []),
        }
        # Connecting a service re-enables it if it was disabled locally.
        service = pending["provider"]
        if service in record["disabled_services"]:
            record["disabled_services"] = [s for s in record["disabled_services"] if s != service]
        token_store.set("google", record)

        log.info("✅ Google connected (%s) as %s", service, record["account"].get("email"))
        return {"success": True, "provider": service, "account": record["account"]}
    except Exception as e:
        log.error("Google callback error: %s", e)
        return {"success": False, "message": f"Google sign-in failed: {e}"}


def handle_github_callback(code: str, state: str) -> dict:
    """Exchange a GitHub auth code for a token, fetch account info, store record."""
    from voxa.integrations.token_store import token_store

    pending = _pop_state(state)
    if not pending or pending["provider"] != "github":
        return {"success": False, "error": "invalid_state",
                "message": "Invalid or expired sign-in attempt. Try connecting again from Voxa."}

    try:
        resp = requests.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": config.GITHUB_CLIENT_ID,
                "client_secret": config.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": _redirect_uri("github"),
            },
            headers={"Accept": "application/json"},
            timeout=20,
        )
        if resp.status_code != 200:
            log.error("GitHub token exchange failed (%d): %s", resp.status_code, resp.text[:200])
            return {"success": False, "message": "GitHub sign-in failed during token exchange."}
        payload = resp.json()
        access_token = payload.get("access_token", "")
        if not access_token:
            return {"success": False, "message": "GitHub sign-in failed — no access token returned."}
        scopes = [s for s in (payload.get("scope") or "").replace(",", " ").split(" ") if s]

        user_resp = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
            timeout=15,
        )
        account = user_resp.json() if user_resp.status_code == 200 else {}

        record = {
            "access_token": access_token,
            "scopes": scopes or GITHUB_SCOPES,
            "account": {
                "login": account.get("login", ""),
                "name": account.get("name", ""),
                "avatar_url": account.get("avatar_url", ""),
            },
        }
        token_store.set("github", record)

        log.info("✅ GitHub connected as %s", record["account"].get("login"))
        return {"success": True, "provider": "github", "account": record["account"]}
    except Exception as e:
        log.error("GitHub callback error: %s", e)
        return {"success": False, "message": f"GitHub sign-in failed: {e}"}


# ─── Disconnect ──────────────────────────────────────────────────────────────────

def disconnect(provider: str) -> dict:
    """
    Disconnect a provider. Google services are only disabled locally; the
    Google account revokes + deletes the token (dropping calendar/gmail too).
    """
    from voxa.integrations.token_store import token_store

    if provider not in PROVIDERS:
        return {"success": False, "error": "unknown_provider",
                "message": f"Unknown provider '{provider}'"}

    if provider in ("google_calendar", "gmail"):
        token_store.set_service_enabled(provider, False)
        return {"success": True, "provider": provider,
                "message": f"{PROVIDER_NAMES[provider]} disconnected."}

    if provider == "google":
        record = token_store.get("google")
        if record and record.get("access_token"):
            try:
                requests.post(
                    "https://oauth2.googleapis.com/revoke",
                    data={"token": record["access_token"]},
                    timeout=15,
                )
            except Exception as e:
                log.warning("Google token revoke failed: %s", e)
        token_store.delete("google")
        return {"success": True, "provider": "google", "message": "Google account signed out."}

    # github
    token_store.delete("github")
    return {"success": True, "provider": "github", "message": "GitHub disconnected."}
