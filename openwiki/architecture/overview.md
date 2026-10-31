---
type: architecture overview
title: Runtime and Product Architecture
description: LangGraph deployment, graph entrypoints, FastAPI ingress, durable dispatch, sandbox ownership, and the dashboard and desktop product surfaces.
tags: [architecture, langgraph, fastapi, dashboard, runtime]
verified:
  - by: openwiki/0.4.2
    at: 2026-10-31T14:24:53.711Z
sources:
  - id: openwiki-source-5bbba7b2a8ea8360ff233d63
    resource: repo://langgraph.json
  - id: openwiki-source-4b1279a0a1e5ec2d55a4558a
    resource: repo://openswe/api/app.py
  - id: openwiki-source-e4bce0ee35cec33ca72293f7
    resource: repo://openswe/dashboard/__init__.py
  - id: openwiki-source-7fc33e4789861923a6f12e78
    resource: repo://openswe/dashboard/routes.py
  - id: openwiki-source-1685d34aae8025be9332f45a
    resource: repo://openswe/dispatch.py
  - id: openwiki-source-813c25f6bac2408de322a1f5
    resource: repo://openswe/graphs/agent.py
  - id: openwiki-source-2e8359c5702d5a31e2d5ea43
    resource: repo://openswe/graphs/read_only.py
  - id: openwiki-source-a9562865a4bff791686b49dd
    resource: repo://openswe/graphs/review_scout.py
  - id: openwiki-source-90b15fd6117126ebfe5b6b22
    resource: repo://openswe/graphs/reviewer.py
  - id: openwiki-source-7a02c62499495310b04f21ef
    resource: repo://openswe/review/chat.py
  - id: openwiki-source-96bcad07b4fe7078402bc2b8
    resource: repo://openswe/reviewer.py
  - id: openwiki-source-3bd49e1c2bb74350a7519268
    resource: repo://openswe/webapp.py
  - id: openwiki-source-4eb06f8c7641cb7107e39ca8
    resource: repo://ui/src/router.tsx
  - id: openwiki-source-c7a3ad58e4b4017484c1e326
    resource: repo://ui/src/routes/agents.tsx
generated: { by: "openwiki/0.4.2", at: "2026-10-31T14:24:53.711Z" }
---

# Runtime and Product Architecture

Open SWE is a LangGraph deployment with a custom FastAPI application. The HTTP layer accepts browser and integration traffic, while durable LangGraph runs execute coding or review work against thread-scoped state and—except for PR chat—a backend. Three registered graph entrypoints power read access to pre-Managed Deep Agents threads, while execution runs on Managed Deep Agents. PR chat flows through a FastAPI proxy to the main agent thread, and background work runs via the job queue, not as registered graphs.

## Mission and workflow

Open SWE turns engineering work into a repeatable system:

1. **Investigate** — Understand the codebase and requirements
2. **Implement in a sandbox** — Make changes in an isolated, persistent backend
3. **Validate** — Run focused tests and checks
4. **Deliver a PR** — Open or update a pull request on GitHub
5. **Review and iterate** — Respond to CI feedback, code review comments, and repository-specific review preferences

It also operates as a reviewer (runs on-demand or automatic reviews, publishes findings, learns repo-specific review styles), as a PR chat agent (read-only discussion of changes), and as a scheduler (recurring tasks, CI monitoring, deadline management).

## Runtime map

`langgraph.json` is the cloud deployment manifest. It registers three named graphs at stable dotted entrypoints, mounts `openswe.webapp:app`, configures checkpointer retention, loads `.env`, and builds the dashboard into the deployment image.

| Graph | Registered entrypoint | Responsibility |
|---|---|---|
| `agent` | `openswe.graphs.agent:traced_agent` | Read access to pre-MDA threads; execution runs on Managed Deep Agents. |
| `reviewer` | `openswe.graphs.reviewer:traced_reviewer_agent` | Read access to pre-MDA reviewer threads; execution runs on Managed Deep Agents. |
| `review-scout` | `openswe.graphs.review_scout:traced_review_scout` | Read access to pre-MDA review-scout threads; execution runs on Managed Deep Agents. |

