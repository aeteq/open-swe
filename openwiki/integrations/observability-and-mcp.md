---
type: integration reference
title: MCP and Tool Integrations
description: Optional Notion MCP and workspace MCP integrations for server-side tool provisioning, plus LangSmith LLM Gateway routing for model calls.
tags: [integrations, mcp, tools, langsmith, gateway, notion]
verified:
  - by: openwiki/0.4.2
    at: 2026-09-19T12:20:12.895Z
sources:
  - id: openwiki-source-b26707b64bee931c416620a7
    resource: repo://agent/dashboard/notion_oauth.py
  - id: openwiki-source-941341430e1d08d8e7e54dfe
    resource: repo://agent/dashboard/user_credentials.py
  - id: openwiki-source-856ade03ef31ac38e1347f7c
    resource: repo://agent/server.py
  - id: openwiki-source-2cd7e2018ae35c5972204803
    resource: repo://agent/tool_loaders/notion_mcp.py
  - id: openwiki-source-2d8602d5d52cd6ee177cde15
    resource: repo://agent/tool_loaders/workspace_mcp.py
  - id: openwiki-source-f0db445078d7a8158aa93724
    resource: repo://agent/utils/gateway.py
  - id: openwiki-source-56ade344fdbe7d47c84f008f
    resource: repo://agent/utils/model.py
  - id: openwiki-source-7c60191e42b8e30b62935af1
    resource: repo://agent/utils/thread_participants.py
generated: { by: "openwiki/0.4.2", at: "2026-09-19T12:20:12.895Z" }
---

# MCP and Tool Integrations

The agent supports several optional external integrations: workspace and user MCP sources that provision custom tools through the server process, per-user Notion MCP with participant-scoped access control, and optional model routing through the LangSmith LLM Gateway.

See [Authentication and security](../concepts/auth-and-security.md) for the broader trust model, [Tools](../concepts/tools.md) for dynamic tool availability, and [Configuration](../operations/configuration.md) for environment settings.

## MCP Tool Loading

The agent loads tools from three MCP tiers in sequence: instance (configured at the deployment level), workspace, and user. When a tool exists in multiple tiers, the user-scoped version takes precedence. All sources use the `streamable_http` transport to the configured MCP server URLs.

MCP tools load only for non-local, non-summary runs where credential scope is known, using a stale-while-revalidate TTL cache scoped to login and workspace. MCP discovery and tool building happen together with Notion tools during the parallel factory phase. A timeout or exception returns an empty tool list rather than failing the run, so unavailable MCPs gracefully degrade to only the core agent tools.

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: an unescaped angle bracket inside a label breaks rendering; rephrase the label. -->
```text
flowchart TD
  Factory["Factory phase<br/>for agent creation"]
  Parallel["Parallel loaders"]
  MCPTiers["MCP tier resolution:<br/>instance → workspace → user"]
  NotionLoad["Notion MCP discovery<br/>and wrapping"]
  Register["Register in<br/>DynamicToolMiddleware"]
  
  Factory --> Parallel
  Parallel -->|300s TTL cache| MCPTiers
  Parallel -->|300s TTL cache| NotionLoad
  MCPTiers --> Register
  NotionLoad --> Register
```

## Notion MCP Integration

Notion tools are backed by the hosted server at `https://mcp.notion.com/mcp` using per-user OAuth access tokens. The loader runs `load_notion_tools(login)`, which discovers the Notion MCP catalog once per login and per 300-second cache window.

Each tool is wrapped so its input schema includes a required `on_behalf_of` GitHub login. At call time, the wrapper validates that the named participant matches the triggering user and is a verified thread participant, then:

1. Resolves a fresh access token for that participant
2. Reconnects to Notion MCP with that token
3. Builds the requested tool with the fresh connection
4. Invokes it

If the participant has no current Notion token, the tool raises an error directing them to reconnect Notion in Profile Settings. If a token refresh fails with a reauth-required error, the stored connection is removed, again triggering a reconnection prompt.

Thus a catalog loaded with one person's token does not authorize calls as that person; every invocation sources fresh, participant-specific credentials. Notion tools load only when a known, logged-in user is available.

### Participant Invariant

`resolve_participant` enforces that `on_behalf_of` matches the user who triggered the run and is a verified thread participant. Calls cannot select a different participant's connection, and any uncertainty during participant verification is rejected rather than silently accepted.

## LangSmith LLM Gateway

The LLM Gateway is an optional model-routing layer, separate from the LangSmith run-inspection utilities. It proxies supported provider calls through LangSmith, which authenticates with a gateway API key and resolves real provider secrets from workspace Provider Secrets while enforcing spend, PII, and secrets policies and tracing every call.

Gateway routing is applied centrally in `make_model` and is opt-in via configuration. A team `gateway_enabled` workspace setting overrides the deployment default; when unset, `LANGSMITH_GATEWAY_ENABLED` decides, or merely setting a dedicated `LANGSMITH_GATEWAY_API_KEY` enables routing by default.

Only `openai`, `anthropic`, `baseten`, `fireworks`, and `google_genai` model prefixes have gateway paths. Unsupported providers or a missing LangSmith API key log a warning and continue with direct provider routing instead of failing model construction. Gateway-routed OpenAI retains the Responses API by default; set `LANGSMITH_GATEWAY_OPENAI_USE_RESPONSES=false` only when a deployment needs Chat Completions.

The gateway-specific key (`LANGSMITH_GATEWAY_API_KEY`) is preferred over the standard LangSmith API key when both are available, since the injected `LANGSMITH_API_KEY` may lack the `gateway:invoke` permission.

## Tool Loading Lifecycle and Failures

While building an executable non-local, non-summary agent, the server concurrently loads MCP and Notion tool groups in the factory phase. Both use a stale-while-revalidate TTL cache with a shared per-run loader timeout. An exception or timeout returns an empty list. Credential reads on the tool-loading path also deliberately fail soft when Store access fails, whereas dashboard status reads surface Store failures. The operational invariant is that optional integration loss reduces available tools, not the ability to start a run.

Loaded tools are registered in a `DynamicToolMiddleware` instance, so they arrive as optional groups alongside the static core tools. Summary-stop and local/desktop runs skip integration tool loading entirely.
