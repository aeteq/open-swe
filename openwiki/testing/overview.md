---
type: testing strategy
title: Testing Infrastructure and Validation Patterns
description: Test organization, fixture strategies, E2E setup, and focused validation patterns for agent behavior, middleware, integrations, and production boundaries.
tags: [testing, pytest, vitest, playwright, e2e, fixtures, isolation, fakes]
verified:
  - by: openwiki/0.4.2
    at: 2026-10-19T15:23:56.456Z
sources:
  - id: openwiki-source-24f77a48f966a05631988d08
    resource: repo://desktop/package.json
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
  - id: openwiki-source-5b54a58d1b51cd490b0e7162
    resource: repo://package.json
  - id: openwiki-source-05ccef8d4cf1698187f20464
    resource: repo://pyproject.toml
  - id: openwiki-source-a7a923eb42c2ccc6f4c875de
    resource: repo://tests/agent/test_agent_assembly_context.py
  - id: openwiki-source-f0a6e7dc03522b2682f88655
    resource: repo://tests/conftest.py
  - id: openwiki-source-069ae2b497200c26ef2dc134
    resource: repo://tests/e2e/fake_llm.py
  - id: openwiki-source-8317f526f4e30c2659c8614e
    resource: repo://tests/e2e/fakes.py
  - id: openwiki-source-c484c171a84d342028bf0794
    resource: repo://tests/e2e/global-setup.ts
  - id: openwiki-source-aefe409f90608437573cbad3
    resource: repo://tests/e2e/harness.py
  - id: openwiki-source-859f98720585f4648f0f7b2e
    resource: repo://tests/e2e/playwright.config.ts
  - id: openwiki-source-4b944ec14a3d793a6f771403
    resource: repo://tests/e2e/playwright.desktop.config.ts
  - id: openwiki-source-7ef60dc4372e1a33c7728fe6
    resource: repo://tests/e2e/README.md
  - id: openwiki-source-86954185ec7b6e72d7a5a7a7
    resource: repo://tests/e2e/tests/desktop.spec.ts
  - id: openwiki-source-4cedab06aadc98083b348ddb
    resource: repo://tests/e2e/tests/full_flow.spec.ts
  - id: openwiki-source-ec3fbe14e1e05123704c4f28
    resource: repo://tests/reviewer/test_reviewer_outcomes.py
  - id: openwiki-source-f05d7497d4c60c3b322628eb
    resource: repo://tests/sandbox/test_sandbox_state.py
  - id: openwiki-source-a9842c19fa28878dfa7fcd61
    resource: repo://tests/webhooks/test_completion_webhook.py
  - id: openwiki-source-440ae1e215cb02721dda855c
    resource: repo://turbo.json
  - id: openwiki-source-436f4179fe22abf615d2f7d0
    resource: repo://ui/package.json
generated: { by: "openwiki/0.4.2", at: "2026-10-19T15:23:56.456Z" }
---

# Testing Infrastructure and Validation Patterns

The testing strategy separates concerns by layer: focused pytest tests for agent, middleware, reviewer, sandbox, and webhook behavior; dashboard Vitest for React rendering and client state; desktop Node tests for Electron main-process code; and Playwright for real webhook, authenticated dashboard, git/sandbox, and Electron integration. Choose the test layer that owns the contract being changed, running it in isolation with fakes and mocking only external boundaries.

## Test layer decision tree

- **Agent, middleware, reviewer, sandbox, webhook, tools**: Focused pytest in asyncio auto mode
- **Dashboard React component or client utility**: Dashboard Vitest
- **Electron main process**: Desktop Node test
- **Real webhook, UI auth, git, Electron integration**: Focused Playwright E2E

Test layer responsibilities: pytest owns Python backend contracts via unit tests with fakes; Vitest owns frontend React components; Node tests own Electron main process; Playwright owns real webhook routes, UI integration, and end-to-end flows through the agent.

## Python test organization and fixtures

### Pytest configuration and execution

Pytest collects tests from `tests/` (per `testpaths` in `pyproject.toml`). Tests run in asyncio auto mode (`asyncio_mode = "auto"`), so async test functions and fixtures are awaited automatically without per-test markers. Install development dependencies with `make install`, which runs `uv sync --extra dev`; the dev group includes pytest, pytest-asyncio, Ruff, ty, and Pygments.

```bash
make install
make test TEST_FILE=tests/sandbox/test_sandbox_state.py
uv run pytest -vvv tests/sandbox/test_sandbox_state.py::test_sandbox_proxy_retries_failed_startup
make lint
make typecheck
```

