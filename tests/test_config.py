from click.testing import CliRunner

from learngraph.cli import main
from learngraph.config import resolve_config


def test_prod_profile_fills_public_urls():
    config = resolve_config(
        environment="prod",
        auth_base_url=None,
        realm=None,
        client_id=None,
        client_secret=None,
        scope=None,
        auth_timeout_s=None,
        token_path=None,
        ingestion_base_url=None,
        resources_base_url=None,
        ingestion_timeout_s=None,
    )

    assert config.auth_base_url == "https://auth.app.learngraph.org"
    assert config.realm == "learngraph-production"
    assert config.client_id == "learngraph-cli"
    assert config.ingestion_base_url == "https://app.learngraph.org/service-ingestion/v1"
    assert config.resources_base_url == "https://app.learngraph.org/service-resources/v1"


def test_explicit_value_wins_over_profile():
    config = resolve_config(
        environment="prod",
        auth_base_url=None,
        realm="custom-realm",
        client_id=None,
        client_secret=None,
        scope=None,
        auth_timeout_s=None,
        token_path=None,
        ingestion_base_url=None,
        resources_base_url=None,
        ingestion_timeout_s=None,
    )

    assert config.realm == "custom-realm"
    assert config.ingestion_base_url == "https://app.learngraph.org/service-ingestion/v1"


def test_help_lists_config_env_vars():
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    for name in (
        "LEARNGRAPH_ENVIRONMENT",
        "LEARNGRAPH_AUTH_BASE_URL",
        "LEARNGRAPH_AUTH_REALM",
        "LEARNGRAPH_AUTH_CLIENT_ID",
        "LEARNGRAPH_AUTH_TOKEN_PATH",
        "LEARNGRAPH_INGESTION_BASE_URL",
        "LEARNGRAPH_RESOURCES_BASE_URL",
    ):
        assert name in result.output
