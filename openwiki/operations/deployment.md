---
type: operations-guide
title: Deployment and Docker Build
description: Deploy Open SWE as a standalone container or on LangGraph Platform, including multi-stage dashboard builds, checkpointer configuration, mount-prefix coupling, and background job requirements.
tags: [deployment, docker, langgraph, dashboard, standalone, platform, build]
verified:
  - by: openwiki/0.4.2
    at: 2026-09-26T12:44:40.906Z
sources:
  - id: openwiki-source-328bde9e94017848bb09ba23
    resource: repo://agent/api/app.py
  - id: openwiki-source-6e64b1ccdb133daeb8f4d1d4
    resource: repo://agent/utils/dashboard_ui.py
  - id: openwiki-source-24f77a48f966a05631988d08
    resource: repo://desktop/package.json
  - id: openwiki-source-2f66613e587b7c57d9be522e
    resource: repo://desktop/README.md
  - id: openwiki-source-bb1ebe868e35e9e500714501
    resource: repo://Dockerfile
  - id: openwiki-source-19973c87ca458faa5d03fecc
    resource: repo://docs/DEVELOPMENT.md
  - id: openwiki-source-bb241754e70259fd67d23952
    resource: repo://docs/INSTALLATION.md
  - id: openwiki-source-2d11873424257deb506bd9cd
    resource: repo://examples/ngrok/webhooks-only.yml
  - id: openwiki-source-b76f79b6cfae139d1784a43a
    resource: repo://langgraph.desktop.json
  - id: openwiki-source-5bbba7b2a8ea8360ff233d63
    resource: repo://langgraph.json
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
  - id: openwiki-source-5b54a58d1b51cd490b0e7162
    resource: repo://package.json
  - id: openwiki-source-40275cb92c3610938f16ade3
    resource: repo://pnpm-workspace.yaml
  - id: openwiki-source-05ccef8d4cf1698187f20464
    resource: repo://pyproject.toml
  - id: openwiki-source-abd87505fae29e34eafc785d
    resource: repo://scripts/create_sandbox_snapshot.py
  - id: openwiki-source-f33397bb846fdff018dc1c94
    resource: repo://scripts/install_desktop.sh
  - id: openwiki-source-8328043d526fe7293c1c1950
    resource: repo://scripts/purge_wakeup_crons.py
  - id: openwiki-source-440ae1e215cb02721dda855c
    resource: repo://turbo.json
  - id: openwiki-source-8b88ebeda33de308d80fcab2
    resource: repo://ui/Dockerfile
  - id: openwiki-source-cee8c9d42a08db69733a075f
    resource: repo://ui/server/backend-proxy.ts
  - id: openwiki-source-a741d432f952c0dbfb4fb35d
    resource: repo://ui/vite.config.ts
generated: { by: "openwiki/0.4.2", at: "2026-09-26T12:44:40.906Z" }
---

# Deployment and Docker Build

Open SWE's standard deployment topology consists of a single LangGraph application serving five graphs (`agent`, `reviewer`, `analyzer`, `review-scout`, `chat`, and `scheduler`), a FastAPI HTTP application (`agent.webapp:app`), and—when built—the bundled dashboard UI. The manifest (`langgraph.json`) declares the Python version, LangGraph API version, graph registrations, checkpointer TTL policy, and environment file to load. The same origin serves browser API calls (relative `/dashboard/api/*`), webhook deliveries, and the UI shell, avoiding CORS and making the `osw_session` cookie straightforward.

## Production deployment options

### LangGraph Platform

Connect the repository in LangSmith → Deployments. The deployment reads `langgraph.json` and runs its specified `dockerfile_lines` to perform a best-effort dashboard build from Node 24, the frozen pnpm lockfile, and the `open-swe-dashboard` package. The build is skipped or continues on failure, allowing the backend to deploy even if the UI build fails.

The platform injects `LANGSMITH_API_KEY`, tracing, and project values. For the complete environment contract, see [Configuration](../operations/configuration.md). The deployment URL becomes the backend's `LANGGRAPH_URL` and the GitHub App callback origin.

### Standalone Docker

Build the root `Dockerfile` with `docker build -t open-swe .`. It is a LangGraph API server image, not a sandbox image.

