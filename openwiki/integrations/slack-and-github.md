---
type: integration
title: Slack & GitHub Integrations
description: Event routing and dispatch from Slack/GitHub webhooks, message formatting, thread management, bidirectional notifications, and code channel binding.
tags: [webhooks, slack, github, integrations, event-routing, thread-management, notifications, message-parsing]
verified:
  - by: openwiki/0.4.2
    at: 2026-10-17T12:03:09.529Z
sources:
  - id: openwiki-source-913527bc7b548b4bf81f6a35
    resource: repo://openswe/completion.py
  - id: openwiki-source-1685d34aae8025be9332f45a
    resource: repo://openswe/dispatch.py
  - id: openwiki-source-ac9f918f457353b3a27ad7be
    resource: repo://openswe/github/notifications.py
  - id: openwiki-source-d0edf7555209b3e6418b5c5f
    resource: repo://openswe/github/routes.py
  - id: openwiki-source-9ad7888a549990068f28dbdc
    resource: repo://openswe/github/webhook.py
  - id: openwiki-source-7f665eda03d736dd3db8c67c
    resource: repo://openswe/slack/code_channels.py
  - id: openwiki-source-96741ebe03021917e4f6995d
    resource: repo://openswe/slack/parsed_message.py
  - id: openwiki-source-495c786db57f684c1095e1a4
    resource: repo://openswe/slack/records.py
  - id: openwiki-source-c1d629bf5196269b73880148
    resource: repo://openswe/slack/routes.py
  - id: openwiki-source-bffcd70d616a6d966fad8308
    resource: repo://openswe/slack/thinking.py
  - id: openwiki-source-72370931d61f0a7232adcf12
    resource: repo://openswe/slack/webhook.py
  - id: openwiki-source-3087256f0cd599176fba3c38
    resource: repo://openswe/webhooks/common.py
generated: { by: "openwiki/0.4.2", at: "2026-10-17T12:03:09.529Z" }
---

# Slack & GitHub Integrations

Open SWE accepts work from Slack and GitHub webhooks, routing validated events to durable agent/reviewer runs while maintaining bidirectional session context. The integration layer decouples signature verification and admission from execution: webhooks return `202 Accepted` immediately after lightweight checks, then background workers construct run input, resolve thread identities, and dispatch to LangGraph.

## Event admission and routing

### GitHub webhooks

The GitHub webhook route (`POST /webhooks/github`) validates HMAC signatures using `X-Hub-Signature-256` and rejects unsigned or invalid payloads with `401`. Accepted event types include:

- **PR lifecycle**: `opened`, `edited`, `ready_for_review`, `converted_to_draft`, `closed`, `reopened`, `synchronize`
- **Review and CI**: `pull_request_review`, `check_run`, `workflow_run`, `deployment_status`
- **Issue work**: `issues` and `issue_comment` when tagged with `@open-swe`
- **Push events** for reviewer watch evaluation (enabled repositories only)

The route filters by supported action, applies repository allowlist checks via `repo_is_routable`, enforces public-repository organization gates, and forwards accepted events to background workers. Invalid signatures, malformed JSON, and unroutable repositories receive explicit rejection; unsupported event types are silently ignored with `{"status": "ignored"}`.

### Slack webhooks

The Slack webhook route (`POST /webhooks/slack`) validates signatures using HMAC-SHA256 (`X-Slack-Signature`) and an internal request timestamp. It handles multiple Slack event types:

- **URL verification challenges** (Slack retry handshake)
- **Event API messages**: mentions, DMs, thread replies, reactions, message edits
- **Slash commands**: `/ask`, `/btw`, `/breakout:web`
- **Block Kit interactions**: buttons, select menus, code channel actions
- **App mentions** anywhere in a channel

Slack message filtering is aggressive: bots and self-messages are rejected, message updates validate identity and content change, and ordinary non-code-channel messages route only if they are mentions, DMs, replies to ready-plan, or permitted untagged two-party replies. Code channels are special: every interaction shares the channel's session thread and treats every message as directed at Open SWE.

Before scheduling work, the Slack route claims an event ID in the store to deduplicate retried deliveries, preventing duplicate runs from the same webhook.

## Thread identity and resolution

### Slack thread binding

A Slack thread is persistent within a channel: each distinct `(channel_id, thread_ts)` binds to exactly one Open SWE thread. The system tracks this binding in the `SlackThread` record, which holds:

- **Thread identity mapping**: `channel_id`, `thread_ts`, and the corresponding `thread_id` (or a detach nonce if the binding was dissolved)
- **Solo-user routing**: for two-party conversations, the system tracks one person (`solo_user_id`) whose untagged messages route to the thread; a second person's message marks the thread `solo_blocked`, and untagged routing stops
- **Kickoff message**: the first Open SWE reply in a new thread is flagged as the kickoff; when that message is removed, the kickoff record expires (TTL 7 days) and future replies replace the thread's thread_id rather than recovering the same one

