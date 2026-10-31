---
type: integration reference
title: Sandbox Providers and Configuration
description: LangSmith managed sandbox provisioning, resource configuration, proxy credentials, and desktop bridge client integration.
tags: [sandbox, providers, langsmith, configuration, lifecycle, bridge]
verified:
  - by: openwiki/0.4.2
    at: 2026-10-31T14:24:53.711Z
sources:
  - id: openwiki-source-3436762fd1bce7c774640399
    resource: repo://openswe/bridge/backend.py
  - id: openwiki-source-b3b6cc9ac2ecd95444dcdfbe
    resource: repo://openswe/sandboxes/managed.py
  - id: openwiki-source-e2d4ab22e08f00169bb3c374
    resource: repo://openswe/sandboxes/providers/langsmith_api.py
  - id: openwiki-source-d16a45e9fc6aa80a3708c88c
    resource: repo://openswe/sandboxes/providers/langsmith.py
  - id: openwiki-source-a4c632cb1c0a9a7a637ab9fe
    resource: repo://openswe/sandboxes/providers/registry.py
  - id: openwiki-source-b7352e4d3dbf0b763a297a54
    resource: repo://openswe/sandboxes/read_only_backend.py
  - id: openwiki-source-63c74145043dac21719006df
    resource: repo://openswe/sandboxes/retry.py
generated: { by: "openwiki/0.4.2", at: "2026-10-31T14:24:53.711Z" }
---

# Sandbox Providers and Configuration

Open SWE runs repository work through a `SandboxBackendProtocol`. The deployment uses LangSmith as the primary sandbox provider; desktop CLI and local development support alternative backends. The sandbox lifecycle owns thread binding, safe reconnection, failure classification, and replacement policy. See [sandbox lifecycle](../architecture/sandbox-lifecycle.md) for the broader thread lifecycle and [configuration](../operations/configuration.md) for environment variables.

## LangSmith sandbox provider

### Overview

LangSmith is the production sandbox backend. Provisioning, reconnection, execution, proxy credential configuration, and environment snapshot operations are all LangSmith-specific.

### Provisioning and resources

Sandbox operations use the shared `LANGSMITH_API_KEY` and `LANGSMITH_ENDPOINT` environment variables. The integration normalizes the SDK endpoint to `/v2/sandboxes`, allowing sandbox operations to point to a distinct LangSmith workspace without separate credential variables.

New boxes use `DEFAULT_SANDBOX_SNAPSHOT_ID` when set; when absent, the create request omits `snapshot_id` so the platform's root snapshot is used. Resource defaults are:

- 4 vCPUs
- 16 GiB memory
- 128 GiB filesystem capacity
- Two-hour idle TTL
- 30-day delete-after-stop TTL

Setting either CPU or memory per call leaves the other as `None`, rather than mixing a partial override with the deployment default. Zero disables either TTL.

### Create-body options and extras

`SANDBOX_CREATE_EXTRA_JSON` supplies deployment-level JSON object fields (e.g., `{"_internal_runtime": "v2"}`). Per-environment or per-call `create_params` override conflicting fields. The implementation sends recognized SDK fields normally and wraps the SDK HTTP `POST /boxes` call to inject unsupported fields into that create request only.

Normal LangSmith creation retries up to three times for retryable status codes (408, 409, 425, 429, 500, 502, 503, 504, 529) and transient creation error classes (`ResourceCreationError`, `SandboxAPIError`, `SandboxConnectionError`, `SandboxNotReadyError`).

### Execution and timeouts

`TimeoutLangSmithSandbox` adapts the synchronous LangSmith SDK sandbox object to async agent work. With an effective command timeout, it:

1. Starts a non-blocking command via WebSocket
2. Waits for the command timeout plus `SANDBOX_EXECUTE_CLIENT_GRACE_SECONDS` (30 seconds by default)
3. Converts the result to `ExecuteResponse`

