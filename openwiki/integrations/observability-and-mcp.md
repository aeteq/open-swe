---
type: integration reference
title: MCP and Integration Architecture
description: Model Context Protocol connections scoped by instance, workspace, and user; participant-scoped Notion MCP with OAuth; and tool loading lifecycle.
tags: [integrations, mcp, credentials, notion, oauth]
sources:
  - id: openwiki-source-b26707b64bee931c416620a7
    resource: repo://agent/dashboard/notion_oauth.py
  - id: openwiki-source-941341430e1d08d8e7e54dfe
    resource: repo://agent/dashboard/user_credentials.py
  - id: openwiki-source-dba44b44d32d913f00633189
    resource: repo://agent/mcp/instance.py
  - id: openwiki-source-6506a11d150e73042a77db68
    resource: repo://agent/mcp/runtime.py
  - id: openwiki-source-45f23fffe531869b52e199fb
    resource: repo://agent/mcp/user.py
  - id: openwiki-source-51bbec13fee43658b1adc3bd
    resource: repo://agent/mcp/workspace.py
  - id: openwiki-source-9103280889fa6c4d9c5bb0df
    resource: repo://agent/middleware/dynamic_tools.py
  - id: openwiki-source-856ade03ef31ac38e1347f7c
    resource: repo://agent/server.py
  - id: openwiki-source-2cd7e2018ae35c5972204803
    resource: repo://agent/tool_loaders/notion_mcp.py
  - id: openwiki-source-7c60191e42b8e30b62935af1
    resource: repo://agent/utils/thread_participants.py
generated: { by: "openwiki/0.4.2", at: "2026-09-22T13:11:45.998Z" }
verified:
  - by: openwiki/0.4.2
    at: 2026-09-22T13:11:45.998Z
---

# MCP and Integration Architecture

The agent offers extensible MCP (Model Context Protocol) connections and a Notion integration. MCPs are admin- or user-managed server connections that expose tool discovery and invocation; Notion is a built-in participant-scoped integration. Both are optional: missing credentials or connection failures remove the optional tools rather than blocking a run.

See [Authentication and security](../concepts/auth-and-security.md) for the broader trust model, [Tools](../concepts/tools.md) for dynamic tool availability, [Models, profiles, and instructions](../concepts/models-profiles-instructions.md) for model selection, and [Configuration](../operations/configuration.md) for environment settings.

## MCP connection scoping and discovery

MCP connections are organized in a three-tier hierarchy: **instance** (globally managed by deployment admins), **workspace** (managed by workspace admins per slug), and **user** (personal connections owned by an individual GitHub login). When loading tools for a run, all three tiers are consulted in order; a later tier's connection with the same name replaces the earlier one.

- **Instance tier** (`agent/mcp/instance.py`): Connections stored in `["instance_mcps"]` that every run can access. The tier adopts and migrates pre-workspace records from the flat `["workspace_mcps"]` namespace on first read, ensuring backward compatibility.
- **Workspace tier** (`agent/mcp/workspace.py`): Connections stored under `["workspace_mcps", <slug>]`, where `<slug>` is the lowercase workspace identifier. Each workspace has its own set of connections.
- **User tier** (`agent/mcp/user.py`): Personal connections stored under `["user_mcps", <login>]`, scoped to a GitHub login and visible only in runs where that login is the triggering user.

Each tier exposes its own admin UI route for creation, validation, token refresh, and discovery. A connection is a reusable MCP server reference with a name, URL, transport (streamable_http or SSE), optional headers (including OAuth token URLs and client secrets), and an optional allowlist of tool names to expose. Stored tokens are encrypted at rest with `agent.encryption`.

## Tool loading and availability

The server loads MCP tools during agent assembly for non-summary, non-local runs with a known credential scope. It loads the three tiers via `load_mcp_tools(*sources)` in `agent/mcp/runtime.py`, which walks each source's connection list, discovers tool definitions, and builds runnable tools. The `DynamicToolMiddleware` exposes only tool *names* initially and defers the MCP handshake (which may fail, timeout, or be expensive) until the agent explicitly calls `load_integration_tools` and requests to use them. This lazy strategy avoids blocking the first model call when MCP availability is uncertain.

Tool loaders use a stale-while-revalidate TTL cache (300 seconds for most tiers, 600 for expensive operations) and enforce a per-load timeout. An exception, timeout, or missing credentials returns an empty tool list rather than failing the run. Reads on the tool-loading path are fail-soft: if the Store backend is unreachable, the run continues without those tools, whereas dashboard status reads surface Store failures.

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: an unescaped angle bracket inside a label breaks rendering; rephrase the label. -->
```text
graph TD
  Trigger["Triggering user"] --> Scope["Credential scope known?"]
  Scope -->|yes, not local/summary| Load["Load MCPs"]
  Scope -->|no or local/summary| Skip["Skip optional tools"]
  Load --> Instance["Instance tier"]
  Load --> Workspace["Workspace tier"]
  Load --> User["User tier<br/>if known login"]
  Instance --> Discover["MCP discovery +<br/>tool cache"]
  Workspace --> Discover
  User --> Discover
  Discover --> Dynamic["DynamicToolMiddleware<br/>exposes names only"]
  Skip --> Server["LangGraph server"]
  Dynamic --> Server
  Discover --> MCP["MCP servers"]
  Server --> MCP
```