Thread resolution uses a priority order: an explicit stored mapping takes precedence, then matching thread metadata, then a deterministic Slack-derived ID. Conflicting metadata matches raise `SlackThreadMappingError` and refuse to guess.

### Code channels

Code channels are Slack channels owned by an agent, identified by a special property flag (`record_channel.record_type == "agent_channel"`). Every interaction in a code channel is treated as part of the same persistent session, keyed by a synthetic timestamp `"0"` (the `CODE_CHANNEL_SESSION_TS`). Unlike ordinary Slack threads:

- All messages and actions route to one agent session regardless of who sends them or what channel thread they land in
- The session has a dedicated status display showing current progress and available commands
- Each channel interaction is explicitly directed (no two-party routing restrictions)

### GitHub thread identity

GitHub issues and PRs derive stable thread IDs from identifiers rather than live APIs:

- **Issue threads**: derived from the issue ID (deterministic across repositories)
- **PR comment threads**: derived from repository + PR number + commenter
- **Reviewer threads**: derived from repository + PR number (for auto-review runs)

This allows multiple webhook deliveries or later dashboard access to recover the same thread state.

## Message parsing and input construction

### Slack message parsing

Slack messages addressed to Open SWE are parsed by `ParsedSlackMessage` to extract:

- **Action**: an optional command like `/btw`, `/breakout`, or `/breakout:web`, which is the first unquoted word after the bot mention or at the message start
- **Workspace selection**: `/workspace:<name>` or legacy `workspace:<name>`/`env:<name>` tags detected anywhere outside quotes
- **Performance model flag**: `/model:perf` or `/model:performance` anywhere in the message outside quotes
- **Prior text**: text the sender wrote before mentioning Open SWE (for breakout context)
- **Argument**: the remaining message text after parsing actions and options

Text inside backticks, quotes, or code blocks is masked during parsing so commands within literals are not recognized.

### Input message construction

The Slack webhook handler constructs a `RunInput` containing:

- **Channel identity**: Slack channel ID, name, topic, purpose, linked repository, dashboard URL, and LangSmith trace link
- **Person identity**: the Slack user who sent the message, with profile mapping to GitHub identity
- **System messages**: context prompts for the conversation type (code channel, kitchen channel, DM, non-kitchen channel, or message update)
- **Message history**: historical thread messages (up to 500) formatted as attributed text blocks with sender, timestamp, and content
- **Attachments and files**: images are embedded as vision blocks; non-image files are staged in the sandbox up to 10 total, with URLs embedded in the message text

The system avoids re-sending context that the agent has already seen: it reads the thread's current message state and filters out Slack timestamps and context hashes that are already visible to the model.

GitHub issues and PR comments construct prompts from issue/PR metadata, body, and comments, with trusted-author detection to identify which commenters are known Open SWE users.

## Slack thread management

### Explicit request handling

An explicit request (marked mention with `@open-swe`, slash command, code-channel action, or explicit tag) uses `multitask_strategy='interrupt'`. This halts any active run on that thread (preserving its checkpoints), then resumes the agent with the full message history plus the new input. On an idle thread, it simply starts a new run.

Untagged two-party replies and other follow-ups use `multitask_strategy='enqueue'`, which queues the follow-up behind active work and preserves ordering.

### Message edits

When a user edits a Slack message they previously sent:

1. The edit is routed through `_process_slack_message_update`, which looks up the thread ID via `(channel_id, thread_ts)` mapping and the delivered message via the message's timestamp
2. Rather than creating a new run, the edit is queued in the store as a message-queue entry
3. At the next model boundary in the thread, the before-model middleware deletes the original message from the model's state and injects the edited version
4. This allows the agent to correct its understanding without spawning a parallel run

### Thinking status and progress streaming

