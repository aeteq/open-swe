---
type: architecture overview
title: Runtime and Product Architecture
description: LangGraph deployment, graph entrypoints, FastAPI ingress, durable dispatch, sandbox ownership, and product surfaces for browser and desktop invocation.
tags: [architecture, langgraph, fastapi, dashboard, runtime]
verified:
  - by: openwiki/0.4.2
    at: 2026-10-19T15:23:56.456Z
sources:
  - id: openwiki-source-5bbba7b2a8ea8360ff233d63
    resource: repo://langgraph.json
  - id: openwiki-source-4b1279a0a1e5ec2d55a4558a
    resource: repo://openswe/api/app.py
  - id: openwiki-source-987be1dce6e9ba720855c2ed
    resource: repo://openswe/baby_sit.py
  - id: openwiki-source-913527bc7b548b4bf81f6a35
    resource: repo://openswe/completion.py
  - id: openwiki-source-e4bce0ee35cec33ca72293f7
    resource: repo://openswe/dashboard/__init__.py
  - id: openwiki-source-7fc33e4789861923a6f12e78
    resource: repo://openswe/dashboard/routes.py
  - id: openwiki-source-1685d34aae8025be9332f45a
    resource: repo://openswe/dispatch.py
  - id: openwiki-source-d0edf7555209b3e6418b5c5f
    resource: repo://openswe/github/routes.py
  - id: openwiki-source-813c25f6bac2408de322a1f5
    resource: repo://openswe/graphs/agent.py
  - id: openwiki-source-a9562865a4bff791686b49dd
    resource: repo://openswe/graphs/review_scout.py
  - id: openwiki-source-90b15fd6117126ebfe5b6b22
    resource: repo://openswe/graphs/reviewer.py
  - id: openwiki-source-ff94e6d6f8e823f174c61b08
    resource: repo://openswe/linear/routes.py
  - id: openwiki-source-7a02c62499495310b04f21ef
    resource: repo://openswe/review/chat.py
  - id: openwiki-source-96bcad07b4fe7078402bc2b8
    resource: repo://openswe/reviewer.py
  - id: openwiki-source-e9b2ac0cf383e184a317d349
    resource: repo://openswe/run_config.py
  - id: openwiki-source-1b32e9f41fa7e64702b380f6
    resource: repo://openswe/sandboxes/lifecycle.py
  - id: openwiki-source-919e16feae379651f2cbc1c9
    resource: repo://openswe/server.py
  - id: openwiki-source-c1d629bf5196269b73880148
    resource: repo://openswe/slack/routes.py
  - id: openwiki-source-5fa7ed68fabfe3d76e320060
    resource: repo://openswe/tasks/store.py
  - id: openwiki-source-3bd49e1c2bb74350a7519268
    resource: repo://openswe/webapp.py
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-4eb06f8c7641cb7107e39ca8
    resource: repo://ui/src/router.tsx
  - id: openwiki-source-c7a3ad58e4b4017484c1e326
    resource: repo://ui/src/routes/agents.tsx
generated: { by: "openwiki/0.4.2", at: "2026-10-19T15:23:56.456Z" }
---

# Runtime and Product Architecture

Open SWE is a LangGraph deployment with a custom FastAPI application. The HTTP layer accepts browser and integration traffic, while durable LangGraph runs execute coding or review work against thread-scoped state and a persistent backend. Three registered graph entrypoints separate the primary agent, reviewer, and review-scout tool inspector; PR chat proxies requests to the main agent thread without its own graph; scheduled work (CI monitoring, cron tasks) uses the job queue and manual dispatch.

## Mission and workflow

Open SWE turns engineering work into a repeatable system:

1. **Investigate** — Understand the codebase and requirements
2. **Implement in a sandbox** — Make changes in an isolated, persistent backend
3. **Validate** — Run focused tests and checks
4. **Deliver a PR** — Open or update a pull request on GitHub
5. **Review and iterate** — Respond to CI feedback, code review comments, and repository-specific review preferences

It also operates as a reviewer (runs on-demand or automatic reviews, publishes findings, learns repo-specific review styles), as a PR chat agent (read-only discussion of changes via dashboard proxy), and through background tasks (recurring work, CI monitoring, deadline management via `/baby-sit` watches and job queue).