```dockerfile
FROM langchain/langgraph-api:0.13.3-py3.14
```

The Dockerfile installs the repository with `uv`, bakes the five graph registrations, HTTP app, and checkpointer policy into environment variables, then exposes port 8000. The images differ: the local dev server (`make dev`) resolves a `langgraph-api` version from `pyproject.toml`'s constraint-dependencies (`>=0.15.0rc1,<0.16`); the standalone image pins Python 3.14 and LangGraph API `0.13.3` in the base layer.

Provide these environment variables and backing services:

- `DATABASE_URI` — PostgreSQL connection string. Required for analytics; migrations create the `open_swe_analytics` schema and the `repository`, `pull_request`, `pull_request_thread`, `pull_request_review`, `users`, `user_identity`, `workspace`, `workspace_repository`, and `workspace_slack_channel` tables.
- `REDIS_URI` — Redis connection string. Required for task workers.
- `LANGSMITH_API_KEY` — LangSmith API key for tracing and sandboxes.
- `LANGGRAPH_CLOUD_LICENSE_KEY` — LangGraph Platform license (required for production).
- `LANGGRAPH_URL` — Public backend URL. Used in webhook callbacks and Trace links.

Do not use scale-to-zero hosting: background runs rely on Redis and Postgres workers staying available. Expose port 8000 through ingress.

**Dashboard bundling:** The image serves a dashboard only if `ui/.output/public` was built before `docker build`, or if `DASHBOARD_STATIC_DIR` names a prebuilt directory at runtime. To build, run `make build-dashboard` before `docker build`.

### Authentication

The standalone image defaults to `LANGGRAPH_AUTH_TYPE=noop`, which exposes raw LangGraph routes (`/threads`, `/runs`, `/assistants`, `/store`) to any network client. Dashboard sessions and webhook signatures do not secure these endpoints. Choose one of:

- **LangSmith:** Set `LANGGRAPH_AUTH_TYPE=langsmith` with `LANGSMITH_AUTH_ENDPOINT` and `LANGSMITH_TENANT_ID` (your workspace id). This makes the LangGraph API require a LangSmith key on every call.
- **Private network:** Use `noop` behind a private gateway or authenticated proxy.

## Multi-stage dashboard build

The platform manifest and standalone `Dockerfile` both use a Node 24 multi-stage build to compile the dashboard:

1. **Install:** pnpm installs the workspace with the frozen lockfile, filtered to the `open-swe-dashboard` package and its dependencies.
2. **Build:** Vite builds the package into `ui/.output/public`, a static directory with:
   - `_shell.html` — revalidated entry point
   - `assets/` — hashed, immutable build artifacts
3. **Copy:** The build is mounted into the backend's static directory.

The build bakes `DASHBOARD_BASE_PATH` (matching the LangGraph `http.mount_prefix`) into the UI's router and asset URLs. The platform manifest extracts this value from `langgraph.json` and supplies it automatically; standalone builds require manual configuration.

### Build configuration

- **`DASHBOARD_BASE_PATH`:** The root path where the dashboard is mounted (e.g., `/` or `/dashboard/`). Must equal `http.mount_prefix` in `langgraph.json`. Build-time variable that affects client routes and asset URLs.
- **`SOURCE_COMMIT`:** Baked into the UI and backend sidecar metadata to link artifacts to the source version.

A build failure does not block backend deployment. If the dashboard is not available, the backend serves a `404` at the UI entrypoint and proceeds normally otherwise.

## Checkpointer TTL and cleanup

The manifest declares a checkpointer policy that automatically deletes old run data:

```json
"checkpointer": {
  "ttl": {
    "strategy": "delete",
    "sweep_interval_minutes": 60,
    "default_ttl": 43200
  }
}
```

Sweeps run every 60 minutes and delete runs older than 43,200 minutes (30 days). Runs with explicit TTLs are deleted at their configured expiration. Checkpoints are dropped alongside runs.

## Environment and version pinning

The local dev server's `langgraph-api` is constrained in `pyproject.toml` to `>=0.15.0rc1,<0.16` via constraint-dependencies. This ensures `uv` resolves a version compatible with `langgraph.json`'s `api_version: ">~=0.15.0rc1"` rather than older releases. The standalone Docker image pins `langchain/langgraph-api:0.13.3-py3.14` in its base layer, decoupling from these constraint-dependencies.

