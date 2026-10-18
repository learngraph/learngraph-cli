"""Public LearnGraph CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import click

from learngraph.config import ShowEnvOption, resolve_config


@click.group()
@click.option(
    "--environment",
    type=click.Choice(["stg", "prod"], case_sensitive=False),
    default=None,
    envvar="LEARNGRAPH_ENVIRONMENT",
    cls=ShowEnvOption,
    help="Fill non-secret API and Keycloak defaults for staging or production.",
)
@click.option(
    "--auth-base-url",
    default=None,
    envvar="LEARNGRAPH_AUTH_BASE_URL",
    cls=ShowEnvOption,
    help="Keycloak base URL.",
)
@click.option(
    "--realm",
    default=None,
    envvar="LEARNGRAPH_AUTH_REALM",
    cls=ShowEnvOption,
    help="Keycloak realm.",
)
@click.option(
    "--client-id",
    default=None,
    envvar="LEARNGRAPH_AUTH_CLIENT_ID",
    cls=ShowEnvOption,
    help="Keycloak client id.",
)
@click.option(
    "--client-secret",
    default=None,
    envvar="LEARNGRAPH_AUTH_CLIENT_SECRET",
    cls=ShowEnvOption,
    help="Keycloak client secret. Only for confidential clients.",
)
@click.option(
    "--scope",
    default=None,
    envvar="LEARNGRAPH_AUTH_SCOPE",
    cls=ShowEnvOption,
    help="OAuth scope requested by device login.",
)
@click.option(
    "--auth-timeout",
    default=None,
    envvar="LEARNGRAPH_AUTH_TIMEOUT_S",
    cls=ShowEnvOption,
    help="Auth HTTP timeout in seconds.",
)
@click.option(
    "--token-path",
    default=None,
    envvar="LEARNGRAPH_AUTH_TOKEN_PATH",
    cls=ShowEnvOption,
    help="Where the access and refresh tokens are stored.",
)
@click.option(
    "--ingestion-base-url",
    default=None,
    envvar="LEARNGRAPH_INGESTION_BASE_URL",
    cls=ShowEnvOption,
    help="Ingestion API base URL, including /service-ingestion/v1.",
)
@click.option(
    "--resources-base-url",
    default=None,
    envvar="LEARNGRAPH_RESOURCES_BASE_URL",
    cls=ShowEnvOption,
    help="Resources API base URL, including /service-resources/v1.",
)
@click.option(
    "--ingestion-timeout",
    default=None,
    envvar="LEARNGRAPH_INGESTION_TIMEOUT_S",
    cls=ShowEnvOption,
    help="Ingestion HTTP timeout in seconds.",
)
@click.pass_context
def main(
    ctx: click.Context,
    environment: str | None,
    auth_base_url: str | None,
    realm: str | None,
    client_id: str | None,
    client_secret: str | None,
    scope: str | None,
    auth_timeout: str | None,
    token_path: str | None,
    ingestion_base_url: str | None,
    resources_base_url: str | None,
    ingestion_timeout: str | None,
) -> None:
    """LearnGraph CLI.

    Configuration precedence is the CLI flag, then the environment variable,
    then the selected --environment profile (stg or prod).
    """
    config = resolve_config(
        environment=environment,
        auth_base_url=auth_base_url,
        realm=realm,
        client_id=client_id,
        client_secret=client_secret,
        scope=scope,
        auth_timeout_s=auth_timeout,
        token_path=token_path,
        ingestion_base_url=ingestion_base_url,
        resources_base_url=resources_base_url,
        ingestion_timeout_s=ingestion_timeout,
    )
    config.export()
    ctx.obj = config


def _auth_manager():
    from learngraph.ingestion_api.auth import AuthConfig, AuthManager

    return AuthManager(AuthConfig.from_env())


def _ingestion_client():
    from learngraph.ingestion_api.client import IngestionApiClient, IngestionApiConfig

    return IngestionApiClient(IngestionApiConfig.from_env(), _auth_manager())


def _print_usage_denied(resp: Any) -> None:
    click.echo(
        "Ingestion blocked by usage limit "
        f"(usage_percent={getattr(resp, 'usage_percent', None)}, "
        f"used_tokens={getattr(resp, 'used_tokens', None)}, "
        f"limit_tokens={getattr(resp, 'limit_tokens', None)})."
    )


def _print_job_result(job: Any, *, json_output: bool) -> None:
    if json_output:
        click.echo(
            json.dumps(
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "type": job.type,
                    "stage": job.stage,
                    "error": job.error,
                    "warnings": job.warnings,
                    "result": None
                    if job.result is None
                    else {
                        "central_topic_id": job.result.central_topic_id,
                        "created_topic_ids": job.result.created_topic_ids,
                        "reused_topic_ids": job.result.reused_topic_ids,
                        "tokens_in": job.result.tokens_in,
                        "tokens_out": job.result.tokens_out,
                    },
                },
                indent=2,
            )
        )
        return

    click.echo(f"Job {job.job_id}: status={job.status}, stage={job.stage or '-'}")
    if job.error:
        click.echo(f"Error: {job.error}")
    if job.warnings:
        click.echo(f"Warnings ({len(job.warnings)}):")
        for warning in job.warnings:
            click.echo(f"  - {warning}")
    if job.result:
        click.echo("Result:")
        click.echo(f"  central_topic_id: {job.result.central_topic_id}")
        click.echo(f"  created_topic_ids: {job.result.created_topic_ids or []}")
        click.echo(f"  reused_topic_ids: {job.result.reused_topic_ids or []}")
        click.echo(f"  tokens_in: {job.result.tokens_in}")
        click.echo(f"  tokens_out: {job.result.tokens_out}")


def _submit_and_optionally_wait(
    accepted: Any,
    *,
    wait: bool,
    poll_interval: float,
    poll_timeout: float | None,
    json_output: bool,
) -> None:
    if getattr(accepted, "allowed", None) is False:
        _print_usage_denied(accepted)
        raise click.exceptions.Exit(2)

    click.echo(f"Accepted job: {accepted.job_id} (status={accepted.status})")
    if not wait:
        return

    client = _ingestion_client()
    click.echo("Polling ingestion job...")
    from learngraph.ingestion_api.polling import PollTimeoutError, PollingConfig, wait_for_job

    try:
        job = wait_for_job(
            client,
            accepted.job_id,
            PollingConfig(interval_seconds=poll_interval, timeout_seconds=poll_timeout),
        )
    except PollTimeoutError as exc:
        raise click.ClickException(str(exc)) from exc

    _print_job_result(job, json_output=json_output)
    if job.status == "failed":
        raise click.exceptions.Exit(1)


@main.group(name="auth")
def auth_group() -> None:
    """Authentication helpers for ingestion endpoints."""


@main.command(name="completion")
@click.argument("shell", type=click.Choice(["zsh", "bash", "fish"], case_sensitive=False))
def completion_cmd(shell: str) -> None:
    """Print shell completion script for this CLI."""
    prog = Path(sys.argv[0]).name
    complete_var = f"_{prog.replace('-', '_').upper()}_COMPLETE"
    env = os.environ.copy()
    env[complete_var] = f"{shell.lower()}_source"
    try:
        output = subprocess.check_output([sys.argv[0]], env=env, text=True)
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(f"Failed to generate completion script: {exc}") from exc
    click.echo(output, nl=False)


@auth_group.command(name="login")
def auth_login_cmd() -> None:
    """Login and store token locally."""
    try:
        token = _auth_manager().login_interactive()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Login successful. Token stored at {_auth_manager().config.token_path}. "
        f"Expires at {token.access_expires_at.isoformat()}."
    )


@auth_group.command(name="status")
def auth_status_cmd() -> None:
    """Show local auth token status, refreshing it when the refresh token is still valid."""
    try:
        is_valid, token = _auth_manager().status()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if token is None:
        click.echo("Not logged in.")
        return
    click.echo(f"Logged in: {is_valid}")
    click.echo(f"Access token expires at: {token.access_expires_at.isoformat()}")
    if token.refresh_expires_at:
        click.echo(f"Refresh token expires at: {token.refresh_expires_at.isoformat()}")


@auth_group.command(name="logout")
def auth_logout_cmd() -> None:
    """Delete local auth token."""
    try:
        _auth_manager().logout()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Logged out. Local token removed.")


@main.command(name="generate-topic-graph")
@click.argument("topic", type=str)
@click.option("--coalesce-threshold", type=float, default=None)
@click.option("--max-resources-per-topic", type=int, default=None)
@click.option("--wait/--no-wait", default=True, show_default=True)
@click.option("--poll-interval", type=float, default=5.0, show_default=True)
@click.option("--poll-timeout", type=float, default=None, help="Polling timeout in seconds.")
@click.option("--json-output", is_flag=True, default=False, help="Print final job result as JSON.")
def generate_topic_graph_cmd(
    topic: str,
    coalesce_threshold: float | None,
    max_resources_per_topic: int | None,
    wait: bool,
    poll_interval: float,
    poll_timeout: float | None,
    json_output: bool,
) -> None:
    """Submit topic ingestion to the ingestion service and optionally wait for completion."""
    click.echo(f"Submitting topic ingestion for: {topic}")
    try:
        response = _ingestion_client().submit_topic_ingestion(
            topic,
            coalesce_threshold=coalesce_threshold,
            max_resources_per_topic=max_resources_per_topic,
        )
        _submit_and_optionally_wait(
            response,
            wait=wait,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            json_output=json_output,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@main.command(name="ingest-resources")
@click.argument("resource_url")
@click.option("--reference", default=None, help="Canonical reference for the resource.")
@click.option("--resource-uuid", default=None, help="Existing resource UUID for uploaded file resources.")
@click.option("--publish/--no-publish", default=None, help="Visibility hint for ingestion service.")
@click.option("--seed-topic-title", default=None, help="Preferred central topic title.")
@click.option("--wait/--no-wait", default=True, show_default=True)
@click.option("--poll-interval", type=float, default=5.0, show_default=True)
@click.option("--poll-timeout", type=float, default=None, help="Polling timeout in seconds.")
@click.option("--json-output", is_flag=True, default=False, help="Print final job result as JSON.")
def ingest(
    resource_url: str,
    reference: str | None,
    resource_uuid: str | None,
    publish: bool | None,
    seed_topic_title: str | None,
    wait: bool,
    poll_interval: float,
    poll_timeout: float | None,
    json_output: bool,
) -> None:
    """Submit resource ingestion to the ingestion service and optionally wait for completion."""
    candidate_path = Path(resource_url).expanduser()
    is_http_url = resource_url.lower().startswith(("http://", "https://"))

    submit_url = resource_url
    submit_reference = reference
    submit_resource_uuid = resource_uuid
    effective_seed_topic = seed_topic_title

    client = _ingestion_client()
    if not is_http_url and candidate_path.exists() and candidate_path.is_file():
        click.echo(f"Uploading local file via resources service: {candidate_path}")
        try:
            uploaded_reference, uploaded_resource_uuid = client.upload_local_file(
                candidate_path,
                publish=publish,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

        submit_url = ""
        submit_reference = uploaded_reference
        submit_resource_uuid = uploaded_resource_uuid
        if effective_seed_topic is None:
            effective_seed_topic = candidate_path.name
    elif not is_http_url and (not candidate_path.exists() or not candidate_path.is_file()):
        raise click.ClickException(
            "Input is neither an http(s) URL nor an existing local file path."
        )

    click.echo(f"Submitting resource ingestion for: {resource_url}")
    try:
        response = client.submit_resource_ingestion(
            url=submit_url,
            reference=submit_reference,
            resource_uuid=submit_resource_uuid,
            publish=publish,
            seed_topic_title=effective_seed_topic,
        )
        _submit_and_optionally_wait(
            response,
            wait=wait,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            json_output=json_output,
        )
    except click.exceptions.Exit:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