All three graphs are re-exports of `openswe.graphs.read_only:read_only_graph`, which serves graph state reads for threads created before Managed Deep Agents migration. New runs execute on Managed Deep Agents and route through `openswe.threads.router:ThreadRouter` middleware. Attempting to execute a run on a pre-MDA thread raises `ReadOnlyThreadError`, directing users to start a new thread.

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: an unescaped angle bracket inside a label breaks rendering; rephrase the label. -->
```text
flowchart TD
  Slack["Slack"] --> Webhooks["Webhook routers<br/>GitHub, Linear, Slack"]
  Linear["Linear"] --> Webhooks
  GitHub["GitHub"] --> Webhooks
  Browser["Web dashboard"] --> Dashboard["Dashboard router"]
  JobQueue["Job queue"] --> BackgroundJobs["Background jobs<br/>reconcile, watch, costs"]
  Dashboard --> Chat["PR chat proxy"]

  subgraph App["FastAPI app"]
    Webhooks
    Dashboard
  end

  Webhooks --> Dispatch["dispatch_agent_run"]
  Dashboard --> Dispatch
  Dispatch --> ThreadRouter["ThreadRouter middleware"]
  ThreadRouter --> MDA["Managed Deep Agents<br/>execution"]
  MDA --> Agent["agent graph"]
  MDA --> Reviewer["reviewer graph"]
  Agent --> Backend["Thread sandbox<br/>or desktop backend"]
  Reviewer --> Backend
  Chat --> Agent
  BackgroundJobs --> Dispatch
```

The diagram shows the full dispatch cycle: `dispatch_agent_run` is the shared creation boundary for agent and reviewer runs. Chat and background work do not go through dispatch or registered graphs.

## Graph and execution boundaries

Execution now runs on Managed Deep Agents via the LangGraph platform's execution runtime. The registered graphs (`agent`, `reviewer`, `review-scout`) serve state reads only; they re-export `openswe.graphs.read_only:read_only_graph`, which raises `ReadOnlyThreadError` if a run attempts to execute on a pre-MDA thread and otherwise returns an empty deep agent with only the caching middleware.

New runs created via `dispatch_agent_run` route through `openswe.threads.router:ThreadRouter` middleware, which detects the thread's execution model and routes to Managed Deep Agents. The platform's execution runtime handles tool invocation, subagent dispatch, and model calls. Thread metadata persists sandbox ID and related settings across workers; the sandbox cache is in process and keyed by thread ID. An existing unreachable sandbox raises rather than being automatically replaced, because silent replacement can discard uncommitted work.

PR chat is intentionally sandbox-less and read-only. Rather than being a separate graph, it is a FastAPI proxy in `openswe/review/chat.py` that proxies requests through to the main agent thread. The dashboard review-chat handlers seed the PR diff, findings, and overview via the existing agent thread's state. Filesystem tools can read that context, while `execute`, writes, edits, and deletion are excluded; GitHub-backed tools use a repository-scoped GitHub App token rather than a user credential.

Background and scheduled work runs via the job queue (openswe/jobs), not as registered graphs. Job handlers dispatch to reconciliation (`reconcile_stale_runs`), watch evaluation (`evaluate_watch`), background-task monitoring, session-cost or agent-cost refresh, thread-feedback evaluation, human-review deadline management, or scheduled agent runs. Missing a watch key, thread ID, or schedule ID yields a structured status instead of launching ambiguous work.

## HTTP composition and ingress

`openswe/webapp.py` is a compatibility re-export of the application assembled by `openswe/api/app.py:create_app`. At import time the API pins one event loop before background workers are built, and repeated pinning in the lifespan hook ensures all workers share the same event loop. The app factory configures credentialed CORS from `DASHBOARD_ALLOWED_ORIGINS` and rejects `*`, then mounts dashboard, plan, workflow-approval, Linear, Notion, Slack, GitHub, health, and sandbox-tool routers plus the bundled dashboard UI. Its lifespan hook validates sandbox and local-development LLM configuration at startup, runs database migrations and user imports, activates analytics, starts listeners for transcripts and sandbox bridges, closes cached models on shutdown, and handles imports of legacy Store records (user mappings, concierge mode, automations).

The dashboard router is rooted at `/dashboard/api` and applies a same-origin dependency to mutations. It is the browser-facing boundary for OAuth, profiles, team defaults, administration, repository and review-style configuration, and thread APIs. Importing `openswe.dashboard` does not eagerly load this large surface: a PEP 562 `__getattr__` imports and caches `routes.router` only when the web application mounts it. This prevents middleware and non-webapp modules from pulling in FastAPI and all downstream API/job dependencies.