## Runtime map

`langgraph.json` is the cloud deployment manifest. It registers three LangGraph graphs via thin `openswe/graphs/` re-export modules as stable dotted entrypoints, mounts `openswe.webapp:app`, configures checkpointer retention, loads `.env`, and attempts to build the dashboard static assets into the deployment image.

| Graph | Registered entrypoint | Responsibility |
|---|---|---|
| `agent` | `openswe.graphs.agent:traced_agent` | Per-run coding-agent factory: backend, models, tools, skills, and middleware. |
| `reviewer` | `openswe.graphs.reviewer:traced_reviewer_agent` | PR review and findings publication workflow. |
| `review-scout` | `openswe.graphs.review_scout:traced_review_scout` | Review-tool inspection and capability discovery. |

PR chat is **not** a separate graph; it is a read-only discussion proxy that routes requests to the pull request's main agent thread (see [Proxy and chat](#proxy-and-chat)). Scheduled and background work (cron ticks, CI watches, deadline monitoring) use the LangGraph run API or job queue directly, not a separate scheduler graph.

```
flowchart TD
  Slack["Slack"] --> Webhooks["Webhook routers<br/>(GitHub, Linear, Slack)"]
  Linear["Linear"] --> Webhooks
  GitHub["GitHub"] --> Webhooks
  Browser["Web dashboard"] --> Dashboard["Dashboard router"]
  Cron["Cron tick<br/>or job"] --> Dispatch["dispatch_agent_run"]

  subgraph App["FastAPI app"]
    Webhooks
    Dashboard
  end

  Webhooks --> Dispatch
  Dashboard --> Dispatch
  
  Dispatch --> Agent["agent graph"]
  Dispatch --> Reviewer["reviewer graph"]
  
  Agent --> Backend["Thread sandbox"]
  Reviewer --> Backend
  Scout["review-scout graph"] --> Backend
  
  Browser --> ChatProxy["PR chat proxy<br/>(agent thread)"]
  ChatProxy --> Agent
```

This shows the principal paths. `dispatch_agent_run` is the shared creation boundary for `agent` and `reviewer` runs. Review-scout, chat, and background/cron work use additional dispatch patterns. All converge to persistent sandbox state and thread-scoped run configuration.

## Graph and execution boundaries

`openswe.server:build_agent` (wrapped as `_get_agent`) produces a fresh deep-agent graph for an executable thread. It uses the thread ID to acquire a cached or reconnected backend (or a desktop `LocalShellBackend`), starts it, resolves thread/team/profile model settings, persists normalized thread settings when needed, and assembles a composite backend, tools, skills, subagents, and middleware. If no thread ID is supplied or the graph is being loaded rather than executed (e.g., for introspection), it returns a deliberately empty deep agent without provisioning a backend. This is important for graph discovery and non-execution loads. See [Agent Graph & get_agent Factory](./agent-graph.md) and [Middleware Stack](./middleware-stack.md) for its detailed composition.

The **reviewer** follows the sandbox lifecycle but deliberately has a review-only toolset: `add_finding`, `update_finding`, `list_findings`, and `publish_review`; it does not receive commit, push, or PR-opening tools. Its preparation computes an in-diff line set so finding validation occurs when a finding is created, rather than failing only during GitHub publication. The **review-scout** graph uses the same sandbox and authenticated `gh` access but is designed for capability inspection and review-tool discovery. See [Reviewer Graph](./reviewer-and-analyzer.md).

### Proxy and chat

The PR chat is intentionally **sandbox-less and read-only**. The dashboard review-chat proxy:
- Derives or creates a read-only agent thread scoped to the pull request
- Seeds the PR diff, findings, and overview as virtual `/pr/` files in the graph's `files` state channel
- Proxies read commands and stream requests directly to that thread's agent run, without starting its own graph

Filesystem tools can read the PR context, while `execute`, writes, edits, and deletion are excluded. GitHub-backed tools use a repository-scoped GitHub App token rather than a user credential. The implementation lives in `openswe.review.chat`; it is a **proxy**, not a graph. Dashboard requests flow through `proxy_review_chat_commands`, `proxy_review_chat_stream_events`, and related functions, which forward them to the underlying agent thread APIs.

## HTTP composition and ingress

