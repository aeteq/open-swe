---
type: architecture-component
title: Middleware and Failure Boundaries
description: Ordering-sensitive middleware around the coding agent and reviewer model and tool loops. Explains preparation, policy, retries, deadlines, completion hooks, and how failures become safe user-visible outcomes.
tags: [middleware, agent, reviewer, model-call, tool-call, fallback, guardrails]
sources:
  - id: openwiki-source-e1f102c9268ae755c7487b1e
    resource: repo://agent/middleware/deliver_event_matches.py
  - id: openwiki-source-991c2ce9c2221af2a4467690
    resource: repo://agent/middleware/image_model_fallback.py
  - id: openwiki-source-0b53777f0ea426a90cf976b4
    resource: repo://agent/middleware/model_call_timeout.py
  - id: openwiki-source-92dfac98dd4efa19a44e0c4e
    resource: repo://agent/middleware/model_errors.py
  - id: openwiki-source-5bbb58a2bed24dc7e0fea26d
    resource: repo://agent/middleware/model_fallback.py
  - id: openwiki-source-f996b5011c02e2c53895ada1
    resource: repo://agent/middleware/notify_step_limit.py
  - id: openwiki-source-de97adb0acb9dec0664a44b6
    resource: repo://agent/middleware/prepare_run.py
  - id: openwiki-source-739850fbbfceb2f1f047ce4e
    resource: repo://agent/middleware/record_run_usage.py
  - id: openwiki-source-9d5775155057d8f8c3a08e3e
    resource: repo://agent/middleware/refresh_github_proxy.py
  - id: openwiki-source-68ed7096f2c698e329abb45c
    resource: repo://agent/middleware/repair_orphaned_tool_calls.py
  - id: openwiki-source-626b1e5ad4f4c7d45dbc8f12
    resource: repo://agent/middleware/settle_review_check.py
  - id: openwiki-source-bcc3375e7c46eaf87e2b2f28
    resource: repo://agent/middleware/task_retry.py
  - id: openwiki-source-a3215ee5f347eab65c5c27a3
    resource: repo://agent/middleware/tool_error_handler.py
  - id: openwiki-source-c53f5f816c45a89d9453ccd6
    resource: repo://agent/middleware/workflow_push_guard.py
  - id: openwiki-source-276ab38291eb5741b4c2141c
    resource: repo://agent/reviewer.py
  - id: openwiki-source-267a662990890ab782a8bf32
    resource: repo://agent/sandboxes/retry.py
  - id: openwiki-source-856ade03ef31ac38e1347f7c
    resource: repo://agent/server.py
  - id: openwiki-source-10026b2dd7b7368bb04e27f0
    resource: repo://tests/sandbox/test_reviewer_sandbox_recovery.py
  - id: openwiki-source-b074bf11145a0ff6206cec7b
    resource: repo://tests/sandbox/test_sandbox_retry.py
generated: { by: "openwiki/0.4.2", at: "2026-10-05T16:54:23.398Z" }
verified:
  - by: openwiki/0.4.2
    at: 2026-10-07T15:19:51.431Z
---

# Middleware and Failure Boundaries

`get_agent` and `get_reviewer_agent` pass ordered middleware lists to `create_deep_agent`. The list is an onion: earlier entries wrap later entries, so an outer layer can alter a request or handle an exception from every inner layer. This makes order part of the runtime contract, rather than an implementation detail. See [Quickstart](../quickstart.md), [Sandbox Lifecycle](sandbox-lifecycle.md), and [PR Creation](../workflows/pr-creation.md) for the graph, review, sandbox, and delivery contexts.

## Coding-agent stack

The coding-agent middleware chain is outer to inner:

1. `FilesystemMiddleware` — exposes file read/write/delete and directory navigation tools with configurable binary content offloading
2. `ConversationOffloadingMiddleware` — handles deferring of conversation context when configured by the user, permitting long runs without hitting provider context limits
3. `PrepareAgentRunMiddleware` — checkpointed per-run setup with fingerprinting to skip already-completed setup on resumed invocations
4. `TranscriptMiddleware` — processes the conversation state and populates the transcript for debugging and auditing
5. `IncidentMiddleware`, only if an incident session is present
6. `WorkspaceSkillsMiddleware`, only if configured (non-local, org admins)
7. `ValidateImageReadsMiddleware` — validates image-read tool calls, positioned after basic tool configuration
8. `ModelCallLimitMiddleware`
9. `ToolErrorMiddleware` — converts unhandled tool exceptions into status=error ToolMessages; treats unreachable sandbox as terminal
10. `ExcludeToolsMiddleware`
11. `SubdirAgentsReadMiddleware`
12. `ToolRetryMiddleware` for `task` — two retries, 1–10 second backoff
13. `PullRequestCreationGuardMiddleware`, except for local/desktop runs
14. `WorkflowPushGuardMiddleware`
15. `refresh_github_proxy_before_model`
16. `check_message_queue_before_model` and `deliver_event_matches_before_model`, except in stop-summary mode
17. `RequireUserReplyMiddleware`
18. `RequireCliResultMiddleware`, only if bridged (CLI) thread
19. `notify_step_limit_reached`
20. `record_run_usage`
21. `ModelSelectionMiddleware`, only if adaptive model routing is enabled
22. `ModelFallbackMiddleware`, only when a different fallback model resolves
23. `ImageModelFallbackMiddleware`, only when the primary model lacks vision support
24. `DynamicToolMiddleware`, only if integration groups are present
25. `SanitizeFireworksMessagesMiddleware`
26. `SanitizeOpenAIResponsesMiddleware`
27. `SanitizeThinkingBlocksMiddleware`
28. `StableToolResultOrderMiddleware`
29. `ModelErrorMiddleware`
30. `ModelCallTimeoutMiddleware`