Active runs stream tool progress and thinking steps into Slack via "Thinking Steps" (Slack's native thinking format). The `SlackThinkingStream` handler:

- Maps LangGraph tool events to sanitized step summaries (e.g., file operations, command execution, external API calls)
- Limits output to 256 characters per step to stay within Slack's constraints
- Updates status at regular intervals (~1s flush interval) or on step completion
- Handles background tasks and sideways task dispatch (subagents) with labeled namespaces

When a run completes or times out, the stream closes and the last status is synced as a completion message.

## GitHub notifications and PR integration

### PR state tracking

Agent threads track their associated pull request(s) in thread metadata: `pr_url`, `pr_urls`, or `pull_requests`. When a PR is opened, closed, or receives commits, webhooks update this metadata so subsequent runs know their context.

### Auto-review dispatch

When auto-review is enabled for a repository:

- **PR open/ready**: `process_github_pr_ready` is invoked, which creates a reviewer run using the PR payload
- **Push to watched PR**: `process_github_push_event` is invoked to re-evaluate watched PRs and trigger re-review if needed
- **Check runs and CI events**: `process_github_ci_event` handles check_run, workflow_run, and deployment_status events to collect CI feedback

Draft PR review is gated by an author profile flag (`review_draft_prs`) with a workspace default fallback.

### Review notifications to Slack

When a GitHub review is submitted on a PR monitored by an agent thread, `notify_slack_review` posts a notice to the thread's Slack location:

- Uses event claims with a 30-day TTL to ensure each review notice is delivered exactly once (even if the webhook is retried)
- Formats the notice with the reviewer, PR label, and review state (approved/changes requested/commented)
- Attempts to find the thread's Slack location via `get_active_slack_thread`, using a mutation lock to serialize concurrent updates
- Posts the notice as a thread reply, unfurling links disabled to keep the output clean

### Issue and comment processing

GitHub issues and issue comments tagged with `@open-swe` are routed to `process_github_issue` or `process_github_pr_comment`:

1. Resolve the GitHub user's email to map to a known Open SWE user
2. React to the comment with 👀 (if a token is available)
3. Fetch historical comments and construct a prompt
4. Resolve or create a thread for the issue/comment pair
5. Dispatch an agent run with the prompt

## GitHub App token and credential management

Slack runs require a valid GitHub credential for the mapped triggering user, because agent work opens pull requests as that user. The system:

- Checks for a cached GitHub token for the thread's email mapping
- Falls back to an app installation token if available
- Requires user re-authentication if no credential is found (returns an account-link prompt in Slack instead of dispatching a run in bot-token-only mode)
- Handles GitHub 401 responses by attempting to refresh the token, falling back to app token if the refresh fails

### Token scope and PR state

When a PR webhook arrives, the system calls `event_token_repositories` to derive the repositories the firing token can access (using GitHub's token-scope API). This informs later agent decisions about which repositories are accessible.

## Run completion and bidirectional workflow

### Completion webhook

Every dispatched run includes a completion webhook URL and a shared-secret token. When a run finishes (success, error, timeout, or interrupt), LangGraph POSTs to `/webhooks/run-complete` with the final status and any error details.

The completion handler:

1. Verifies the webhook token
2. For **success**: enqueues deferred session-cost enrichment; Slack runs update their thread status
3. For **error** or **timeout**: posts a brief failure reply to the originating surface (Slack, Linear, GitHub, or Notion) if one hasn't already been sent for that run
4. Publishes completion events to trigger UI invalidations or monitoring

Failure replies are idempotent: the handler tracks run IDs to avoid posting duplicate "something went wrong" messages, and caps consecutive failure replies at 3 per thread to prevent flooding.

### Deferred status updates

Baby-sit checks and background task completions enqueue messages or status updates rather than interrupting active work. These are consumed by the before-model middleware at the next model boundary, allowing the agent to incorporate CI feedback without spawning a parallel run.

## Configuration and operational concerns

### Signature verification

Both Slack and GitHub webhooks fail closed when verification secrets are missing:

- `SLACK_SIGNING_SECRET`: required for Slack webhook verification; missing secret causes route to reject all calls with `401`
- `GITHUB_WEBHOOK_SECRET`: required for GitHub webhook verification; missing secret causes route to reject all calls with `401`
- `RUN_COMPLETE_WEBHOOK_SECRET`: required for completion webhook verification; missing secret disables failure replies and completion notifications

### Rate limiting and retry

Slack and GitHub both retry failed webhooks. The system:

- Returns `202 Accepted` immediately after admission checks so webhooks succeed and are not retried
- Claims event IDs to deduplicate retried Slack events before scheduling work
- Returns `503` (Service Unavailable) for temporary failures like workspace-ownership lookups so GitHub retries; persisting errors lead to ignored/dropped events
- Respects Slack rate-limit response headers and backs off exponentially when updating thread status

### Per-run context capture

Every run captures its source, originating user, and Slack/GitHub location in thread metadata and source context. This enables:

- Completion handlers to route replies back to the correct surface
- Transcripts to record where work originated
- Analytics to attribute costs to sources
- Later runs to know what conversation context exists

## Extension points

- **Webhook signature verification**: `verify_github_signature` and `verify_slack_signature` can be swapped to support different signing schemes
- **Thread resolution**: custom implementations of `resolve_slack_thread_id` can use different mapping strategies
- **Input construction**: `RunInput` and message formatting can be customized per conversation type
- **Completion handlers**: custom routes can be mounted to post completion notifications to other surfaces (already supported: Slack, Linear, GitHub, Notion)
- **Event filtering**: admission logic for Slack messages and GitHub events can be customized to add organization-specific gates or repository filters
