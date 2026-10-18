from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learngraph.ingestion_api.auth import AuthConfig, AuthManager, TokenState


class _FakeResponse:
    def __init__(self, status_code: int, body: dict[str, object]):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self) -> dict[str, object]:
        return self._body


def _auth_config(tmp_path):
    return AuthConfig(
        keycloak_base_url="http://keycloak.test",
        realm="learngraph",
        client_id="learngraph-cli",
        client_secret=None,
        scope="openid offline_access",
        timeout_s=5,
        token_path=tmp_path / "auth.json",
    )


def test_device_login_handles_pending_and_offline_refresh(monkeypatch, tmp_path):
    cfg = _auth_config(tmp_path)
    manager = AuthManager(cfg)

    calls = {"token": 0}

    def fake_post(url, data, timeout):
        if url.endswith("/auth/device"):
            return _FakeResponse(
                200,
                {
                    "device_code": "dev-code",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://kc.test/device",
                    "verification_uri_complete": "https://kc.test/device?user_code=ABCD-EFGH",
                    "expires_in": 600,
                    "interval": 1,
                },
            )
        calls["token"] += 1
        if calls["token"] == 1:
            return _FakeResponse(400, {"error": "authorization_pending"})
        return _FakeResponse(
            200,
            {
                "access_token": "access-1",
                "token_type": "Bearer",
                "expires_in": 600,
                "refresh_token": "refresh-1",
                "refresh_expires_in": 0,
            },
        )

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda _: None)

    token = manager.login_interactive()

    assert token.access_token == "access-1"
    assert token.refresh_token == "refresh-1"
    assert token.refresh_expires_at is None
    assert token.refresh_valid()


def test_refresh_keeps_previous_refresh_token_when_response_omits_it(monkeypatch, tmp_path):
    cfg = _auth_config(tmp_path)
    manager = AuthManager(cfg)
    now = datetime.now(UTC)
    manager.store.save(
        TokenState(
            access_token="old-access",
            token_type="Bearer",
            access_expires_at=now - timedelta(minutes=1),
            refresh_token="stable-refresh",
            refresh_expires_at=now + timedelta(days=30),
        )
    )

    def fake_post(url, data, timeout):
        return _FakeResponse(
            200,
            {
                "access_token": "new-access",
                "token_type": "Bearer",
                "expires_in": 600,
            },
        )

    monkeypatch.setattr("requests.post", fake_post)

    header = manager.authorization_header()
    saved = manager.store.load()

    assert header == "Bearer new-access"
    assert saved is not None
    assert saved.refresh_token == "stable-refresh"
    assert saved.refresh_expires_at is not None


def test_status_refreshes_expired_access_token(monkeypatch, tmp_path):
    cfg = _auth_config(tmp_path)
    manager = AuthManager(cfg)
    now = datetime.now(UTC)
    manager.store.save(
        TokenState(
            access_token="old-access",
            token_type="Bearer",
            access_expires_at=now - timedelta(minutes=1),
            refresh_token="stable-refresh",
            refresh_expires_at=now + timedelta(days=30),
        )
    )

    def fake_post(url, data, timeout):
        return _FakeResponse(
            200,
            {
                "access_token": "new-access",
                "token_type": "Bearer",
                "expires_in": 600,
                "refresh_token": "stable-refresh",
                "refresh_expires_in": 2592000,
            },
        )

    monkeypatch.setattr("requests.post", fake_post)

    is_valid, token = manager.status()
    saved = manager.store.load()

    assert is_valid is True
    assert token is not None
    assert token.access_token == "new-access"
    assert saved is not None
    assert saved.access_token == "new-access"
    assert saved.refresh_token == "stable-refresh"
