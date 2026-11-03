---
type: integration reference
title: Sandbox Providers and Configuration
description: Sandbox backend selection, provisioning, and configuration. Covers LangSmith managed sandboxes, Managed Deep Agents lifecycle, bridge client for desktop, and sandbox reconnection patterns.
tags: [sandbox, providers, langsmith, configuration, lifecycle, mda]
verified:
  - by: openwiki/0.4.2
    at: 2026-11-02T18:01:41.066Z
sources:
  - id: openwiki-source-3436762fd1bce7c774640399
    resource: repo://openswe/bridge/backend.py
  - id: openwiki-source-1b32e9f41fa7e64702b380f6
    resource: repo://openswe/sandboxes/lifecycle.py
  - id: openwiki-source-e2d4ab22e08f00169bb3c374
    resource: repo://openswe/sandboxes/providers/langsmith_api.py
  - id: openwiki-source-d16a45e9fc6aa80a3708c88c
    resource: repo://openswe/sandboxes/providers/langsmith.py
  - id: openwiki-source-a4c632cb1c0a9a7a637ab9fe
    resource: repo://openswe/sandboxes/providers/registry.py
  - id: openwiki-source-b7352e4d3dbf0b763a297a54
    resource: repo://openswe/sandboxes/read_only_backend.py
  - id: openwiki-source-c5766699cee46f671b69bf81
    resource: repo://openswe/sandboxes/repo_prep.py
generated: { by: "openwiki/0.4.2", at: "2026-11-02T18:01:41.066Z" }
---

# Sandbox Providers and Configuration

Open SWE runs repository work through a `SandboxBackendProtocol`. Sandbox creation is managed by Managed Deep Agents (MDA), which owns the lifecycle of thread sandboxes. Reconnection and proxy configuration for existing sandboxes are handled by provider backends. See [sandbox lifecycle](../architecture/sandbox-lifecycle.md) for the broader thread lifecycle and [configuration](../operations/configuration.md) for environment variables.

## Sandbox creation and ownership

Managed Deep Agents (MDA) creates and replaces every thread's sandbox. The backend never creates one. When a thread needs a sandbox:

1. The thread's metadata is checked for an existing `sandbox_id` and `sandbox_owner` (typically `"mda"`)
2. If the thread is unbound, MDA is asked to create a sandbox; once created, the lifecycle binds the thread to it
3. The backend reconnects to an existing sandbox by id, refreshes its proxy credentials and Git identity, and configures access

A thread can be bound to:
- An MDA-created LangSmith sandbox
- A deleted or unreachable LangSmith sandbox (owned by MDA or the old provider system)
- A desktop/local machine via bridge connection

Reconnection is the only operation the backend performs on existing sandboxes; creation is MDA's responsibility.

## Reconnection and provider backends

### LangSmith reconnection

`connect_existing_sandbox(sandbox_id)` reconnects to a LangSmith sandbox created earlier. It calls `create_langsmith_sandbox(sandbox_id)` with only the id; resource options are not used on reconnection.

`LangSmithProvider.get_or_create()` handles both creation (via MDA) and reconnection:
- When creating, it accepts snapshot, CPU, memory, filesystem, TTL, and extra create fields
- When reconnecting (when `sandbox_id` is provided), it ignores creation-time parameters and simply connects to the existing box
- It enforces operation-specific timeouts and can retry transient failures

### Bridge reconnection for desktop

When a thread is bound to a desktop/local machine (identified by a bridge id embedded in the sandbox id), `BridgeSandboxBackend.connect()` binds to the live bridge connection. If the bridge is down or unavailable, it raises `SandboxUnreachableError` and the thread is handed to MDA.

## Thread binding and failure semantics

`ensure_sandbox_for_thread()` manages reconnection for an existing thread sandbox. It:

1. Checks if the thread is a task worker and attaches to its coordinator's sandbox
2. Verifies the thread has a bound `sandbox_id`; if not, raises `SandboxUnreachableError`
3. Detects a bridge id and connects via `BridgeSandboxBackend` if present
4. Calls `_connect_existing_sandbox()` to reconnect and refresh proxy/Git configuration
5. Hands an unreachable or deleted sandbox to MDA

### Distinct deletion vs. unreachability

Reconnection distinguishes between two failure modes:

- **`SandboxGoneError`** (from LangSmith `ResourceNotFoundError`): the sandbox was deleted, contains no working tree, and can be recreated by MDA
- **`SandboxUnreachableError`** (other reconnection failures): the sandbox exists but is unreachable; normally stops the run rather than replacing it with a fresh empty sandbox, as replacement loses uncommitted working-tree state
- **`allow_replacement=True`** permits replacement for reviewer and review-scout threads because their checkout is re-derived from the PR on every run

### Initialization and binding ordering

The lifecycle updates thread metadata with the `sandbox_id` only after creation, identity setup, and proxy work complete. It publishes the backend proxy last. This ordering prevents later work from adopting an incompletely initialized or unpersisted sandbox.

### No delete operation

The provider interface intentionally has no delete operation. A sandbox can contain the agent's only working tree, and failed metadata reads can look like no sandbox. Cleanup is instead a platform responsibility controlled by creation-time idle and delete-after-stop TTLs (for LangSmith).

## LangSmith provider capabilities

### Provisioning and resources

Sandbox operations use the shared `LANGSMITH_API_KEY` and `LANGSMITH_ENDPOINT` environment variables. The integration normalizes the SDK endpoint to `/v2/sandboxes`, allowing sandbox operations to point to a distinct LangSmith workspace without separate credential variables.

New boxes use a configured snapshot or the platform root snapshot when omitted. Resource defaults are:

- 4 vCPUs
- 16 GiB memory
- 128 GiB filesystem capacity
- Two-hour idle TTL
- 30-day delete-after-stop TTL

Setting either CPU or memory per call leaves the other as `None`, rather than mixing a partial override with the deployment default. Zero disables either TTL.

### Create-body options and extras

`SANDBOX_CREATE_EXTRA_JSON` supplies deployment-level JSON object fields (e.g., `{"_internal_runtime": "v2"}`). Per-workspace or per-call `create_params` override conflicting fields. The implementation sends recognized SDK fields normally and wraps the SDK HTTP `POST /boxes` call to inject unsupported fields into that create request only.

Normal LangSmith creation retries up to three times for retryable status codes (408, 409, 425, 429, 500, 502, 503, 504, 529) and transient creation error classes (`ResourceCreationError`, `SandboxAPIError`, `SandboxConnectionError`, `SandboxNotReadyError`).

### Execution and timeouts

`TimeoutLangSmithSandbox` adapts the synchronous LangSmith object to async agent work. With an effective command timeout, it:

1. Starts a non-blocking command via WebSocket
2. Waits for the command timeout plus `SANDBOX_EXECUTE_CLIENT_GRACE_SECONDS` (30 seconds by default)
3. Converts the result to `ExecuteResponse`

A server `CommandTimeoutError` returns exit code 124 without a kill. Expiry of the client deadline triggers a best-effort kill and returns exit code 124. WebSocket setup or supported midstream failures fall back to the base HTTP-capable `aexecute()` path. With no effective timeout, it delegates directly to that base path.

### Command execution retries

Only `SandboxRetryableConnectionError` is retried for command execution: it denotes a rejected WebSocket upgrade before the execute frame was sent, making a retry safe from double execution. Retries are capped at four attempts with jittered exponential backoff.

### GitHub credentials and proxy configuration

For all thread creation and reuse, the lifecycle mints a GitHub App installation token at runtime and configures proxy rules. The proxy injects:

- Basic authentication for `github.com` and `*.github.com`
- Bearer authentication plus a placeholder `GH_TOKEN` for `api.github.com`

