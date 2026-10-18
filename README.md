# learngraph

Public command-line client for [LearnGraph](https://learngraph.org).

It logs in with the Keycloak device flow and submits topic-graph and resource
ingestion jobs. Backup, restore, and direct database commands are not part of
this tool.

License: [CC BY-NC 4.0](LICENSE).

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configure

Precedence is the CLI flag, then the environment variable, then the selected
`--environment` profile.

```bash
learngraph --help
```

`--environment stg` talks to `https://stg.learngraph.org`.
`--environment prod` talks to `https://app.learngraph.org`.
Both use Keycloak at `https://auth.app.learngraph.org`.

| Variable | Purpose |
| --- | --- |
| `LEARNGRAPH_ENVIRONMENT` | `stg` or `prod` |
| `LEARNGRAPH_AUTH_BASE_URL` | Keycloak base URL |
| `LEARNGRAPH_AUTH_REALM` | Keycloak realm |
| `LEARNGRAPH_AUTH_CLIENT_ID` | Defaults to `learngraph-cli` |
| `LEARNGRAPH_AUTH_CLIENT_SECRET` | Only for confidential clients |
| `LEARNGRAPH_AUTH_SCOPE` | OAuth scope |
| `LEARNGRAPH_AUTH_TIMEOUT_S` | Auth HTTP timeout |
| `LEARNGRAPH_AUTH_TOKEN_PATH` | Token file. Default `~/.config/learngraph/auth.json` |
| `LEARNGRAPH_INGESTION_BASE_URL` | Ingestion API base URL |
| `LEARNGRAPH_RESOURCES_BASE_URL` | Resources API base URL |
| `LEARNGRAPH_INGESTION_TIMEOUT_S` | Ingestion HTTP timeout |

## Use

```bash
learngraph --environment prod auth login
learngraph --environment prod auth status
learngraph --environment prod generate-topic-graph "Machine Learning"
learngraph --environment prod ingest-resources "https://example.com/some-resource"
```

`auth status` refreshes the access token when it has expired and the refresh
token is still valid. Tokens stay in `~/.config/learngraph/auth.json`.

`generate-topic-graph` and `ingest-resources` create graph content and spend
AI quota. `auth login` prints a verification URL and code; approve it in the
browser.