`make test` (alias `make tests`) executes `uv run pytest -vvv $(TEST_FILE)` when the path exists; otherwise it prints a skip message. Use `TEST_FILE` for a file or directory path; for a single node id like `file.py::test_name`, invoke pytest directly. Quality gates are independent: `make lint` runs Ruff checking and a format diff, `make format` fixes code in place, and `make typecheck` runs `ty check openswe tests`.

### Shared fixtures and isolation

`tests/conftest.py` provides autouse fixtures that make unit tests independent of a live Store and built dashboard:

- **`_no_bundled_dashboard`** (autouse): Points `DASHBOARD_STATIC_DIR` to a missing temporary directory so a locally built `ui/.output` cannot influence Python tests.
- **`_reset_ttl_cache`** (autouse): Clears the process-global TTL cache before and after each test, preventing cached team settings from leaking between tests. Also clears the langgraph_api in-process cache when not running against a PostgreSQL backend.
- **`_reset_sandbox_registries`** (autouse): Clears `SANDBOX_BACKENDS` and `SANDBOX_CONNECTIONS` (process globals) to prevent one test's sandbox from answering for another's thread.
- **`_default_enable_auto_review`** (autouse): Stubs `is_review_repo_enabled` to return `True` for every repository because the dashboard opt-in list is empty without a live Store. Tests targeting the auto-review gate must override it with a stricter policy.
- **`_offline`** (autouse): Refuses real network requests; MockTransport, ASGITransport and local fakes still work. Tests that need HTTP use inline async httpx clients or fixtures like `slack_api`.
- **`registry_db`** and **`registry_db_if_available`**: Isolated PostgreSQL schemas for pull-request and repository rows; required for tests using the real database code path. Set `TEST_ANALYTICS_POSTGRES_URI` to enable.
- **`slack_api`**: A mock Slack API server for tests driving real Slack endpoints without credentials.
- **`allowed_bot`**: Seeds a test Slack bot configuration; requires the `registry_db` fixture.
- **`user_records`**: Routes every `UserRecords` access to an in-memory table for the test.
- **`grant_tool_access`**: Resolves every gated tool call to `Access(**fields)` for the test.
- **`memory_event_claims`**: In-memory claims without PostgreSQL (claims held forever, never lapsing).

### System-boundary test locations and patterns

Use the narrow test family that carries the failure semantics being changed:

| Change | Focused location and protected behavior |
| --- | --- |
| Main agent construction, source-specific tools, backend, skills, or middleware | `tests/agent/test_agent_assembly_context.py`; it verifies the initialized `CompositeBackend`/`SandboxBackendProxy` arrangement, read-only skills, dynamic browser-tool exposure, and parent-only tool boundaries. |
| Reviewer findings, published reviews, reconciliation, check runs, or learning outcomes | `tests/reviewer/test_reviewer_outcomes.py`; maps resolution and feedback into true/false-positive outcomes and treats absent credentials or repository data as a no-op. |
| Lazy sandbox reconnection, capture offload, or sandbox identity recovery | `tests/sandbox/test_sandbox_state.py`; requires `BaseSandbox` compatibility, safe offload fallback, one shared reconnect, cancellation-safe waiting, retry after failed startup, and live-thread metadata fallback. |
| Completion notification and reviewer error cleanup | `tests/webhooks/test_completion_webhook.py`; errors on Slack-originated work send a thread reply and record the run, while reviewer failures settle a tracked check when its metadata and token exist. |
| Dashboard routes, thread API, session gate, or server rendering | `tests/dashboard/`; for example `test_dashboard_thread_api.py` verifies `/dashboard/api/*` behavior, and `test_dashboard_ui.py` asserts SSR and session requirements. |
| Middleware ordering, tool composition, error recovery, or state transitions | `tests/middleware/`; each middleware has focused contract tests (e.g., `test_model_fallback_middleware.py` for retry logic, `test_stable_tool_order.py` for ordering). |

Tests are organized by system owner: `tests/agent/`, `tests/reviewer/`, `tests/sandbox/`, `tests/webhooks/`, `tests/dashboard/`, `tests/middleware/`, `tests/github/`, `tests/slack/`, and `tests/tools/`. Use prompt snapshots only to protect rendered output, configuration precedence, tool composition, or behavioral results—not to restate static prompt text.

## Frontend tests: Vitest and Node

### Dashboard unit tests

For dashboard component rendering, client-side utilities, and state management, use Vitest:

```bash
pnpm --filter open-swe-dashboard run test
```

Vitest runs via `vitest run` from the dashboard workspace. Write tests for React rendering, optimistic state, stream transformation, terminal state transitions, and API-client behavior before escalating to browser E2E.

### Desktop unit tests

For Electron main-process code, use Node's built-in test harness:

```bash
pnpm --dir desktop run test
```

The desktop package builds its main bundle first, then runs `node --test test/*.test.cjs`. Tests verify IPC, window lifecycle, git operations, and local-agent invocation without launching a full browser.

### Root test delegation

`pnpm test` at the repository root delegates all workspace test tasks to Turbo, running dashboard Vitest and desktop Node tests in parallel. Use it after broad changes; otherwise target the workspace:

```bash
pnpm --filter open-swe-dashboard run test
pnpm --dir desktop run test
```

## End-to-end: Playwright with controlled boundaries

The E2E suite proves production integration without relying on live SaaS. It runs the real agent code end-to-end with real Deep Agents, real tools, real middleware, and real LangGraph checkpoints. Only the LLM and external SaaS HTTP boundaries are faked; everything else is production code.

### E2E philosophy: real agent, faked only at boundaries

The E2E suite exercises the **whole happy path** end-to-end:

1. A user posts a message to a **mock Slack** thread.
2. The **real agent** runs on Managed Deep Agents (`mda/`): its deepagents loop on the real MDA dev server, its tools and middleware execute on the real `langgraph dev` backend.
3. The agent implements a change in a **local temp-dir sandbox** (real sandbox provider), pushes a branch, and opens a PR on a **fake GitHub**.
4. It posts the PR link back to the **same Slack thread** — visible in the mock UI.

Only these boundaries are faked:

- **LLM**: A scripted `BaseChatModel` (`fake_llm.py`) that emits a fixed tool sequence, allowing deterministic test scenarios without actual model calls.
- **External SaaS HTTP endpoints**: GitHub and Slack REST APIs, GitHub OAuth token mint, and LangSmith snapshot service.
- **Token lookups**: GitHub App installation and token mint, `api.github.com/user` identity.

Everything else is production code:

- Webhook routes, agent graph, deepagents loop, tools, middleware, real local sandbox provider, real git, real browser UI, real dashboard server rendering.
- In-memory PR/Slack stores (`fakes.py`) serve as the single source of truth; the mock UIs render them, and tests assert on them.
- Seeded local bare remote that the agent clones and pushes to.

### E2E test flow

The E2E test harness (`harness.py`) overlays the real `openswe.webapp` with fake endpoints, mock UIs, and control routes:

1. **Test setup** via `/control` endpoints: reset harness state, seed user credentials, issue session cookies.
2. **User posts to `/fake-slack`**: the mock Slack UI sends a signed message to the real webhook route.
3. **Webhook routes to the real app**: `process_slack_mention` runs for real, dispatching the run to LangGraph.
4. **Agent runs on Managed Deep Agents**: the real agent executes with the scripted fake LLM for tool selection.
5. **Tools execute for real**: `open_pull_request` hits the fake GitHub, `slack_reply` hits the fake Slack.
6. **Agent posts `/fake-slack` reply**: the thread is updated with the PR link.
7. **Test asserts on fake store state**: the in-memory PR/Slack stores hold exactly what the real agent produced.

### E2E architecture: real dashboard and full flow

The browser suite drives the **actual built `ui/` React application**—not a mock—served same-origin from the harness so the session cookie and `/dashboard/api/*` calls work without CORS. Global setup (`global-setup.ts`) builds the real dashboard once (cached unless `E2E_FORCE_UI_BUILD=1`), starts its Nitro server on `E2E_UI_PORT` (default 3100), and the harness proxies page requests to it. This exercises real server rendering—the root session gate, the redirect, hydration—instead of a static shell.

`full_flow.spec.ts` proves the Slack request → implementation → PR → same-thread reply path. The browser directory also contains specs for dashboard/thread behavior, environment and plan approval, Slack redelivery/debouncing, SSR, output iframe, sandbox identity, and workspace scenarios.

```bash
pnpm install --frozen-lockfile
pnpm run test:e2e:install          # install Chromium dependencies
pnpm exec playwright test tests/full_flow.spec.ts  # single spec
pnpm run test:e2e                  # full browser suite
```

The browser configuration runs serially with one worker, ignores `desktop.spec.ts`, uses a 90-second test timeout, and reuses a warm `langgraph dev` server outside CI.

### Desktop E2E: Electron local-agent flow

