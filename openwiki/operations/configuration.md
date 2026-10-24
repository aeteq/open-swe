---
type: operations reference
title: Configuration and Startup Validation
description: Explains Open SWE's lazy environment registry, persisted team and workspace settings, model and sandbox selection, secrets, and the boot-time validation that determines whether a server starts.
tags: [configuration, operations, environment-variables, startup-validation, sandbox, models, security, workspace-settings]
sources:
  - id: openwiki-source-5bbba7b2a8ea8360ff233d63
    resource: repo://langgraph.json
  - id: openwiki-source-15d75fcce83b1cece4ea13b8
    resource: repo://openswe/agent_api/client.py
  - id: openwiki-source-4b1279a0a1e5ec2d55a4558a
    resource: repo://openswe/api/app.py
  - id: openwiki-source-913527bc7b548b4bf81f6a35
    resource: repo://openswe/completion.py
  - id: openwiki-source-b3a1e5fc7fe45f62e902bef9
    resource: repo://openswe/config.py
  - id: openwiki-source-50d64b46ab06b6436266b4d0
    resource: repo://openswe/dashboard/oauth.py
  - id: openwiki-source-775d5704fff1c9b4f3e91941
    resource: repo://openswe/dashboard/workspace_settings.py
  - id: openwiki-source-1685d34aae8025be9332f45a
    resource: repo://openswe/dispatch.py
  - id: openwiki-source-b11ec0af4e40439361058935
    resource: repo://openswe/encryption.py
  - id: openwiki-source-1b32e9f41fa7e64702b380f6
    resource: repo://openswe/sandboxes/lifecycle.py
  - id: openwiki-source-e2d4ab22e08f00169bb3c374
    resource: repo://openswe/sandboxes/providers/langsmith_api.py
  - id: openwiki-source-d16a45e9fc6aa80a3708c88c
    resource: repo://openswe/sandboxes/providers/langsmith.py
  - id: openwiki-source-a4c632cb1c0a9a7a637ab9fe
    resource: repo://openswe/sandboxes/providers/registry.py
  - id: openwiki-source-919e16feae379651f2cbc1c9
    resource: repo://openswe/server.py
  - id: openwiki-source-cbab46b11893a9efc599e687
    resource: repo://openswe/utils/gateway.py
  - id: openwiki-source-4cc74089c0207ec1e5a6ca3b
    resource: repo://openswe/utils/model.py
verified:
  - by: openwiki/0.4.2
    at: 2026-10-24T12:31:26.683Z
generated: { by: "openwiki/0.4.2", at: "2026-10-24T12:31:26.683Z" }
---

# Configuration and Startup Validation

Open SWE has two configuration planes:

- **Deployment configuration** is declared centrally in `openswe/config.py` and normally supplied through environment variables (including the `.env` file named by `langgraph.json`). It covers connectivity, credentials, provider selection, UI URLs, and deployment defaults.
- **Persisted settings** are instance-wide (team settings) or per-workspace records in LangGraph Store, and change selected behavior without a redeploy: team-wide review toggles and model defaults, workspace-level base snapshot and custom resource sizing. These are not substitutes for secrets or provider credentials, which remain deployment configuration.

This page describes configuration ownership, validation behavior, and important patterns rather than cataloging every variable. `openswe/config.py` is the complete registry; [deployment](deployment.md) covers installation. See [models, profiles, and instructions](../concepts/models-profiles-instructions.md) for model selection semantics.

## Environment variables and the ENV registry

The `ENV` registry centralizes environment variable declarations and reads. Code accesses variables through `ENV.<name>` or `ENV["name"]` rather than calling `os.environ` directly, so lazy reads capture late secret hydration, key rotation, and test mocking. Whitespace-only and empty values count as unset. The registry documents descriptions, defaults, secret status, aliases, and deprecated names; its accessors (`get`, `require`, `get_int`, `get_bool`, `get_list`) parse values typefully.