`openswe/webapp.py` is a compatibility re-export of the application assembled by `openswe/api/app.py:create_app`. At import time the API pins one event loop before queue workers are built, and repeated pinning in the lifespan hook ensures all workers share the same loop. The app factory:

- Configures credentialed CORS from `DASHBOARD_ALLOWED_ORIGINS` and rejects `*` when credentials are allowed
- Mounts dashboard, plan, workflow-approval, Linear, Notion, Slack, GitHub, health, sandbox-tool, and remote-runtime routers
- Bundles the dashboard static UI (best-effort; a build failure leaves the backend deployable)
- On lifespan startup:
  - Validates sandbox and local-development LLM configuration
  - Runs database migrations and user imports
  - Activates analytics and event reporting
  - Starts listeners for transcripts and sandbox bridges
  - Initializes the job queue and workers
  - Warms the agent build
  - Handles imports of legacy Store records (user mappings, concierge mode, automations)
- On shutdown: closes cached models and cleans up listeners

The **dashboard router** is rooted at `/dashboard/api` and applies a same-origin dependency to mutations. It is the browser-facing boundary for OAuth, profiles, team defaults, administration, repository and review-style configuration, and thread APIs. Importing `openswe.dashboard` does not eagerly load this large surface: a PEP 562 `__getattr__` imports and caches `routes.router` only when the web application mounts it. This prevents middleware and non-webapp modules from pulling in FastAPI and all downstream API/job dependencies.

**Webhook routers** for Slack, Linear, and GitHub validate and normalize external events before scheduling service work. They derive or resolve stable thread identities—for example, Linear uses the issue ID and reviewer runs use repository and PR coordinates—so later activity can recover the corresponding thread state rather than starting an unrelated session. GitHub rejects invalid webhook signatures; Slack rejects conflicting mapping rather than guessing an agent thread.

## Durable dispatch and state ownership

`openswe.dispatch:dispatch_agent_run` is the common run-creation contract used by Slack, Linear, GitHub, dashboard, and background-task triggers. `assistant_id` selects `agent` or `reviewer`; `source` determines input identity and is retained for metadata/logging, not graph selection. The dispatcher rejects ambiguous combinations of a prebuilt input with content or identity arguments, ensuring callers choose either a fully constructed `RunInput` or build one from content, context, and identities.

The durable defaults are intentional:

- **`multitask_strategy="interrupt"`** — a follow-up halts the active run (progress preserved by its checkpoints) and resumes the agent with full history plus the new message. On an idle thread it just starts. Background follow-ups such as `/baby-sit` can explicitly opt into another strategy like `enqueue` for background queuing instead.
- **`durability="async"`** — checkpoint every step, written while the next one runs, so a crash or worker recycle resumes from at most one step back. (`"sync"` made every step wait on its write, adding ~0.3s per model/tool step in production; dashboard-started runs already use the platform's async default.)
- **Stream resilience** — `stream_resumable=True` retains the run's event stream so a client that attaches later can replay it. Without this the dashboard cannot observe a run it did not start; the v3 protocol only synthesizes the `lifecycle: running` event that drives `stream.isLoading` when it can replay the run's events, so an externally-triggered run would appear idle in the web UI (no stop button) until it emitted its next event.
- **v3 streaming shape** — the same `stream_mode` set, `stream_subgraphs` flag, and compatibility marker (`__event_streaming_v2`) that `langgraph_api`'s `run.start` command applies when the dashboard submits a run. The server fixes a run's streaming protocol at creation: without the marker a run streams `values` only, so the dashboard sees no `tools` events or subagent namespaces for externally triggered runs.

**Completion notification** is best effort. The dispatcher attaches a webhook only when `RUN_COMPLETE_WEBHOOK_SECRET` is configured and `COMPLETION_WEBHOOK_URL` is absolute and non-loopback. Otherwise it logs the condition and creates the run without a webhook, avoiding a configuration error that would poison all run creation.

### Run completion

`openswe.completion:run_complete_webhook` is the endpoint that receives the LangGraph platform's run-completion webhook. It:

- Verifies the token came from dispatch using `RUN_COMPLETE_WEBHOOK_SECRET`
- Handles **failure replies**: For terminal-failure statuses (`error`, `timeout`), posts a short reply to the run's originating channel (Slack, Linear, GitHub, etc.) so a run that died never leaves the user silent
- Enriches **session costs**: Slack runs enqueue deferred session-cost refresh so the dashboard's usage page accounts for the work
- **Settles transcript turns**: Records the run's final outcome and completes its turn history for replay
- **Best-effort design**: The reply is idempotent per run; older or manual payloads without a run id fall back to legacy thread-level idempotence

### Thread-scoped state and sandbox ownership

Graph state is ephemeral, but thread execution context is durable:

- **LangGraph checkpointing** retains graph state and allows resuming from any previous step
- **LangGraph thread metadata** holds the sandbox ID and related thread settings (repo, PR number, review settings, etc.)
- **Per-thread sandbox lifecycle** (openswe.sandboxes.lifecycle):
  - The sandbox cache is in-process and keyed by thread ID
  - Another worker reconnects using the persisted ID from thread metadata
  - An existing unreachable sandbox raises rather than being automatically replaced, because silent replacement can discard uncommitted work
  - Reviewer callers can allow replacement because their checkout is re-derived
  - The sandbox is published to the cache only after initialization and metadata binding succeed
- **Persistent task coordination** (openswe.tasks.store):
  - TaskMembership and TaskDelegation rows persist thread→task relationships across process boundaries
  - Worker threads coordinate with a coordinator thread, and coordinator progress is durably stored

See [Sandbox Lifecycle](./sandbox-lifecycle.md) and [Invocation](../workflows/invocation.md) for detailed ownership and recovery semantics.

## Background work and CI watches

The `/baby-sit` skill (openswe.baby_sit.BabySitWatch) is an optional, opt-in durable CI watch that:

- Stores a watch state in a pull request's task metadata
- Gets re-triggered by a cron job (every 10 minutes by default) or by the job queue
- Monitors pull request CI status and decides whether to dispatch a recovery/follow-up run
- Can retry up to 3 times per commit before giving up
- Coordinates with the main agent and reviewer runs to avoid redundant work

The baby-sit watch is **not** a separate graph; it uses `dispatch_agent_run` directly with the `multitask_strategy="enqueue"` option to queue follow-up work instead of interrupting active runs. This allows CI monitoring to happen asynchronously without disrupting an agent that may already be working on the same PR.

## Cloud and desktop product surfaces

The cloud manifest currently pins Python 3.14 and LangGraph API version >~=0.15.0rc1. Its checkpointer TTL uses `delete` strategy, sweeps every 60 minutes, and defaults to 43,200 minutes (30 days).

The **`ui/` application** is a TanStack Router React client with routes for:
- Agent sessions (cloud and local threads)
- Plans and automations
- Skills and environment configuration
- Reviews, styles, and administration
- Integrations and usage tracking
- Sandbox and instruction views

The `/agents` layout requires a session except for enabled desktop-local routes and selects `cloud` or `local` streaming transport from the active route. Router `basepath` follows Vite's build base, allowing the bundle to run below a configured mount prefix.

## Operations and safe changes

- **Add a deployable graph** by exporting a stable factory through `openswe/graphs/` and registering it in the appropriate manifest. Do not assume it becomes eligible for `dispatch_agent_run`; that contract selects only `agent` and `reviewer`.
- **Add browser APIs** through `create_app`, preserving session and mutation-origin protections rather than bypassing the dashboard boundary.
- **Treat a coding sandbox that is unreachable** as a recovery decision, not a cache miss. Replacing it changes the thread working tree.
- **When changing dispatch defaults or stream fields**, test durable run creation and cross-surface event attachment: dashboard observability relies on replayable v3-compatible streams for runs created outside the browser.
- **When changing desktop path handling**, retain real-path validation, the allowlist/worktree boundary, and artifact routing; each prevents a distinct local safety or repository-hygiene failure.
- **When adding scheduled work**, prefer the job queue and manual dispatch over creating a new graph. Use `dispatch_agent_run` with appropriate `multitask_strategy` for queueing or interruption semantics.

Related pages: [Agent Graph & get_agent Factory](./agent-graph.md), [Reviewer Graph](./reviewer-and-analyzer.md), [Sandbox Lifecycle](./sandbox-lifecycle.md), [Dashboard UI](../integrations/dashboard-ui.md), and [Invocation](../workflows/invocation.md).
