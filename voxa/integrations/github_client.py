"""
GitHub API Client for Voxa Integrations.
Notifications and open-PR summaries via the REST API (requests only).
Tokens come from the token store; every function returns a uniform
{success, action, message, ...} dict with a TTS-friendly message.
"""
from __future__ import annotations

from typing import Optional

import requests

from voxa.utils.logger import get_logger

log = get_logger("integrations.github")

_API_BASE = "https://api.github.com"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def get_user(token: str) -> dict:
    """Fetch the GitHub account profile for an access token."""
    resp = requests.get(f"{_API_BASE}/user", headers=_headers(token), timeout=15)
    return resp.json() if resp.status_code == 200 else {}


def _get_token() -> Optional[str]:
    from voxa.integrations.token_store import token_store
    return token_store.get_github_access_token()


_NOT_CONNECTED = "GitHub isn't connected — open Voxa Settings → Accounts to connect it."


def get_notifications_summary(max_results: int = 10) -> dict:
    """Summarize unread GitHub notifications (repo + subject for the newest few)."""
    token = _get_token()
    if not token:
        return {"success": False, "not_connected": True,
                "action": "github_notifications", "message": _NOT_CONNECTED}

    try:
        resp = requests.get(
            f"{_API_BASE}/notifications",
            headers=_headers(token),
            params={"per_page": max_results},
            timeout=20,
        )
        if resp.status_code >= 400:
            log.error("GitHub notifications failed (%d): %s", resp.status_code, resp.text[:200])
            return {"success": False, "action": "github_notifications",
                    "message": "Couldn't fetch your GitHub notifications."}
        items = resp.json()
        if not items:
            return {"success": True, "action": "github_notifications",
                    "message": "No new GitHub notifications.", "count": 0}
        lines = []
        for n in items[:5]:
            repo = n.get("repository", {}).get("full_name", "unknown repo")
            title = n.get("subject", {}).get("title", "(no title)")
            lines.append(f"{repo}: {title}")
        summary = f"You have {len(items)} GitHub notification(s). " + "; ".join(lines)
        return {"success": True, "action": "github_notifications",
                "message": summary, "count": len(items)}
    except Exception as e:
        log.error("GitHub notifications error: %s", e)
        return {"success": False, "action": "github_notifications",
                "message": f"Couldn't fetch GitHub notifications: {e}"}


def get_open_prs_summary(max_results: int = 10) -> dict:
    """Summarize the user's open pull requests."""
    token = _get_token()
    if not token:
        return {"success": False, "not_connected": True,
                "action": "github_open_prs", "message": _NOT_CONNECTED}

    try:
        resp = requests.get(
            f"{_API_BASE}/search/issues",
            headers=_headers(token),
            params={"q": "is:pr is:open author:@me", "per_page": max_results},
            timeout=20,
        )
        if resp.status_code >= 400:
            log.error("GitHub open PRs failed (%d): %s", resp.status_code, resp.text[:200])
            return {"success": False, "action": "github_open_prs",
                    "message": "Couldn't fetch your open pull requests."}
        data = resp.json()
        items = data.get("items", [])
        total = data.get("total_count", len(items))
        if not items:
            return {"success": True, "action": "github_open_prs",
                    "message": "You have no open pull requests.", "count": 0}
        lines = [f"{pr.get('title', '(no title)')}" for pr in items[:5]]
        summary = f"You have {total} open pull request(s): " + "; ".join(lines)
        return {"success": True, "action": "github_open_prs",
                "message": summary, "count": total}
    except Exception as e:
        log.error("GitHub open PRs error: %s", e)
        return {"success": False, "action": "github_open_prs",
                "message": f"Couldn't fetch open pull requests: {e}"}