The canonical name wins over aliases. Deprecated names and aliases are registered once and centralized so `deprecated_in_use()` can report them, and suppresses warnings when both old and new names are set (e.g., LangGraph Platform injecting legacy `LANGCHAIN_*` alongside `LANGSMITH_*`). An undeclared variable name raises `AttributeError` or `KeyError`, making environment variables an explicit schema.

### Deployment topology

`langgraph.json` registers the agent, reviewer, review-scout, chat, and scheduler graphs and mounts `openswe.webapp:app` (FastAPI) as the HTTP application. The checkpointer uses a delete-based TTL strategy with a 60-minute sweep interval and 43200-minute default TTL (30 days). The file declares `.env` as the environment file.

## Startup lifecycle and validation

The FastAPI entrypoint is `openswe.api.app:create_app`. It pins the process to a single event loop before background workers are constructed, and pins again in the lifespan startup phase. The lifespan then runs mandatory validation checks in order, aborting startup if any fail. After validation, it initializes background workers and services before yielding to serve routes. On shutdown it closes the database and stops workers.

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: an unescaped angle bracket inside a label breaks rendering; rephrase the label. -->
```text
flowchart TD
    Init["Import application"] --> Pin["Pin one event loop"]
    Pin --> Build["Create FastAPI application"]
    Build --> ValidateOrigins{"DASHBOARD_ALLOWED_ORIGINS<br/>contains asterisk?"}
    ValidateOrigins -->|yes| Abort["Abort: credentialed CORS<br/>cannot use wildcard"]
    ValidateOrigins -->|no| Start["Lifespan startup"]
    Start --> CheckAuth["Validate GitHub login allowlist"]
    CheckAuth -->|fail| Stop["Raise and abort startup"]
    CheckAuth -->|pass| CheckSandbox["Validate sandbox configuration"]
    CheckSandbox -->|fail| Stop
    CheckSandbox -->|pass| CheckMDA["Validate MDA/remote runtime URL"]
    CheckMDA -->|fail| Stop
    CheckMDA -->|pass| CheckModel["Validate localhost model credentials"]
    CheckModel -->|fail| Stop
    CheckModel -->|pass| Workers["Initialize background workers"]
    Workers --> Serve["Serve routes and runs"]
    Serve --> Close["Close database and stop workers"]
```

### Validation details

**GitHub login gate**: Startup fails when neither `OPEN_SWE_LOCAL_AUTH_TOKEN` is set nor either `ALLOWED_GITHUB_ORGS` or `ALLOWED_GITHUB_USERS` is non-empty. The deployment must gate dashboard access.

**MDA/Remote runtime**: Startup fails when `MDA_RUNTIME_URL` is not configured, since the agent and reviewer graphs require it. The URL must be absolute and use HTTPS (HTTP allowed only for localhost). Additionally, `REMOTE_RUNTIME_TOKEN_SECRET` must be configured to sign the run tokens the backend presents to MDA.

**Sandbox configuration**: Validation is provider-specific. For `SANDBOX_TYPE=langsmith`, it checks numeric resource fields (`DEFAULT_SANDBOX_*_BYTES`, `DEFAULT_SANDBOX_*_SECONDS`), numeric TTL fields (rejecting negative values for idle or delete-after-stop), and `SANDBOX_CREATE_EXTRA_JSON` (rejecting non-JSON or non-object). An unsupported provider name is rejected only when `create_sandbox` is called, not at startup.

**Model credentials** (localhost only): Validation runs only when `DASHBOARD_BASE_URL` is explicitly set to an `http://localhost` address. It checks the credential required by the deployment's `LLM_MODEL_ID` (or the fallback default): `OPENAI_API_KEY` for OpenAI, `ANTHROPIC_API_KEY` for Anthropic, and so on. Desktop OpenAI OAuth is accepted as a substitute for `OPENAI_API_KEY`. Runtime model choices (team settings, profile, thread) are not validated at boot.

**CORS wildcards**: If `DASHBOARD_ALLOWED_ORIGINS` contains `*`, the application raises during construction because credentialed CORS (required for dashboard API access) cannot safely use wildcards. Explicit origins enable credential sharing.

## Sandboxes: provider selection and configuration