A server `CommandTimeoutError` returns exit code 124 without a kill. Expiry of the client deadline triggers a best-effort kill and returns exit code 124. WebSocket setup or supported midstream failures fall back to the base HTTP-capable `aexecute()` path. With no effective timeout, it delegates directly to that base path.

### Command execution retries

Only `SandboxRetryableConnectionError` is retried for command execution: it denotes a rejected WebSocket upgrade before the execute frame was sent, making a retry safe from double execution. Retries are capped at four attempts with jittered exponential backoff.

### GitHub credentials and proxy configuration

For LangSmith thread creation and reuse, the lifecycle mints a GitHub App installation token at runtime and configures proxy rules. The proxy injects:

- Basic authentication for `github.com` and `*.github.com`
- Bearer authentication plus a placeholder `GH_TOKEN` for `api.github.com`

The real GitHub token is not written into the sandbox. A not-ready proxy update starts the box best-effort and retries. Proxy configuration also preserves caller-provided rules, can inject connected user LangSmith credentials for HTTPS endpoints, and can add a supported Stagehand model rule.

### Environment snapshot capture and reset

Environment snapshot capture and `reset_sandbox_for_thread()` require LangSmith. Reset creates from an unfiltered create-body object, accepts SDK-supported and injected fields, reconfigures credentials and Git identity, and atomically hands the thread to the new id only after metadata persists.

### Sandbox startup validation

The FastAPI lifespan hook calls `validate_sandbox_startup_config()` before serving. LangSmith validation checks that:

- Configured resource and TTL values parse as integers
- TTLs are non-negative
- `SANDBOX_CREATE_EXTRA_JSON` parses as a valid JSON object

## Thread binding and failure semantics

### Sandbox connection and lifecycle

The thread-sandbox binding is owned by the thread's metadata record. `connect_existing_sandbox(sandbox_id: str)` reconnects to an existing LangSmith sandbox by its id; creation starts a new one with the configured resources and snapshot.

### Distinct deletion vs. unreachability

A missing LangSmith box is deliberately distinct from an unreachable box:

- `ResourceNotFoundError` becomes `SandboxGoneError`, so the lifecycle recreates the deleted box
- Other reconnection failures become `SandboxUnreachableError` and normally stop the run rather than silently replacing the working tree with an empty sandbox
- `allow_replacement=True` permits replacement for reviewer threads because their checkout is regenerated on every review run

### Initialization ordering

The lifecycle updates thread metadata with `sandbox_id` only after creation, identity setup, and proxy work finish. It publishes the backend proxy last. Reset and recreate similarly require a distinct new id and retain the old binding until metadata persistence succeeds. This ordering prevents later work from adopting an incompletely initialized or unpersisted sandbox.

### No delete operation

The provider interface intentionally has no delete operation. A sandbox can contain the agent's only working tree, and failed metadata reads can look like no sandbox. Cleanup is instead a platform responsibility controlled by creation-time idle and delete-after-stop TTLs.

## Desktop bridge client

Desktop CLI synchronizes repository state with the backend via a bridge connection. `BridgeSandboxBackend` is async-only and:

- Queues requests to the desktop over a persistent WebSocket
- Waits for results on the CLI side with optional liveness ticks (every 15 seconds)
- Enforces file transfer timeouts (120 seconds) and worktree handoff timeout (360 seconds)
- Supports execute, upload, and download operations only; all other operations raise `NotImplementedError`

When a thread connects to a desktop machine, the backend proxy receives sandbox operations via the bridge connection instead of direct LangSmith calls. The bridge backend pair implements `SandboxBackendProtocol` symmetrically: the backend submits requests, the listener on the desktop answers them, and results flow back through the bridge store. A `BridgeUnavailableError` surfaces when the desktop closes its connection or stops responding.

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

Trusted skills are extracted from the PR's base SHA rather than the author-controlled PR head. `materialize_trusted_skills()`:

- Extracts skill directories from a trusted ref (base SHA)
- Saves them to a separate directory outside the main checkout
- Prevents PR authors from injecting instructions into the reviewer prompt
- Returns extracted source directories with trailing slash for SkillsMiddleware