Slack, Linear, and GitHub webhook routes validate and normalize external events before scheduling their service work. They derive or resolve stable thread identities—for example, Linear uses the issue ID and reviewer runs use repository and PR coordinates—so later activity can recover the corresponding thread state rather than starting an unrelated session. GitHub rejects invalid webhook signatures; Slack rejects conflicting mapping rather than guessing an agent thread.

## Durable dispatch and state ownership

`dispatch_agent_run` is the common run-creation contract used by Slack, Linear, GitHub, dashboard, and scheduled agent/reviewer triggers. `assistant_id` selects `agent` or `reviewer`; `source` determines input identity and is retained for metadata/logging, not graph selection. The dispatcher rejects ambiguous combinations of a prebuilt input with content or identity arguments, ensuring callers choose either a fully constructed `RunInput` or build one from content, context, and identities.

The durable defaults are intentional:
- **`multitask_strategy="interrupt"`** — a follow-up halts the active run (progress preserved by its checkpoints) and resumes the agent with full history plus the new message. On an idle thread it just starts. Background follow-ups such as scheduled work can explicitly opt into another strategy like `enqueue` for background queuing instead.
- **`durability="async"`** — checkpoint every step, written while the next one runs, so a crash or worker recycle resumes from at most one step back. (`"sync"` made every step wait on its write, adding ~0.3s per model/tool step in production; dashboard-started runs already use the platform's async default.)
- **Stream resilience** — `stream_resumable=False` omits run-completion event replay from the platform's event store, allowing the dashboard to read thread history from its own transcript database instead. This prevents the Agent Server's Redis from accumulating events; the dashboard observes a run it did not start by reattaching to its thread and reading new events as they emit.
- **v3 streaming shape** — the same `stream_mode` set, `stream_subgraphs` flag, and compatibility marker (`__event_streaming_v2`) that `langgraph_api`'s `run.start` command applies when the dashboard submits a run. The server fixes a run's streaming protocol at creation: without the marker a run streams `values` only, so the dashboard sees no `tools` events or subagent namespaces for externally triggered runs.

Completion notification is best effort. The dispatcher attaches a webhook only when `RUN_COMPLETE_WEBHOOK_SECRET` is configured and `COMPLETION_WEBHOOK_URL` is absolute and non-loopback. Otherwise it logs the condition and creates the run without a webhook, avoiding a configuration error that would poison all run creation.

Thread execution context is durable: LangGraph checkpointing retains graph state, while LangGraph thread metadata holds the sandbox ID and related thread settings. The sandbox cache is in process and keyed by thread ID; another worker reconnects using the persisted ID. An existing unreachable sandbox raises rather than being automatically replaced, because silent replacement can discard uncommitted work. Reviewer callers can allow replacement because their checkout is re-derived. The sandbox is published to the cache only after initialization and metadata binding succeed. See [Invocation](../workflows/invocation.md).

## Cloud and desktop product surfaces

The cloud manifest currently pins Python 3.14 and LangGraph API version >~=0.15.0rc1. Its checkpointer TTL uses `delete`, sweeps every 60 minutes, and defaults to 43,200 minutes. The Dockerfile instructions attempt to build and install the dashboard static assets but allow a backend-only deployment if that build fails.

The `ui/` application is a TanStack Router React client with routes for agent sessions and threads, local sessions, plans, automations, skills, reviews and styles, administration, integrations, usage, settings, environments, instructions, and sandbox views. The `/agents` layout requires a session except for enabled desktop-local routes and selects `cloud` or `local` streaming transport from the active route. Router `basepath` follows Vite's build base, allowing the bundle to run below a configured mount prefix.

## Operations and safe changes

- Add a deployable graph by exporting a stable factory through `openswe/graphs/` and registering it in the appropriate manifest. Do not assume it becomes eligible for `dispatch_agent_run`; that contract selects only `agent` and `reviewer`.
- Add browser APIs through `create_app`, preserving session and mutation-origin protections rather than bypassing the dashboard boundary.
- Treat a coding sandbox that is unreachable as a recovery decision, not a cache miss. Replacing it changes the thread working tree.
- When changing dispatch defaults or stream fields, test durable run creation and cross-surface event attachment: dashboard observability relies on replayable v3-compatible streams for runs created outside the browser.
- When changing desktop path handling, retain real-path validation, the allowlist/worktree boundary, and artifact routing; each prevents a distinct local safety or repository-hygiene failure.

Related pages: [Invocation](../workflows/invocation.md), [Dashboard UI](../integrations/dashboard-ui.md).