The last three layers form the critical model-failure boundary. Provider-specific message cleanup and stable tool-result ordering prepare a valid provider request. `ModelCallTimeoutMiddleware` is innermost, so its wall-clock deadline includes the provider operation itself. It converts a stalled call to `ModelCallTimeoutError`, which is a `TimeoutError`; that exception first passes through `ModelErrorMiddleware` for classification and thread metadata, then reaches the optional fallback wrapper. Thus a hang becomes either a retried request or a controlled, visible end to the run rather than a silent parked invocation.

```mermaid
flowchart TD
  Fallback["Fallback retry wrapper"] --> Plan["Message sanitizers and stable result order"]
  Plan --> Errors["Model error recorder"]
  Errors --> Deadline["Model call deadline"]
  Deadline --> Provider["Provider call"]
  Provider -. "timeout exception" .-> Errors
  Errors -. "record and re-raise" .-> Fallback
  Fallback -. "attempts exhausted" .-> Outage["Terminal outage message"]
```
This is the inner model-call path: timeout errors are recorded before the outer fallback decides whether to retry them.

### Preparation, tools, and follow-up messages

`BasePrepareRunMiddleware` supplies checkpointed `before_agent` setup for the agent and reviewer specializations. It fingerprints the latest message, middleware class, and preparation configuration. A matching `run_prepared_for` latch skips already-checkpointed setup on a resumed invocation; a later invocation on the same thread gets fresh tokens, prompt material, and review/diff context. Preparation must remain idempotent because a failure before the checkpoint can run it again. Its model wrapper installs the rendered system prompt.

`TranscriptMiddleware` processes the conversation state and populates the transcript for debugging and auditing.

`DynamicToolMiddleware` exposes configured integration groups lazily, allowing lazy loading of MCPs and Notion tools only when the agent requests them. `ExcludeToolsMiddleware` filters disallowed tool names from model requests. `SubdirAgentsReadMiddleware` contributes applicable ancestor `AGENTS.md` instructions once per thread.

The proxy refresh hook runs before each model call. It refreshes a near-expiry sandbox GitHub-proxy installation token that expires after one hour. Next, the queue hook reads `("queue", thread_id)` from the LangGraph store, deletes `pending_messages` before constructing messages to avoid duplicate delivery, and injects queued human input in FIFO order. It also consumes a pending autofix event. The event-matches hook appends any owed webhook-driven events from the database in oldest-first order. Image content is omitted with a warning when the resolved model has no vision support.

### Limits, policy, and completion

`notify_step_limit_reached` is an after-agent hook that recognizes the model-call-limit marker and posts an explanatory Slack message when the agent hits its step limit.

The PR guard blocks `execute` and `background_execute` command forms that create a pull request outside `open_pull_request`, including GitHub CLI, API, curl, and bounded nested `bash -c` forms. It returns a tool error instead of executing and is not installed locally. The workflow-push guard permits a rewritten safe push affecting `.github/workflows` only after recorded human approval; otherwise it returns a blocked result containing an approval URL.

`record_run_usage` is also an after-agent completion hook. When the run has a preparation-run ID, it persists summarized token usage and schedules deferred cost enrichment. Its own persistence failures are logged at debug level and do not change the agent result.

`ModelErrorMiddleware` is inside fallback but outside the deadline. On any exception from the inner request, it logs full classified fields, writes the type and classification code to the LangGraph thread metadata when available, and re-raises unchanged. This preserves the meaningful provider-error category for completion handling even where platform exception messages are scrubbed.

## Retry and failure boundaries

