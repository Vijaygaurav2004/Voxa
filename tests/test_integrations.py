"""
Tests for Voxa Integrations (Google / GitHub OAuth, token store, API routes,
bridge-token auth middleware, and dispatcher routing).
All network calls are mocked; disk state uses tmp_path — never ~/.voxa.
"""
import time
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest

# Skip server tests if httpx is not available
httpx = pytest.importorskip("httpx")

from voxa.config import config
from voxa.integrations.token_store import TokenStore


# ─── Fixtures & helpers ───────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    """Create a test client for the API server (no bridge token)."""
    monkeypatch.delenv("VOXA_BRIDGE_TOKEN", raising=False)
    from voxa.server import create_api_server
    from fastapi.testclient import TestClient

    app = create_api_server()
    return TestClient(app)


def _google_record(**overrides) -> dict:
    record = {
        "access_token": "ya29.SECRETTOKEN123",
        "refresh_token": "1//REFRESHSECRET456",
        "expires_at": time.time() + 3600,
        "scopes": [
            "openid", "email", "profile",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
        ],
        "account": {"email": "an@gmail.com", "name": "Anantha", "picture": "https://p.example/a.png"},
        "disabled_services": [],
    }
    record.update(overrides)
    return record


def _json_response(status_code=200, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    resp.text = str(payload)
    return resp


# ─── 1. TokenStore roundtrip ──────────────────────────────────────────────────

class TestTokenStore:
    def test_roundtrip_set_get_delete(self, tmp_path):
        store = TokenStore(tmp_path / "integrations.json")
        assert store.get("google") is None

        store.set("google", _google_record())
        rec = store.get("google")
        assert rec["access_token"] == "ya29.SECRETTOKEN123"
        assert rec["account"]["email"] == "an@gmail.com"

        store.delete("google")
        assert store.get("google") is None

    def test_file_mode_is_0600(self, tmp_path):
        path = tmp_path / "integrations.json"
        store = TokenStore(path)
        store.set("github", {"access_token": "ghp_x", "scopes": [], "account": {}})
        assert (path.stat().st_mode & 0o777) == 0o600

    def test_service_enable_disable(self, tmp_path):
        store = TokenStore(tmp_path / "integrations.json")
        store.set("google", _google_record())

        store.set_service_enabled("gmail", False)
        assert "gmail" in store.get("google")["disabled_services"]

        store.set_service_enabled("gmail", True)
        assert "gmail" not in store.get("google")["disabled_services"]

    def test_set_service_enabled_ignores_unknown_service(self, tmp_path):
        store = TokenStore(tmp_path / "integrations.json")
        store.set("google", _google_record())
        store.set_service_enabled("dropbox", False)
        assert store.get("google")["disabled_services"] == []


# ─── 2. Google token auto-refresh ─────────────────────────────────────────────

class TestGoogleTokenRefresh:
    def test_valid_token_returned_without_refresh(self, tmp_path):
        store = TokenStore(tmp_path / "integrations.json")
        store.set("google", _google_record())
        with patch("voxa.integrations.token_store.requests.post") as mock_post:
            assert store.get_google_access_token() == "ya29.SECRETTOKEN123"
            mock_post.assert_not_called()

    def test_expired_token_is_refreshed_and_persisted(self, tmp_path):
        store = TokenStore(tmp_path / "integrations.json")
        store.set("google", _google_record(expires_at=time.time() - 10))
        refresh_resp = _json_response(200, {"access_token": "ya29.NEWTOKEN", "expires_in": 3600})
        with patch("voxa.integrations.token_store.requests.post", return_value=refresh_resp) as mock_post:
            token = store.get_google_access_token()
        assert token == "ya29.NEWTOKEN"
        mock_post.assert_called_once()
        # New token persisted to disk
        assert store.get("google")["access_token"] == "ya29.NEWTOKEN"
        assert store.get("google")["expires_at"] > time.time() + 60

    def test_refresh_failure_returns_none(self, tmp_path):
        store = TokenStore(tmp_path / "integrations.json")
        store.set("google", _google_record(expires_at=time.time() - 10))
        with patch("voxa.integrations.token_store.requests.post", return_value=_json_response(400, {})):
            assert store.get_google_access_token() is None

    def test_no_record_returns_none(self, tmp_path):
        store = TokenStore(tmp_path / "integrations.json")
        assert store.get_google_access_token() is None


# ─── 3. begin_connect ─────────────────────────────────────────────────────────

class TestBeginConnect:
    def test_not_configured(self):
        from voxa.integrations import oauth
        with patch.object(config, "GOOGLE_CLIENT_ID", ""), \
             patch.object(config, "GOOGLE_CLIENT_SECRET", ""):
            result = oauth.begin_connect("google")
        assert result["success"] is False
        assert result["error"] == "not_configured"
        assert "GOOGLE_CLIENT_ID" in result["message"]

    def test_configured_returns_auth_url_with_state_and_pkce(self, tmp_path):
        from voxa.integrations import oauth
        with patch.object(config, "GOOGLE_CLIENT_ID", "cid"), \
             patch.object(config, "GOOGLE_CLIENT_SECRET", "sec"), \
             patch("voxa.integrations.token_store.token_store", TokenStore(tmp_path / "i.json")):
            result = oauth.begin_connect("google_calendar")
        assert result["success"] is True
        url = result["auth_url"]
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert query["state"][0]
        assert query["code_challenge"][0]
        assert query["code_challenge_method"][0] == "S256"
        assert query["access_type"][0] == "offline"
        assert query["include_granted_scopes"][0] == "true"
        # Requested service scope + identity scopes present
        assert "calendar.events" in query["scope"][0]
        assert "openid" in query["scope"][0]

    def test_github_not_configured(self):
        from voxa.integrations import oauth
        with patch.object(config, "GITHUB_CLIENT_ID", ""), \
             patch.object(config, "GITHUB_CLIENT_SECRET", ""):
            result = oauth.begin_connect("github")
        assert result["success"] is False
        assert result["error"] == "not_configured"

    def test_github_configured(self):
        from voxa.integrations import oauth
        with patch.object(config, "GITHUB_CLIENT_ID", "ghcid"), \
             patch.object(config, "GITHUB_CLIENT_SECRET", "ghsec"):
            result = oauth.begin_connect("github")
        assert result["success"] is True
        assert result["auth_url"].startswith("https://github.com/login/oauth/authorize?")


# ─── 4. handle_google_callback ────────────────────────────────────────────────

class TestGoogleCallback:
    def test_happy_path_stores_record(self, tmp_path):
        from voxa.integrations import oauth
        store = TokenStore(tmp_path / "i.json")

        with patch.object(config, "GOOGLE_CLIENT_ID", "cid"), \
             patch.object(config, "GOOGLE_CLIENT_SECRET", "sec"), \
             patch("voxa.integrations.token_store.token_store", store):
            begin = oauth.begin_connect("gmail")
            query = urllib.parse.parse_qs(urllib.parse.urlparse(begin["auth_url"]).query)
            state = query["state"][0]

            token_resp = _json_response(200, {
                "access_token": "ya29.NEW",
                "refresh_token": "1//refresh",
                "expires_in": 3599,
                "scope": "openid email profile https://www.googleapis.com/auth/gmail.send",
            })
            userinfo_resp = _json_response(200, {
                "email": "an@gmail.com", "name": "Anantha", "picture": "https://p/x.png",
            })
            with patch("voxa.integrations.oauth.requests.post", return_value=token_resp), \
                 patch("voxa.integrations.oauth.requests.get", return_value=userinfo_resp):
                result = oauth.handle_google_callback("the-code", state)

        assert result["success"] is True
        assert result["provider"] == "gmail"
        assert result["account"]["email"] == "an@gmail.com"

        rec = store.get("google")
        assert rec["access_token"] == "ya29.NEW"
        assert rec["refresh_token"] == "1//refresh"
        # Scopes parsed from the space-separated token response
        assert "https://www.googleapis.com/auth/gmail.send" in rec["scopes"]
        assert "email" in rec["scopes"]

    def test_refresh_token_merged_from_previous_record(self, tmp_path):
        from voxa.integrations import oauth
        store = TokenStore(tmp_path / "i.json")
        store.set("google", _google_record(refresh_token="1//KEEPME"))

        with patch.object(config, "GOOGLE_CLIENT_ID", "cid"), \
             patch.object(config, "GOOGLE_CLIENT_SECRET", "sec"), \
             patch("voxa.integrations.token_store.token_store", store):
            begin = oauth.begin_connect("google")
            state = urllib.parse.parse_qs(urllib.parse.urlparse(begin["auth_url"]).query)["state"][0]

            # Google omits refresh_token on re-consent
            token_resp = _json_response(200, {
                "access_token": "ya29.AGAIN", "expires_in": 3599, "scope": "openid email profile",
            })
            userinfo_resp = _json_response(200, {"email": "an@gmail.com", "name": "A", "picture": ""})
            with patch("voxa.integrations.oauth.requests.post", return_value=token_resp), \
                 patch("voxa.integrations.oauth.requests.get", return_value=userinfo_resp):
                result = oauth.handle_google_callback("code2", state)

        assert result["success"] is True
        assert store.get("google")["refresh_token"] == "1//KEEPME"

    def test_bad_state_returns_error(self):
        from voxa.integrations import oauth
        result = oauth.handle_google_callback("some-code", "not-a-real-state")
        assert result["success"] is False
        assert result["error"] == "invalid_state"


# ─── 5. GET /api/integrations ─────────────────────────────────────────────────

class TestIntegrationsEndpoint:
    def test_shape_and_no_secret_leakage(self, client, tmp_path):
        store = TokenStore(tmp_path / "i.json")
        store.set("google", _google_record())
        with patch.object(config, "GOOGLE_CLIENT_ID", "cid"), \
             patch.object(config, "GOOGLE_CLIENT_SECRET", "supersecret"), \
             patch.object(config, "GITHUB_CLIENT_ID", ""), \
             patch.object(config, "GITHUB_CLIENT_SECRET", ""), \
             patch("voxa.integrations.token_store.token_store", store):
            response = client.get("/api/integrations")

        assert response.status_code == 200
        data = response.json()
        ids = [p["id"] for p in data["providers"]]
        assert ids == ["google", "google_calendar", "gmail", "github"]
        for p in data["providers"]:
            for key in ("id", "name", "connected", "configured", "account_label", "avatar_url", "detail"):
                assert key in p

        google = data["providers"][0]
        assert google["connected"] is True
        assert google["account_label"] == "Anantha (an@gmail.com)"
        calendar = data["providers"][1]
        assert calendar["connected"] is True
        assert calendar["account_label"] == "an@gmail.com"
        github = data["providers"][3]
        assert github["connected"] is False
        assert github["configured"] is False
        assert "GITHUB_CLIENT_ID" in github["detail"]

        # No tokens or client secrets ever exposed
        body = response.text
        assert "SECRETTOKEN123" not in body
        assert "REFRESHSECRET" not in body
        assert "supersecret" not in body

    def test_disabled_service_shows_disconnected(self, client, tmp_path):
        store = TokenStore(tmp_path / "i.json")
        store.set("google", _google_record(disabled_services=["gmail"]))
        with patch.object(config, "GOOGLE_CLIENT_ID", "cid"), \
             patch.object(config, "GOOGLE_CLIENT_SECRET", "sec"), \
             patch("voxa.integrations.token_store.token_store", store):
            data = client.get("/api/integrations").json()
        gmail = [p for p in data["providers"] if p["id"] == "gmail"][0]
        assert gmail["connected"] is False
        assert gmail["detail"] == "Not connected"


# ─── 6. connect / disconnect endpoints ────────────────────────────────────────

class TestConnectDisconnectEndpoints:
    def test_connect_unknown_provider_returns_400(self, client):
        response = client.post("/api/integrations/facebook/connect")
        assert response.status_code == 400
        assert response.json()["success"] is False

    def test_disconnect_unknown_provider_returns_400(self, client):
        response = client.post("/api/integrations/facebook/disconnect")
        assert response.status_code == 400
        assert response.json()["success"] is False

    def test_connect_not_configured(self, client):
        with patch.object(config, "GOOGLE_CLIENT_ID", ""), \
             patch.object(config, "GOOGLE_CLIENT_SECRET", ""):
            response = client.post("/api/integrations/google/connect")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "not_configured"

    def test_connect_returns_auth_url(self, client, tmp_path):
        with patch.object(config, "GITHUB_CLIENT_ID", "ghcid"), \
             patch.object(config, "GITHUB_CLIENT_SECRET", "ghsec"):
            response = client.post("/api/integrations/github/connect")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["auth_url"].startswith("https://github.com/")

    def test_disconnect_google_service_disables_locally(self, client, tmp_path):
        store = TokenStore(tmp_path / "i.json")
        store.set("google", _google_record())
        with patch("voxa.integrations.token_store.token_store", store):
            response = client.post("/api/integrations/google_calendar/disconnect")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "google_calendar" in store.get("google")["disabled_services"]
        # Google record itself remains
        assert store.get("google")["access_token"]

    def test_disconnect_github_deletes_record(self, tmp_path):
        from voxa.integrations import oauth
        store = TokenStore(tmp_path / "i.json")
        store.set("github", {"access_token": "ghp_x", "scopes": [], "account": {"login": "me"}})
        with patch("voxa.integrations.token_store.token_store", store):
            result = oauth.disconnect("github")
        assert result["success"] is True
        assert store.get("github") is None

    def test_disconnect_google_revokes_and_deletes(self, tmp_path):
        from voxa.integrations import oauth
        store = TokenStore(tmp_path / "i.json")
        store.set("google", _google_record())
        with patch("voxa.integrations.token_store.token_store", store), \
             patch("voxa.integrations.oauth.requests.post", return_value=_json_response(200, {})) as mock_post:
            result = oauth.disconnect("google")
        assert result["success"] is True
        assert store.get("google") is None
        assert "revoke" in mock_post.call_args[0][0]


# ─── 7. Bridge auth middleware ────────────────────────────────────────────────

class TestBridgeAuthMiddleware:
    def test_token_required_when_env_set(self, monkeypatch):
        monkeypatch.setenv("VOXA_BRIDGE_TOKEN", "sekret-token")
        from voxa.server import create_api_server
        from fastapi.testclient import TestClient

        client = TestClient(create_api_server())

        # /api/* without the header → 401
        assert client.get("/api/context").status_code == 401
        # With the correct header → allowed through
        assert client.get("/api/context", headers={"X-Voxa-Token": "sekret-token"}).status_code == 200
        # Wrong token → 401
        assert client.get("/api/context", headers={"X-Voxa-Token": "wrong"}).status_code == 401
        # /api/health is always open
        assert client.get("/api/health").status_code == 200
        # OAuth callback pages must stay reachable from the browser (may be 400
        # for a bad/missing state, but never 401)
        assert client.get("/api/auth/google/callback").status_code != 401
        assert client.get("/api/auth/github/callback").status_code != 401

    def test_everything_open_when_env_unset(self, client):
        # `client` fixture deletes VOXA_BRIDGE_TOKEN
        assert client.get("/api/context").status_code == 200
        assert client.get("/api/health").status_code == 200


# ─── 8. Dispatcher routing ────────────────────────────────────────────────────

class TestDispatcherIntegrations:
    def _make_action(self, action_type, **kwargs):
        from voxa.intelligence.intent_parser import Action
        return Action(action=action_type, description="test", **kwargs)

    def test_calendar_create_event_routes_to_google_client(self):
        from voxa.actions import dispatcher
        from voxa.intelligence.intent_parser import ActionType

        action = self._make_action(
            ActionType.CALENDAR_CREATE_EVENT,
            event_title="Standup",
            event_start="2026-07-23T15:00:00",
            event_end="2026-07-23T15:30:00",
        )
        with patch("voxa.integrations.google_client.create_calendar_event",
                   return_value={"success": True, "message": "Added 'Standup' to your Google Calendar."}) as m:
            result = dispatcher.execute_action(action)
        m.assert_called_once()
        assert m.call_args.kwargs["title"] == "Standup"
        assert result["success"] is True

    def test_calendar_create_event_falls_back_to_browser_template(self):
        from voxa.actions import dispatcher
        from voxa.intelligence.intent_parser import ActionType

        action = self._make_action(
            ActionType.CALENDAR_CREATE_EVENT,
            event_title="Standup",
            event_start="2026-07-23T15:00:00",
            event_end="2026-07-23T15:30:00",
        )
        with patch("voxa.integrations.google_client.create_calendar_event",
                   return_value={"success": False, "not_connected": True, "message": "not connected"}), \
             patch("voxa.actions.browser.open_url", return_value={"success": True, "message": ""}) as m_open:
            result = dispatcher.execute_action(action)
        m_open.assert_called_once()
        url = m_open.call_args[0][0]
        assert "calendar.google.com/calendar/render" in url
        assert "20260723T150000%2F20260723T153000" in url
        assert result["success"] is True
        assert "connect Google Calendar" in result["message"]

    def test_gmail_send_routes_to_google_client(self):
        from voxa.actions import dispatcher
        from voxa.intelligence.intent_parser import ActionType

        action = self._make_action(
            ActionType.GMAIL_SEND,
            email_to="a@b.c", email_subject="Hi", email_body="Body",
        )
        with patch("voxa.integrations.google_client.send_gmail",
                   return_value={"success": True, "message": "Email sent to a@b.c."}) as m:
            result = dispatcher.execute_action(action)
        m.assert_called_once_with(to="a@b.c", subject="Hi", body="Body")
        assert result["success"] is True

    def test_gmail_send_falls_back_to_compose_when_not_connected(self):
        from voxa.actions import dispatcher
        from voxa.intelligence.intent_parser import ActionType

        action = self._make_action(
            ActionType.GMAIL_SEND,
            email_to="a@b.c", email_subject="Hi", email_body="Body",
        )
        with patch("voxa.integrations.google_client.send_gmail",
                   return_value={"success": False, "not_connected": True, "message": "not connected"}), \
             patch("voxa.actions.email.compose_email",
                   return_value={"success": True, "message": "Opened email compose"}) as m_compose:
            result = dispatcher.execute_action(action)
        m_compose.assert_called_once_with(to="a@b.c", subject="Hi", body="Body")
        assert result["success"] is True

    def test_gmail_unread_routes_to_google_client(self):
        from voxa.actions import dispatcher
        from voxa.intelligence.intent_parser import ActionType

        action = self._make_action(ActionType.GMAIL_UNREAD)
        with patch("voxa.integrations.google_client.get_unread_summary",
                   return_value={"success": True, "message": "No unread emails."}) as m:
            result = dispatcher.execute_action(action)
        m.assert_called_once()
        assert result["success"] is True

    def test_github_notifications_routes_to_github_client(self):
        from voxa.actions import dispatcher
        from voxa.intelligence.intent_parser import ActionType

        action = self._make_action(ActionType.GITHUB_NOTIFICATIONS)
        with patch("voxa.integrations.github_client.get_notifications_summary",
                   return_value={"success": True, "message": "No new GitHub notifications."}) as m:
            result = dispatcher.execute_action(action)
        m.assert_called_once()
        assert result["success"] is True

    def test_new_actions_are_python_classified(self):
        from voxa.intelligence.intent_parser import ActionType, classify_action
        for at in (ActionType.CALENDAR_CREATE_EVENT, ActionType.GMAIL_SEND,
                   ActionType.GMAIL_UNREAD, ActionType.GITHUB_NOTIFICATIONS):
            assert classify_action(at) == "python"

    def test_speak_result_actions_include_new_queries(self):
        from voxa.actions.dispatcher import SPEAK_RESULT_ACTIONS
        from voxa.intelligence.intent_parser import ActionType
        assert ActionType.CALENDAR_CREATE_EVENT in SPEAK_RESULT_ACTIONS
        assert ActionType.GMAIL_UNREAD in SPEAK_RESULT_ACTIONS
        assert ActionType.GITHUB_NOTIFICATIONS in SPEAK_RESULT_ACTIONS