`SANDBOX_TYPE` defaults to `langsmith` and selects the sandbox backend. The provider registry recognizes `langsmith`, `daytona`, `modal`, `runloop`, `e2b`, and `local`. Unsupported values raise `ValueError` with the supported list. The local provider executes commands on the host without isolation and is intended for local development only.

### LangSmith sandbox resources

For LangSmith, resource defaults are:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEFAULT_SANDBOX_SNAPSHOT_FS_CAPACITY_BYTES` | 128 GiB | Root filesystem size for new sandboxes |
| `DEFAULT_SANDBOX_VCPUS` | 4 | vCPUs allocated to a sandbox |
| `DEFAULT_SANDBOX_MEM_BYTES` | 16 GiB | Memory allocated to a sandbox |
| `DEFAULT_SANDBOX_IDLE_TTL_SECONDS` | 7200 (2 hours) | Idle seconds before a sandbox stops; 0 disables |
| `DEFAULT_SANDBOX_DELETE_AFTER_STOP_SECONDS` | 2592000 (30 days) | Seconds after stop before deletion; 0 disables |

Invalid or non-integer values raise `ValueError` at startup. Negative TTL values are also rejected.

`SANDBOX_CREATE_EXTRA_JSON` accepts a JSON object merged into the sandbox create body (e.g., `{"_internal_runtime": "v2"}` or nested `proxy_config`). Non-JSON or non-object values raise `ValueError` at startup.

### Workspace-level sandbox configuration

Each workspace can specify a `base_snapshot_id` (opaque provider-scoped identifier), custom resource overrides (mem_bytes, vcpus, fs_capacity_bytes), and arbitrary provider create-body parameters (create_params). When a workspace captures a snapshot, new sandboxes boot from it instead of a deployment default.

`WORKSPACE_SNAPSHOT_PREFIX` (default `openswe` via legacy alias `ENVIRONMENT_SNAPSHOT_PREFIX`) separates environment snapshot names when deployments share a LangSmith workspace. Sandbox operations use `LANGSMITH_API_KEY` and `LANGSMITH_ENDPOINT` unless workspace-specific alternatives are configured (currently through workspace records, not environment variables).

### Optional sandbox providers

Sandbox providers beyond `langsmith` and `local` are optional dependencies:

| Provider | SDK modules | Install extra |
|----------|-----------|---------------|
| daytona | `daytona`, `langchain_daytona` | `sandbox-daytona` or `sandbox-providers` |
| modal | `modal`, `langchain_modal` | `sandbox-modal` or `sandbox-providers` |
| runloop | `runloop_api_client`, `langchain_runloop` | `sandbox-runloop` or `sandbox-providers` |
| e2b | `e2b`, `langchain_e2b` | `sandbox-e2b` or `sandbox-providers` |

When `create_sandbox` is called with an unsupported provider or a missing optional extra, it raises `ValueError` with installation instructions.

### Local sandbox provider

The local provider for development sets:

| Variable | Purpose |
|----------|---------|
| `LOCAL_SANDBOX_ROOT_DIR` | Root directory for sandboxes on the host |
| `OPENSWE_SCRIPT_ROOT` | Where scripts and logs live (default `/open-swe/environment`, but local dev may override to a writable location) |
| `GIT_CONFIG_GLOBAL` | Git's global config path; kept out of `~/.gitconfig` |

## Models and reasoning profiles

The deployment specifies a default model in `LLM_MODEL_ID` (required format: `provider:model`, e.g., `openai:gpt-6.1-sol`). A fallback model is configured via `LLM_FALLBACK_MODEL_ID` or defaults to a provider-specific fallback when unset (Anthropic falls back to OpenAI and vice versa; other providers have no automatic fallback).

`LLM_REASONING_EFFORT` sets the default reasoning effort (low, medium, high, max) when no workspace or profile setting applies. Reasoning is currently supported on OpenAI, Anthropic, Google Gemini 3+, Fireworks reasoning models, and Baseten. Each provider maps effort to its own parameter names and formats.

Model calls carry a provider-level per-request timeout defaulting to 600 seconds with 6 retries, applied to the openai, anthropic, baseten, google_genai, and fireworks providers so a stalled connection retries instead of parking a run.

### Gateway routing

Gateway routing uses explicit `LANGSMITH_GATEWAY_ENABLED` when set and otherwise enables when `LANGSMITH_GATEWAY_API_KEY` is set; a true or false team value (in workspace settings) overrides this default, whereas an unset value inherits it. Unavailable routing logs and falls back to direct provider calls.

The gateway routes OpenAI, Anthropic, Baseten, Fireworks, and Google Gemini calls through LangSmith; other providers call directly. `LANGSMITH_GATEWAY_OPENAI_USE_RESPONSES=true` (default) keeps OpenAI's Responses API through the gateway for reasoning models.

## Team and workspace settings

Team settings are a single instance-wide Store record. Model-and-effort pairs are validated on input. When a Store read fails, application defaults hardcoded in `_default_settings()` are used instead. Chat inherits the agent model, and review grouping inherits the reviewer subagent model when unset or invalid.

## Security and secrets

### Token encryption

`TOKEN_ENCRYPTION_KEY` encrypts stored GitHub tokens and accepts an ordered, most-recent-first list of Fernet keys so writes use the first key while reads try each key in order, enabling rotation without invalidating already-stored tokens. The key(s) can be comma-separated or newline-separated.

### Webhook token verification

`RUN_COMPLETE_WEBHOOK_SECRET` is a shared bearer token proving a `/webhooks/run-complete` call came from Open SWE's own dispatch. The `verify_run_complete_token()` function fails closed by rejecting every call when the secret is unset, disabling completion and failure replies until it is configured.

`COMPLETION_WEBHOOK_URL` sets the absolute HTTPS URL where LangGraph posts run-completion webhooks. The platform rejects relative or loopback URLs (localhost, 127.0.0.1, ::1) even if a completion secret is set, so a platform-rejected callback cannot break run creation. When the secret is set and the URL is valid, it is appended with `?token=<secret>` so the route can verify the call came from dispatch.

## Observability and tracing

`LANGSMITH_API_KEY` is required for LangSmith trace links and feedback collection. The LangSmith SDK reads it directly, and LangGraph Platform injects it. `LANGSMITH_ENDPOINT` specifies a self-hosted or regional LangSmith API (defaults to https://api.smith.langchain.com).

`LANGSMITH_PROJECT` names the LangSmith project every run traces into and trace links point at (defaults to "default"). `LANGSMITH_TENANT_ID` supplies the LangSmith workspace id for trace links; when unset it is discovered from the workspace.

`POSTHOG_API_KEY` (optional) enables PostHog server-side usage capture. `DD_ENV` sets the shared Datadog and analytics environment (defaults to "production").

## Integrations

### GitHub

`GITHUB_APP_ID` is the numeric GitHub App id. `GITHUB_APP_CLIENT_ID` and `GITHUB_APP_CLIENT_SECRET` enable OAuth flow for the dashboard. `GITHUB_APP_PRIVATE_KEY` (PEM) signs app JWTs. `GITHUB_APP_INSTALLATION_ID` supplies a fallback GitHub App installation when a run names none.

`ALLOWED_GITHUB_ORGS` and `ALLOWED_GITHUB_USERS` gate webhook and dashboard access. At least one must be configured.

`GITHUB_WEBHOOK_SECRET` is the HMAC secret for webhook deliveries. `MERGE_QUEUE_DISPATCH_SECRET` is a backend-only signing secret for the queue dispatch gateway.

### Slack

`SLACK_BOT_TOKEN` (xoxb-...) is the Slack bot user OAuth token. `SLACK_SIGNING_SECRET` is the HMAC secret for webhook deliveries. `SLACK_BOT_USER_ID` and `SLACK_BOT_USERNAME` enable mention detection and readable context.

`SLACK_CLIENT_ID` and `SLACK_CLIENT_SECRET` enable "Sign in with Slack" on the dashboard. `SLACK_TEAM_ID` restricts it to one workspace.

`SLACK_PUBLIC_BASE_URL` sets the public URL for Slack webhooks and OAuth callbacks (defaults to `DASHBOARD_API_BASE_URL`; use ngrok URL when the dashboard runs on localhost).

### Linear

`LINEAR_WEBHOOK_SECRET` is the HMAC secret for Linear webhook deliveries. Linear uses MCP for bidirectional integration; see [Observability and MCP](../integrations/observability-and-mcp.md).

### Notion

`NOTION_API_KEY` is the Notion internal integration token. `NOTION_AGENT_API_KEY` is an optional personal access token of the agent's Notion member (defaults to `NOTION_API_KEY`). `NOTION_WEBHOOK_SECRET` verifies webhook deliveries.

Database properties and statuses are configurable; see `openswe/config.py` for the full list (assignee, repository, status, PR URL properties, status transitions, design document configuration, etc.).

## Database and persistence

`POSTGRES_URI` is the PostgreSQL URI available to custom code. `ANALYTICS_POOL_SIZE` (default 20) and `ANALYTICS_POOL_OVERFLOW` (default 20) configure the connection pool per process. `ANALYTICS_POOL_TIMEOUT_SECONDS` (default 5) sets the checkout timeout.

`POSTGRES_SLOW_QUERY_MS` (default 1000) logs queries at or above this duration; 0 disables. `ANALYTICS_HEALTH_TIMEOUT_SECONDS` (default 3) sets the analytics readiness timeout.

Data retention windows are configurable: raw events (25 months), aggregates (7 years), person records (13 months), acknowledged outbox (30 days), ingestion receipts (90 days).

## Optional features and flags

`OPEN_SWE_LOCAL_AUTH_TOKEN` enables local authentication for development without GitHub OAuth. When set, either this token or GitHub authorization permits dashboard access.

`OPENSWE_ENV` names the agent prompt deployment environment (`production`, `staging`, `preview`, or `local`). `preview` also lets startup drop superseded migration revisions and turns off reviewer auto-assignment.

`DEBUG_TRACEMALLOC` enables tracemalloc to attribute unclosed-session warnings (frames configurable via `DEBUG_TRACEMALLOC_FRAMES`, default 25).

`BG_JOB_ISOLATED_LOOPS` is a LangGraph background-job event-loop isolation flag.

## Integration examples and reference

### LangSmith and tracing

```
LANGSMITH_API_KEY=<key>
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=my-project
```

### MDA deployment

```
MDA_RUNTIME_URL=https://mda.example.com
REMOTE_RUNTIME_TOKEN_SECRET=<hmac-key>
MDA_RUNTIME_API_KEY=<optional-key-defaults-to-LANGSMITH_API_KEY>
```

### Gateway routing

```
LANGSMITH_GATEWAY_ENABLED=true
LANGSMITH_GATEWAY_API_KEY=<key-with-gateway:invoke>
LANGSMITH_GATEWAY_BASE_URL=https://gateway.smith.langchain.com
```

### Sandbox with custom resources

```
SANDBOX_TYPE=langsmith
DEFAULT_SANDBOX_VCPUS=8
DEFAULT_SANDBOX_MEM_BYTES=33285996544  # 31 GiB
DEFAULT_SANDBOX_SNAPSHOT_FS_CAPACITY_BYTES=274877906944  # 256 GiB
DEFAULT_SANDBOX_IDLE_TTL_SECONDS=3600  # 1 hour
DEFAULT_SANDBOX_DELETE_AFTER_STOP_SECONDS=604800  # 7 days
SANDBOX_CREATE_EXTRA_JSON='{"_internal_runtime": "v2"}'
WORKSPACE_SNAPSHOT_PREFIX=my-deployment
```

### Webhook setup

```
RUN_COMPLETE_WEBHOOK_SECRET=<bearer-token>
COMPLETION_WEBHOOK_URL=https://myapp.example.com/webhooks/run-complete
```

### Token encryption key rotation

```
TOKEN_ENCRYPTION_KEY=<new-key>,<old-key>,<older-key>
```

The first key encrypts all new tokens; all three can decrypt existing tokens.
