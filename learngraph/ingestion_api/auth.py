from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests


class AuthError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_expiry(seconds: int | float | None) -> datetime:
    safe_seconds = int(seconds or 0)
    return _utc_now() + timedelta(seconds=max(0, safe_seconds))


def _default_token_path() -> Path:
    custom = os.getenv("LEARNGRAPH_AUTH_TOKEN_PATH")
    if custom:
        return Path(custom).expanduser()
    return Path("~/.config/learngraph/auth.json").expanduser()


@dataclass(frozen=True)
class AuthConfig:
    keycloak_base_url: str
    realm: str
    client_id: str
    client_secret: str | None
    scope: str
    timeout_s: float
    token_path: Path

    @staticmethod
    def from_env() -> "AuthConfig":
        base = os.getenv("LEARNGRAPH_AUTH_BASE_URL", "").strip().rstrip("/")
        if not base:
            raise AuthError(
                "Missing LEARNGRAPH_AUTH_BASE_URL. "
                "Set it to your Keycloak base URL, e.g. http://localhost:8083."
            )

        return AuthConfig(
            keycloak_base_url=base,
            realm=os.getenv("LEARNGRAPH_AUTH_REALM", "learngraph-staging").strip(),
            client_id=os.getenv("LEARNGRAPH_AUTH_CLIENT_ID", "learngraph-cli").strip(),
            client_secret=os.getenv("LEARNGRAPH_AUTH_CLIENT_SECRET") or None,
            scope=os.getenv("LEARNGRAPH_AUTH_SCOPE", "openid profile email organization offline_access").strip(),
            timeout_s=float(os.getenv("LEARNGRAPH_AUTH_TIMEOUT_S", "20")),
            token_path=_default_token_path(),
        )

    @property
    def token_url(self) -> str:
        return f"{self.keycloak_base_url}/realms/{self.realm}/protocol/openid-connect/token"

    @property
    def device_auth_url(self) -> str:
        return f"{self.keycloak_base_url}/realms/{self.realm}/protocol/openid-connect/auth/device"


@dataclass(frozen=True)
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    interval: int


@dataclass
class TokenState:
    access_token: str
    token_type: str
    access_expires_at: datetime
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None

    @property
    def authorization_header(self) -> str:
        return f"Bearer {self.access_token}"

    def access_valid(self, skew_seconds: int = 30) -> bool:
        return self.access_expires_at > (_utc_now() + timedelta(seconds=skew_seconds))

    def refresh_valid(self, skew_seconds: int = 30) -> bool:
        if not self.refresh_token:
            return False
        # Keycloak may return refresh_expires_in=0 for offline tokens.
        # Treat missing expiry as unbounded/unknown instead of immediately expired.
        if self.refresh_expires_at is None:
            return True
        return self.refresh_expires_at > (_utc_now() + timedelta(seconds=skew_seconds))

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "access_expires_at": self.access_expires_at.isoformat(),
            "refresh_token": self.refresh_token,
            "refresh_expires_at": self.refresh_expires_at.isoformat() if self.refresh_expires_at else None,
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "TokenState":
        refresh_expires_at_raw = payload.get("refresh_expires_at")
        refresh_expires_at = None
        if refresh_expires_at_raw:
            refresh_expires_at = datetime.fromisoformat(refresh_expires_at_raw)
        return TokenState(
            access_token=payload["access_token"],
            token_type=payload.get("token_type", "Bearer"),
            access_expires_at=datetime.fromisoformat(payload["access_expires_at"]),
            refresh_token=payload.get("refresh_token"),
            refresh_expires_at=refresh_expires_at,
        )


class TokenStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> TokenState | None:
        if not self.path.exists():
            return None
        with self.path.open("r", encoding="utf-8") as fh:
            return TokenState.from_dict(json.load(fh))

    def save(self, state: TokenState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2)
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        tmp_path.replace(self.path)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class AuthManager:
    def __init__(self, config: AuthConfig):
        self.config = config
        self.store = TokenStore(config.token_path)

    def login_interactive(self) -> TokenState:
        device = self._request_device_code()
        print("Open this URL to authenticate:")
        print(f"  {device.verification_uri_complete or device.verification_uri}")
        print(f"Then enter code: {device.user_code}")
        token = self._poll_device_code(device)
        self.store.save(token)
        return token

    def logout(self) -> None:
        self.store.clear()

    def status(self) -> tuple[bool, TokenState | None]:
        token = self.store.load()
        if token is None:
            return False, None
        if token.access_valid():
            return True, token
        if token.refresh_valid():
            refreshed = self._refresh(
                token.refresh_token or "",
                previous_refresh_expires_at=token.refresh_expires_at,
            )
            self.store.save(refreshed)
            return True, refreshed
        return False, token

    def userinfo(self) -> dict[str, Any]:
        """Call the Keycloak userinfo endpoint with the current access token."""
        url = (
            f"{self.config.keycloak_base_url}/realms/{self.config.realm}"
            "/protocol/openid-connect/userinfo"
        )
        try:
            response = requests.get(
                url,
                headers={"Authorization": self.authorization_header()},
                timeout=self.config.timeout_s,
            )
        except requests.RequestException as exc:
            raise AuthError(f"Userinfo request failed: {exc}") from exc
        if response.status_code >= 400:
            raise AuthError(
                f"Userinfo failed ({response.status_code}): {response.text.strip()}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise AuthError("Userinfo response was not JSON.") from exc
        if not isinstance(body, dict):
            raise AuthError("Userinfo response was not a JSON object.")
        return body

    def access_token(self) -> str:
        """Return the current access token, refreshing it when the refresh token is still valid."""
        return self._current_token().access_token

    def authorization_header(self) -> str:
        return f"Bearer {self.access_token()}"

    def _current_token(self) -> TokenState:
        token = self.store.load()
        if token is None:
            raise AuthError("Not logged in. Run: learngraph auth login")
        if token.access_valid():
            return token
        if token.refresh_valid():
            refreshed = self._refresh(
                token.refresh_token or "",
                previous_refresh_expires_at=token.refresh_expires_at,
            )
            self.store.save(refreshed)
            return refreshed
        raise AuthError("Token expired. Run: learngraph auth login")

    def _request_device_code(self) -> DeviceAuthorization:
        payload = {
            "client_id": self.config.client_id,
            "scope": self.config.scope,
        }
        if self.config.client_secret:
            payload["client_secret"] = self.config.client_secret
        try:
            response = requests.post(
                self.config.device_auth_url,
                data=payload,
                timeout=self.config.timeout_s,
            )
        except requests.RequestException as exc:
            raise AuthError(f"Device auth request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text.strip()
            raise AuthError(f"Device auth failed ({response.status_code}): {detail}")

        body = response.json()
        device_code = body.get("device_code")
        user_code = body.get("user_code")
        verification_uri = body.get("verification_uri")
        if not device_code or not user_code or not verification_uri:
            raise AuthError("Device auth response missing required fields.")
        try:
            expires_in = int(body.get("expires_in", 0))
            interval = int(body.get("interval", 5))
        except (TypeError, ValueError) as exc:
            raise AuthError("Device auth response contains invalid timings.") from exc
        return DeviceAuthorization(
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            verification_uri_complete=body.get("verification_uri_complete"),
            expires_in=max(1, expires_in),
            interval=max(1, interval),
        )

    def _poll_device_code(self, device: DeviceAuthorization) -> TokenState:
        deadline = time.monotonic() + device.expires_in
        interval = device.interval
        while time.monotonic() < deadline:
            payload = {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self.config.client_id,
                "device_code": device.device_code,
            }
            if self.config.client_secret:
                payload["client_secret"] = self.config.client_secret
            try:
                response = requests.post(
                    self.config.token_url,
                    data=payload,
                    timeout=self.config.timeout_s,
                )
            except requests.RequestException as exc:
                raise AuthError(f"Device token polling failed: {exc}") from exc

            if response.status_code < 400:
                return self._token_state_from_body(response.json())

            try:
                body = response.json()
            except ValueError:
                body = {}
            error_code = str(body.get("error", "")).strip()
            if response.status_code == 400 and error_code == "authorization_pending":
                time.sleep(interval)
                continue
            if response.status_code == 400 and error_code == "slow_down":
                interval += 5
                time.sleep(interval)
                continue
            if response.status_code == 400 and error_code == "access_denied":
                raise AuthError("Login denied.")
            if response.status_code == 400 and error_code == "expired_token":
                raise AuthError("Device login code expired. Run: learngraph auth login")
            detail = response.text.strip()
            raise AuthError(f"Device login failed ({response.status_code}): {detail}")

        raise AuthError("Device login timed out. Run: learngraph auth login")

    def _refresh(
        self,
        refresh_token: str,
        *,
        previous_refresh_expires_at: datetime | None = None,
    ) -> TokenState:
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.config.client_id,
            "refresh_token": refresh_token,
        }
        if self.config.client_secret:
            payload["client_secret"] = self.config.client_secret
        return self._request_token(
            payload,
            previous_refresh_token=refresh_token,
            previous_refresh_expires_at=previous_refresh_expires_at,
        )

    def _request_token(
        self,
        payload: dict[str, str],
        *,
        previous_refresh_token: str | None = None,
        previous_refresh_expires_at: datetime | None = None,
    ) -> TokenState:
        try:
            response = requests.post(
                self.config.token_url,
                data=payload,
                timeout=self.config.timeout_s,
            )
        except requests.RequestException as exc:
            raise AuthError(f"Auth request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text.strip()
            raise AuthError(f"Auth failed ({response.status_code}): {detail}")

        body = response.json()
        return self._token_state_from_body(
            body,
            previous_refresh_token=previous_refresh_token,
            previous_refresh_expires_at=previous_refresh_expires_at,
        )

    def _token_state_from_body(
        self,
        body: dict[str, Any],
        *,
        previous_refresh_token: str | None = None,
        previous_refresh_expires_at: datetime | None = None,
    ) -> TokenState:
        access_token = body.get("access_token")
        if not access_token:
            raise AuthError("Auth response missing access_token.")

        refresh_token = body.get("refresh_token") or previous_refresh_token
        refresh_expires = body.get("refresh_expires_in")
        refresh_expires_at = previous_refresh_expires_at
        if refresh_expires is not None:
            # For some Keycloak flows (notably offline tokens), 0 means
            # "not bounded by refresh_expires_in" rather than "expires now".
            try:
                refresh_expires_seconds = int(refresh_expires)
            except (TypeError, ValueError):
                refresh_expires_seconds = None
            if refresh_expires_seconds and refresh_expires_seconds > 0:
                refresh_expires_at = _parse_expiry(refresh_expires_seconds)
            else:
                refresh_expires_at = None

        return TokenState(
            access_token=access_token,
            token_type=body.get("token_type", "Bearer"),
            access_expires_at=_parse_expiry(body.get("expires_in")),
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expires_at,
        )