The desktop spec (`tests/desktop.spec.ts`) separately resets harness state, clones the seeded local bare remote into an isolated temporary project, installs a harness-issued `osw_session` cookie, invokes the local-agent request, and verifies both the local project edit and fake-GitHub PR fields.

```bash
pnpm run test:e2e:desktop
```

The desktop spec:

1. Resets the shared harness state via `/control/reset`.
2. Clones the seeded fake-GitHub remote into an isolated temp directory.
3. Issues a session cookie via `/control/login`.
4. Launches Electron with the local project, session cookie, and isolated git config.
5. Types a message into the local-agent composer.
6. Waits for the agent to complete and verify the edit was made locally and the PR was opened on fake-GitHub.
7. Explicitly traces the Electron context and attaches screenshots for the unified and completed views.
8. Cleans up temporary state unless `E2E_KEEP_TMP` is set.

The desktop configuration selects only `desktop.spec.ts`, raises timeouts to 180 seconds, uses a separate output directory, and disables automatic Playwright media recording because the spec explicitly records an Electron trace.

### Playwright configuration and artifacts

Recording costs real time on every spec, so browser tests keep a **trace** (DOM-snapshot timeline + network + console + source) and a **video** only for a failed attempt; failures also get a screenshot. Set `E2E_ARTIFACTS=1` to capture both unconditionally, which is what you want when a spec passes but does the wrong thing. The Desktop test records an Electron trace and a success screenshot. Artifacts land in `test-results/<test>/` and `playwright-report/`:

```bash
pnpm exec playwright show-report                       # browse runs; each has a Trace tab
pnpm exec playwright show-trace test-results/<test>/trace.zip   # open one trace directly
```

In CI the browser shards upload **playwright-report-1**, **playwright-report-2**, and **playwright-report-3**; Desktop uploads **playwright-report-desktop**. Each contains `playwright-report/` and `test-results/`. Download the relevant artifact, then `pnpm exec playwright show-report <unzipped-dir>` (or drag a `trace.zip` onto <https://trace.playwright.dev>) to replay.

The backend requires PostgreSQL: export `POSTGRES_URI` before running the suite or `langgraph dev` (a throwaway `docker run -d -p 5433:5432 -e POSTGRES_PASSWORD=postgres postgres:16` with `POSTGRES_URI=postgresql://postgres:postgres@localhost:5433/postgres` is enough). CI provides one as a job service.

Poke at it by hand (from the repo root):

```bash
uv run langgraph dev --config tests/e2e/langgraph.e2e.json --port 2024 \
  --no-browser --allow-blocking --no-reload
# open http://127.0.0.1:2024/mock/slack  and  /mock/github
```

### Fake LLM: scripted agent behavior

The fake LLM (`fake_llm.py`) is the only faked piece of the agent. It is a `BaseChatModel` subclass that drives the real deepagents loop with a fixed sequence of tool calls:

1. Execute a shell script that creates a feature branch and adds a file.
2. Call `open_pull_request` with the real tool to create a PR on fake-GitHub.
3. Read the actual PR URL from the preceding tool result.
4. Call `slack_reply` with the real tool to post the PR link back to the thread.

This allows deterministic test scenarios where the agent's model decisions are scripted but all tools and middleware run for real.

### Fake stores and mock UIs

In-memory stores (`fakes.py`) hold PR and Slack state and serve as the single source of truth:

- **PR store**: PR files carry a real per-file `patch`, so eligibility checks that read the diff see what GitHub would return.
- **Slack store**: Thread messages, ephemeral replies, and views are stored in memory.
- **Local bare remote**: A seeded git repository that the agent clones and pushes to.

The mock UIs (`static/slack.html`, `static/github.html`) are minimal JavaScript that render the fake stores, allow test interaction, and display agents' output. The dashboard is **not** mocked — it's the real `ui/` app served same-origin.

### E2E harness architecture

The harness (`harness.py`) mounts the real `openswe.webapp` application plus:

- **Fake GitHub REST API** (`/fake-gh/...`): Implements PR creation, file reads for diff eligibility, and check-run settlement.
- **Fake Slack API** (`/fake-slack/...`): Implements message posting and user lookups.
- **Mock UIs** (`/mock/slack`, `/mock/github`): Render the fake stores for test interaction.
- **Control endpoints** (`/control/*`): Allow test setup via reset, login, and signed webhook delivery.

Nothing in the harness touches agent logic — it only stands in for the SaaS boundaries and renders their state back as a user-facing UI.