`ModelFallbackMiddleware` is installed only when `LLM_FALLBACK_MODEL_ID`, or the primary model's default fallback, resolves to a different model. It makes one more attempt than its backoff schedule entries: by default six attempts with delays `0, 5, 15, 30, 45` seconds plus ±25% jitter. Attempts alternate primary and fallback models. It retries connection and timeout failures and selected provider statuses (including 408, 409, 425, 429, 5xx, and 529). An Anthropic/OpenAI model-not-available access error is immediately converted to a user-facing `AIMessage`; an exhausted transient budget normally returns an outage `AIMessage`, although `surface_outage_message=False` re-raises the final error.

`ImageModelFallbackMiddleware` routes image-bearing requests to a vision-capable fallback model when the primary model does not support images, preventing image-related failures on text-only models. When no fallback is available, image content is simply omitted with a warning.

`ModelCallTimeoutMiddleware` reads `OPEN_SWE_MODEL_CALL_TIMEOUT_SECONDS`, validates that it is positive, and otherwise uses 900 seconds. `asyncio.wait_for` makes a websocket or other provider stall observable; it deliberately sits above provider-level request timeouts, which get a chance to retry inside the provider client first.

Tool failures have a separate safety boundary:

* `ToolErrorMiddleware` turns ordinary unhandled tool exceptions into `ToolMessage(status="error")` JSON carrying error type, error text, and tool name when known, allowing the model to self-correct.
* `SandboxRetryableConnectionError` means the SDK rejected the WebSocket upgrade before the execute frame was sent. It is converted to a `sandbox_transient` tool error, explicitly stating that nothing ran or changed; retrying cannot double-run the command.
* A `SandboxConnectionError`, except `SandboxServerReloadError`, means the sandbox is unreachable. So does `ResourceNotFoundError` only when the missing resource is the sandbox. These are notified and re-raised to end the run: continuing would repeatedly fail and notify.

`retry_transient_sandbox_errors` is the corresponding direct-operation utility. It retries only the SDK-marked pre-start error, at most four times, with bounded exponential backoff and jitter; terminal sandbox errors are never retried. Unreachable notification prefers the active Slack thread, then Linear, then a configured GitHub issue or PR if a token is available. Coding-agent recovery deliberately does not auto-replace a sandbox because a fresh sandbox could conceal loss of uncommitted work; users can retrigger the thread or start a new one.

`ToolRetryMiddleware` is narrower: it wraps delegated `task` calls with two retries, one-second initial delay, and ten-second maximum delay. `task_retry_on` accepts retryable statuses and transient transport exception names, including a subagent `ModelCallTimeoutError`; subagents do not have fallback middleware. On exhaustion, `task_on_failure` returns structured `failed` data only for invalid-prompt/context-length failures and re-raises other errors.

## Reviewer stack and completion guarantee

The reviewer uses a deliberately smaller chain: `PrepareReviewerRunMiddleware`, `ModelCallLimitMiddleware`, `ToolErrorMiddleware`, `refresh_github_proxy_before_model`, `check_message_queue_before_model`, `SanitizeFireworksMessagesMiddleware`, `SanitizeOpenAIResponsesMiddleware`, `SanitizeThinkingBlocksMiddleware`, `RepairOrphanedToolCallsMiddleware`, `StableToolResultOrderMiddleware`, `ModelRetryMiddleware` (from langchain, retrying on `TimeoutError`), `ModelErrorMiddleware`, `ModelCallTimeoutMiddleware`, and `settle_review_check_on_exit`.

It omits conversation offloading, transcript, incident, workspace skills, dynamic tools, tool exclusion, subdirectory instructions, task retry, PR/workflow guards, run-usage recording, model selection, and model fallback. `RepairOrphanedToolCallsMiddleware` prevents an interrupted review from being permanently rejected by a provider: before a later model call, it inserts synthetic error `ToolMessage` results for tool-call IDs that have no result.

Reviewer sandbox setup opts into replacement because its checkout is re-derived for each run and a persistent PR thread should not be bricked by a dead sandbox. A failed replacement remains `SandboxUnreachableError` and is notified safely. `settle_review_check_on_exit` closes a tracked but unpublished GitHub review check as **neutral**, rather than falsely marking the PR's code as failed. If `publish_review` recorded a pending completion result whose PATCH failed transiently, the hook retries that real conclusion instead.

## Safe changes and focused tests

Preserve the outer-to-inner arrangement when adding middleware. In particular, moving the deadline outside fallback would prevent timeout recovery, and moving error recording outside fallback would miss failures the fallback consumes. Keep preparation idempotent, retain delete-before-inject queue semantics, and treat a sandbox error as retryable only when the SDK guarantees the command never started.

Focused middleware tests cover queue injection, dynamic tool behavior, preparation latching, orphaned-call repair, stable result ordering, timeout cancellation, fallback alternation/eligibility, step-limit notification, subdirectory instructions, usage recording, and model selection. Sandbox recovery tests verify that reviewer replacement is permitted, default coding-agent replacement is not, and a failed replacement remains typed. These are the tests to extend when changing an ordering edge, error classification, or a completion short-circuit.