```toml
[tool.uv]
constraint-dependencies = [
  "langgraph-api>=0.15.0rc1,<0.16",
  "langgraph-runtime-inmem>=0.35.0rc1,<0.36",
]
```

The `.env` file is loaded by `langgraph.json` at both development and deployment time, so environment-specific variables like `LANGSMITH_API_KEY` and database URIs are available to both the backend application and graph code.

## Dashboard mount path and static serving

The backend's dashboard integration handles both bundled builds and separate deployments:

- **Bundled:** The backend discovers the dashboard build at `ui/.output/public` by default, or at a path set by `DASHBOARD_STATIC_DIR`. Non-HTML requests for missing files return 404; HTML requests (navigations and client routing) return the shell (`_shell.html`) so the client router can handle them. Asset files under `assets/` are cached immutably.
- **Separate Vite dev:** When `DASHBOARD_DEV_SERVER_URL` is set, the backend reverse-proxies non-reserved paths to the Vite dev server on that URL. HMR and module loading come directly from Vite's port, not through the FastAPI proxy.

Reserved paths that the backend or LangGraph server own are never served by the dashboard catch-all:

- `/dashboard/api` — dashboard API routes
- `/webhooks` — GitHub, Slack, Linear webhook handlers
- `/health` — health checks
- `/assistants`, `/threads`, `/runs`, `/store`, `/mcp`, `/a2a` — LangGraph runtime routes
- `/ui`, `/docs`, `/openapi.json`, `/info`, `/metrics`, `/ok` — LangGraph and FastAPI introspection

The mount-prefix invariant is critical: if the backend mounts the dashboard at `/dashboard/` (via `http.mount_prefix`), the build must be made with `DASHBOARD_BASE_PATH=/dashboard/` so client routes and asset URLs point to the correct location. A mismatch causes navigation and asset fetch failures.

## CORS and origins

The backend applies credentialed CORS with a configured origin list:

```python
allowed_origins = [
  origin.strip()
  for origin in ENV.DASHBOARD_ALLOWED_ORIGINS.get().split(",")
  if origin.strip()
]
if "*" in allowed_origins:
  raise RuntimeError(
    "DASHBOARD_ALLOWED_ORIGINS must not include '*' when allow_credentials=True"
  )
```

For same-origin deployments (bundled dashboard or Vite dev), set `DASHBOARD_ALLOWED_ORIGINS` to the backend origin. For separate dashboard deployments, set it to the dashboard origin and configure `DASHBOARD_BASE_URL` and `DASHBOARD_API_BASE_URL` on the backend to point back to the dashboard, so OAuth redirects and API calls flow through the dashboard's proxy.

## Separate dashboard deployment

The dashboard can be deployed independently of the backend using `ui/Dockerfile`, built from the repository root:

```bash
docker build -f ui/Dockerfile .
```

This is a Node 24 Alpine multi-stage build that installs the workspace with the frozen pnpm lockfile, builds `open-swe-dashboard`, and runs the Nitro `.output` server on port 8080 as user `node`. The image reads `DASHBOARD_API_URL` at request time (not at build time), so one image can front any backend.

The Nitro server forwards `/dashboard/api/**` and `/webhooks/**` requests to the backend:

- Preserves path, query, and method
- Streams non-GET request bodies
- Forwards separate `Set-Cookie` headers line-by-line
- Leaves OAuth redirects intact for the browser to follow
- Throws if `DASHBOARD_API_URL` is unset

```typescript
export function backendOrigin(): string {
  const configured = (process.env.DASHBOARD_API_URL ?? "").replace(/\/$/, "")
  if (!configured) {
    throw new Error(
      "DASHBOARD_API_URL is not set. It is the backend this dashboard fronts; " +
        "there is no default because a fallback would be production's backend."
    )
  }
  return configured
}
```

### Cross-origin configuration

For same-origin proxy, set the backend's `DASHBOARD_BASE_URL` and `DASHBOARD_API_BASE_URL` to the dashboard origin and register its callback with the GitHub App. The dashboard proxies everything, so the browser stays on the dashboard origin.

