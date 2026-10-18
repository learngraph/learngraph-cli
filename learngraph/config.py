"""Resolve CLI flags, environment variables, and stg/prod profiles."""

from __future__ import annotations

import os
from dataclasses import dataclass

import click


class ShowEnvOption(click.Option):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("show_envvar", True)
        super().__init__(*args, **kwargs)


PROFILES: dict[str, dict[str, str]] = {
    "stg": {
        "LEARNGRAPH_AUTH_BASE_URL": "https://auth.app.learngraph.org",
        "LEARNGRAPH_AUTH_REALM": "learngraph-staging",
        "LEARNGRAPH_AUTH_CLIENT_ID": "learngraph-cli",
        "LEARNGRAPH_INGESTION_BASE_URL": "https://stg.learngraph.org/service-ingestion/v1",
        "LEARNGRAPH_RESOURCES_BASE_URL": "https://stg.learngraph.org/service-resources/v1",
    },
    "prod": {
        "LEARNGRAPH_AUTH_BASE_URL": "https://auth.app.learngraph.org",
        "LEARNGRAPH_AUTH_REALM": "learngraph-production",
        "LEARNGRAPH_AUTH_CLIENT_ID": "learngraph-cli",
        "LEARNGRAPH_INGESTION_BASE_URL": "https://app.learngraph.org/service-ingestion/v1",
        "LEARNGRAPH_RESOURCES_BASE_URL": "https://app.learngraph.org/service-resources/v1",
    },
}

DEFAULT_SCOPE = "openid profile email organization offline_access"
DEFAULT_CLIENT_ID = "learngraph-cli"
DEFAULT_AUTH_TIMEOUT = "20"
DEFAULT_INGESTION_TIMEOUT = "30"
DEFAULT_TOKEN_PATH = "~/.config/learngraph/auth.json"


@dataclass(frozen=True)
class PublicConfig:
    environment: str | None
    auth_base_url: str
    realm: str
    client_id: str
    client_secret: str | None
    scope: str
    auth_timeout_s: str
    token_path: str
    ingestion_base_url: str
    resources_base_url: str
    ingestion_timeout_s: str

    def export(self) -> None:
        """Publish resolved values so existing env readers see flag and profile values."""
        mapping = {
            "LEARNGRAPH_AUTH_BASE_URL": self.auth_base_url,
            "LEARNGRAPH_AUTH_REALM": self.realm,
            "LEARNGRAPH_AUTH_CLIENT_ID": self.client_id,
            "LEARNGRAPH_AUTH_SCOPE": self.scope,
            "LEARNGRAPH_AUTH_TIMEOUT_S": self.auth_timeout_s,
            "LEARNGRAPH_AUTH_TOKEN_PATH": self.token_path,
            "LEARNGRAPH_INGESTION_BASE_URL": self.ingestion_base_url,
            "LEARNGRAPH_RESOURCES_BASE_URL": self.resources_base_url,
            "LEARNGRAPH_INGESTION_TIMEOUT_S": self.ingestion_timeout_s,
        }
        if self.environment:
            mapping["LEARNGRAPH_ENVIRONMENT"] = self.environment
        if self.client_secret:
            mapping["LEARNGRAPH_AUTH_CLIENT_SECRET"] = self.client_secret
        for name, value in mapping.items():
            if value:
                os.environ[name] = value


def _chosen(explicit: str | None, profile: dict[str, str], env_name: str, fallback: str = "") -> str:
    if explicit is not None and str(explicit).strip() != "":
        return str(explicit).strip()
    profile_value = profile.get(env_name, "")
    if profile_value:
        return profile_value
    return fallback


def resolve_config(
    *,
    environment: str | None,
    auth_base_url: str | None,
    realm: str | None,
    client_id: str | None,
    client_secret: str | None,
    scope: str | None,
    auth_timeout_s: str | None,
    token_path: str | None,
    ingestion_base_url: str | None,
    resources_base_url: str | None,
    ingestion_timeout_s: str | None,
) -> PublicConfig:
    """Precedence is CLI flag, then environment variable, then the selected profile.

    Click already folds flags over env vars into the explicit arguments. This
    function only fills what is still empty from the profile and fixed defaults.
    """
    normalized = environment.strip().lower() if environment else None
    if normalized == "":
        normalized = None
    profile = PROFILES.get(normalized or "", {})
    secret = client_secret.strip() if client_secret and client_secret.strip() else None
    return PublicConfig(
        environment=normalized,
        auth_base_url=_chosen(auth_base_url, profile, "LEARNGRAPH_AUTH_BASE_URL"),
        realm=_chosen(realm, profile, "LEARNGRAPH_AUTH_REALM", "learngraph-staging"),
        client_id=_chosen(client_id, profile, "LEARNGRAPH_AUTH_CLIENT_ID", DEFAULT_CLIENT_ID),
        client_secret=secret,
        scope=_chosen(scope, profile, "LEARNGRAPH_AUTH_SCOPE", DEFAULT_SCOPE),
        auth_timeout_s=_chosen(auth_timeout_s, profile, "LEARNGRAPH_AUTH_TIMEOUT_S", DEFAULT_AUTH_TIMEOUT),
        token_path=_chosen(token_path, profile, "LEARNGRAPH_AUTH_TOKEN_PATH", DEFAULT_TOKEN_PATH),
        ingestion_base_url=_chosen(ingestion_base_url, profile, "LEARNGRAPH_INGESTION_BASE_URL"),
        resources_base_url=_chosen(resources_base_url, profile, "LEARNGRAPH_RESOURCES_BASE_URL"),
        ingestion_timeout_s=_chosen(
            ingestion_timeout_s,
            profile,
            "LEARNGRAPH_INGESTION_TIMEOUT_S",
            DEFAULT_INGESTION_TIMEOUT,
        ),
    )