## Notion integration

Notion is a built-in, participant-scoped MCP integration backed by the hosted server at `https://mcp.notion.com/mcp` using per-user OAuth access tokens. Unlike the general MCP tiers, Notion tools are always participant-scoped: each tool invocation must include an `on_behalf_of` parameter naming the GitHub login of the person whose Notion connection to use.

### Notion OAuth and credential lifecycle

The `agent/dashboard/notion_oauth.py` module orchestrates discovery and exchange with Notion's OAuth authorization server. The agent stores one encrypted Notion record per user under `["user_credentials", <login>, "notion"]`, containing:

- **Encrypted access token** (`encrypted_access_token`): The current bearer token for the Notion MCP server.
- **Encrypted refresh token** (`encrypted_refresh_token`): A long-lived token to refresh the access token without re-authorization.
- **Token expiry** (`token_expires_at`, `refresh_token_expires_at`): ISO timestamps used to determine whether proactive refresh is needed.
- **OAuth flow metadata** (`client_id`, `token_endpoint`, `encrypted_client_secret`): Credentials to perform refresh operations.
- **Timestamps** (`updated_at`): When the record was last modified.

Token expiry is checked with a 300-second skew before a call to allow proactive refresh. If the access token is expired and a refresh token exists, `refresh_notion_access_token` is called under a per-login lock to avoid concurrent refresh races. If the refresh fails with a 401/403 (indicating the token is dead), the connection is dropped and a reconnect is required. If the access token is missing or non-refreshable, the tool call fails.

### Notion tool discovery and wrapping

`load_notion_tools(login)` loads only the private thread owner's Notion tools and only if they have a valid Notion connection. It uses that login's access token to call `_build_mcp_tools` once, discovering the MCP catalog. Every discovered tool is then wrapped in a `_RefreshingNotionMCPTool`, which adds a required `on_behalf_of` input parameter to every tool's schema. The wrapped tool is stateless: its schema is the same for all runs and all participants, reflecting the Notion MCP's catalog at discovery time, not a specific user's authorization.

At invocation, the wrapper:

1. Extracts the `on_behalf_of` parameter from the input.
2. Resolves the participant via `resolve_participant`, ensuring they match the triggering user and are a verified thread participant.
3. Fetches a fresh access token for that participant.
4. Rebuilds the MCP tool by calling `_build_mcp_tools` with the fresh token.
5. Invokes the tool.

If the participant is not found, the token is missing (no Notion connection), or the refresh fails, a `RuntimeError` is raised and the tool invocation fails. This design ensures tool invocations cannot use one person's Notion connection to act as another, and each call gets a current token even if previous calls expired it.

### Participant invariant

All uses of `on_behalf_of` are validated by `resolve_participant` in `agent/utils/thread_participants.py`. The parameter must be:

- Nonempty and case-insensitively match the GitHub login that triggered the current run.
- Among the verified participants of the thread (resolved by reading Slack, GitHub, and Linear message history).
- Uncertainty while verifying participants is rejected rather than silently accepted.

This invariant prevents the agent from using one person's credentials to act as a different, untrusted thread participant.

## Tool loading lifecycle and failures

While assembling a non-local, non-summary agent, the server concurrently loads:

- **MCP tools** from instance, workspace, and user tiers using `_mcp_tools_for`.
- **Notion tools** for the triggering login using `_notion_tools_for`, only if the run has a known credential scope.

Summary-stop and local/desktop runs skip optional tool loading. Both loaders are wrapped in a TTL cache and timeout, returning an empty list on failure. The server then registers each tool group with `DynamicToolMiddleware`, which defers the MCP handshake. The agent can call `load_integration_tools` to load a group by name and begin using its tools.

The operational invariant is that optional tool loss reduces available tools, not the ability to start or complete a run. If all MCPs are unavailable, the agent continues without them. If Notion is unavailable, the run has no Notion tools but is not blocked.

## Focused verification

Relevant tests cover MCP tool loading and caching in `tests/tools/test_mcp_sources.py` and `tests/tools/test_workspace_mcp_tools.py`, Notion wrapper refresh and participant validation in `tests/tools/test_notion_mcp_tools.py`, and concurrent factory loading in `tests/agent/test_factory_tool_loading.py`.