Alternatively, build the dashboard with `VITE_DASHBOARD_API_BASE_URL` set to the backend origin. Keep `DASHBOARD_API_BASE_URL` on the backend and add the dashboard origin to `DASHBOARD_ALLOWED_ORIGINS`. The client will discover the session after hydration and resolve requests cross-origin. Never include secrets in `VITE_*` values; they become browser build-time constants.

## Desktop application

The experimental Electron client bundles the compiled dashboard UI and a local LangGraph backend. Users configure only the backend URL on first launch; they do not select a maintainer-hosted default.

```json
{
  "graphs": {
    "agent": "agent.graphs.agent:traced_agent"
  },
  "auth": {
    "path": "agent.local_auth:auth",
    "disable_studio_auth": true
  },
  "http": {
    "disable_ui": true
  }
}
```

The desktop manifest (`langgraph.desktop.json`) exposes only the `agent` graph with a local auth handler and disables the built-in UI (the bundled Electron UI takes its place). Background workers and checkpoint storage use SQLite instead of Redis and Postgres.

The bundled UI proxies `/dashboard/api/*` calls to the selected backend. Cloud features (GitHub login, shared workspaces, threads) require the selected backend; local mode (This Mac) runs on a loopback server without cloud connectivity.

### Building and installing

For source development, run `make desktop` (requires `make dev` to be running on `http://localhost:2024`), or pass `--backend-url` / set `OPEN_SWE_BACKEND_URL`.

Package with `pnpm --dir desktop run pack` (unpacked) or `pnpm --dir desktop run dist` (installer). Packaging rebuilds the dashboard and local backend resources.

On macOS, `make install-desktop` refuses a dirty checkout, fast-forwards `main`, then runs `scripts/install_desktop.sh`. The script:

1. Checks that Node, `ditto`, `uv`, and a pnpm/corepack launcher are available
2. Installs workspace dependencies
3. Packages the app with `pnpm --dir desktop run pack`
4. Stages the packaged app atomically into `/Applications` (or `~/Applications` if `/Applications` is not writable)
5. Quits any running Open SWE process and swaps in the new version

`make install-checkout` uses the current checkout without changing Git state.

## Operational helpers

### Testing and linting

```bash
make install          # uv sync --extra dev
make test [TEST_FILE=...]    # pytest (skips missing paths)
make integration_tests        # pytest tests/integration_tests/
make lint             # ruff check
make format           # ruff format --fix
make format-check     # ruff format --check
make typecheck        # ty check agent tests
```

### Deployment automation

**`scripts/create_sandbox_snapshot.py`** — Creates a LangSmith sandbox snapshot from a Docker image for use as a workspace's base sandbox:

```bash
uv run python scripts/create_sandbox_snapshot.py \
  --image johanneslangchain/open-swe-sandbox:gh-cli-amd64 \
  --name open-swe-gh-amd64
```

Prints the UUID to set as `DEFAULT_SANDBOX_SNAPSHOT_ID` in the deployment.

**`scripts/purge_wakeup_crons.py`** — A one-time backfill that deletes expired `thread_wakeup` crons from a deployment. Start with `--dry-run`:

```bash
uv run python scripts/purge_wakeup_crons.py --dry-run
uv run python scripts/purge_wakeup_crons.py
```

Resolves the target deployment from `--url` or `LANGGRAPH_URL` and the API key from `LANGGRAPH_API_KEY` or `LANGSMITH_API_KEY`.

## Webhook exposure during development

`langgraph dev` does not authenticate raw LangGraph API routes. Never expose port 2024 to the public without a restrictive gateway.

For local development with public webhooks, use:

```bash
make tunnel NGROK_DOMAIN=<name>.ngrok-free.dev
```

This tunnels port 2024 through ngrok with a policy that returns 404 for every path except `/webhooks/*`. GitHub, Slack, and Linear can deliver webhooks while dashboard and LangGraph access stay local.

```yaml
# examples/ngrok/webhooks-only.yml
actions:
  - type: deny
    expression: "http.request.uri.path != '/webhooks/github' && http.request.uri.path != '/webhooks/slack' && http.request.uri.path != '/webhooks/linear'"
```

Point integrations at the public webhook paths and use the URL where the dashboard is actually opened for the GitHub OAuth callback.