The real GitHub token is not written into the sandbox. A not-ready proxy update starts the box best-effort and retries. Proxy configuration also preserves caller-provided rules, can inject connected user LangSmith credentials for HTTPS endpoints, and can add a supported Stagehand model rule.

### Startup validation

The FastAPI lifespan hook calls `validate_sandbox_startup_config()` before serving. For LangSmith: configured resource and TTL values must parse as integers, TTLs must be non-negative, and `SANDBOX_CREATE_EXTRA_JSON` must parse as a valid JSON object.

## Bridge backend for desktop and local machines

### Desktop and local machine integration

`BridgeSandboxBackend` is async-only and:

- Queues requests to the desktop over a persistent WebSocket
- Waits for results on the CLI side with optional liveness ticks (every 15 seconds)
- Enforces file transfer timeouts (120 seconds) and worktree handoff timeout (360 seconds)
- Supports execute, upload, download, and worktree handoff operations only; all other operations raise `NotImplementedError`

The bridge backend pair implements `SandboxBackendProtocol` symmetrically: the backend submits requests, the listener on the desktop answers them, and results flow back through the bridge store. A `BridgeUnavailableError` surfaces when the desktop closes its connection or stops responding.

When a thread connects to a desktop machine, the backend proxy receives sandbox operations via the bridge connection instead of direct LangSmith calls. Reconnection via bridge requires the desktop to be alive; an unavailable bridge causes the run to fail with `SandboxUnreachableError`.

### Read-only backend for virtual skill routes

`ReadOnlyBackend` wraps another backend and delegates only async read operations (`als`, `aread`, `agrep`, `aglob`, `adownload_files`), rejecting all synchronous calls and mutation operations. Used by the desktop to serve bundled and user skill routes read-only.

## Repository preparation and review

### Reviewer sandbox preparation

Reviewer preparation clone-or-fetches and verifies the PR head before agent work. `prepare_review_repo()`:

- Clone-or-fetches the repo using `gh repo clone` with blobless filtering
- Fetches target commit and PR head specifically to minimize download
- Checks out the PR head and verifies SHA matches
- Returns `False` if prep fails so review can continue from diff context

### Trusted skills extraction

Trusted skills are extracted from the PR's base SHA rather than the author-controlled PR head. Skills extracted from the base ensure reviewer callers never execute untrusted instructions.

## Historical provider system

Earlier versions of Open SWE supported a provider registry with six pluggable sandbox backends: `langsmith`, `daytona`, `modal`, `runloop`, `e2b`, and `local`. This system allowed selecting sandboxes via `SANDBOX_TYPE` and forwarding resource options to any provider.

The current architecture has migrated to Managed Deep Agents (MDA) for sandbox creation. MDA handles provisioning with consistent configuration, lifecycle management, and replacement policy. The only remaining provider-specific code is LangSmith's reconnection logic, which is now part of the core lifecycle rather than a pluggable factory.

The bridge backend enables desktop/local machine integration without requiring a separate provider; it is selected implicitly when a thread's sandbox id contains a bridge id.

## Extension: reconnecting to new provider backends

To add support for reconnection to a new provider backend:

1. Create a factory function in `openswe/sandboxes/providers/<name>.py`:
   ```python
   async def create_<name>_sandbox(sandbox_id: str | None = None) -> SandboxBackendProtocol:
       # If sandbox_id is provided, reconnect to it
       # If sandbox_id is None, this path is not used (MDA creates new sandboxes)
   ```

2. Update `openswe/sandboxes/providers/registry.py` to call the factory from `connect_existing_sandbox()` based on the sandbox id's prefix or metadata.

3. Add environment variable documentation to `openswe/config.py` for credentials and configuration.

The factory is responsible only for reconnection. Sandbox creation is always MDA's responsibility. The factory receives only the `sandbox_id` and returns a `SandboxBackendProtocol` instance.
