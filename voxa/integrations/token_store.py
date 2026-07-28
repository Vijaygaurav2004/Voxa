"""
Token Store for Voxa Integrations.
Persists OAuth token records (Google, GitHub) in ~/.voxa/integrations.json,
written with mode 0o600. Handles automatic Google access-token refresh.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import requests

from voxa.utils.logger import get_logger

log = get_logger("integrations.store")

# Google services that ride on the single "google" token record.
GOOGLE_SERVICES = ("google_calendar", "gmail")

# Refresh the Google access token when it expires within this many seconds.
_REFRESH_MARGIN_SECONDS = 60


class TokenStore:
    """
    Reads/writes integration token records on disk.

    JSON shape:
        {
          "google": {access_token, refresh_token, expires_at, scopes,
                     account: {email, name, picture}, disabled_services: []},
          "github": {access_token, scopes, account: {login, name, avatar_url}}
        }
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else (Path.home() / ".voxa" / "integrations.json")

    # ── Disk I/O ──────────────────────────────────────────────────────────────

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except Exception as e:
            log.error("Failed to read %s: %s", self.path, e)
            return {}

    def _write(self, data: dict):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Create owner-only from the start — never a 0o644 window with tokens inside.
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.chmod(self.path, 0o600)  # tighten pre-existing files too
        except Exception as e:
            log.error("Failed to write %s: %s", self.path, e)

    # ── Record CRUD ───────────────────────────────────────────────────────────

    def get(self, provider: str) -> Optional[dict]:
        """Return the stored record for a provider, or None."""
        return self._read().get(provider)

    def set(self, provider: str, record: dict):
        """Store (replace) the record for a provider."""
        data = self._read()
        data[provider] = record
        self._write(data)

    def delete(self, provider: str):
        """Delete a provider's record (no-op if absent)."""
        data = self._read()
        if provider in data:
            del data[provider]
            self._write(data)

    def set_service_enabled(self, service: str, enabled: bool):
        """Enable/disable a Google service (google_calendar / gmail) locally."""
        if service not in GOOGLE_SERVICES:
            return
        data = self._read()
        record = data.get("google")
        if not record:
            return
        disabled = [s for s in record.get("disabled_services", []) if s != service]
        if not enabled:
            disabled.append(service)
        record["disabled_services"] = disabled
        self._write(data)

    # ── Access Tokens ─────────────────────────────────────────────────────────

    def get_google_access_token(self) -> Optional[str]:
        """
        Return a valid Google access token, refreshing it with the stored
        refresh_token when it expires within 60s. Returns None if no record
        exists or the refresh fails.
        """
        record = self.get("google")
        if not record:
            return None

        expires_at = float(record.get("expires_at") or 0)
        if expires_at - time.time() > _REFRESH_MARGIN_SECONDS:
            return record.get("access_token")

        refresh_token = record.get("refresh_token")
        if not refresh_token:
            log.warning("Google token expired and no refresh_token stored")
            return None

        try:
            from voxa.config import config
            resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": config.GOOGLE_CLIENT_ID,
                    "client_secret": config.GOOGLE_CLIENT_SECRET,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                log.error("Google token refresh failed (%d): %s", resp.status_code, resp.text[:200])
                return None
            payload = resp.json()
            record["access_token"] = payload.get("access_token", "")
            record["expires_at"] = time.time() + float(payload.get("expires_in", 3600))
            self.set("google", record)
            log.info("🔄 Refreshed Google access token")
            return record["access_token"]
        except Exception as e:
            log.error("Google token refresh error: %s", e)
            return None

    def get_github_access_token(self) -> Optional[str]:
        """Return the stored GitHub access token, or None."""
        record = self.get("github")
        return record.get("access_token") if record else None


# Singleton instance
token_store = TokenStore()
