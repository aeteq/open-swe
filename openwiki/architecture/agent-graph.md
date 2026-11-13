---
type: architecture
title: Coding Agent Assembly and Execution
description: How the primary Deep Agents coding graph is assembled per executable thread run, covering factory entry, configuration resolution, model routing, backend and skills assembly, tool curation, subagent configuration, and middleware ordering.
tags: [agent-graph, deep-agents, langgraph, middleware, subagents, sandbox, tools, factory, managed-deep-agents]
verified:
  - by: openwiki/0.4.2
    at: 2026-11-11T15:58:52.285Z
sources:
  - id: openwiki-source-5bbba7b2a8ea8360ff233d63
    resource: repo://langgraph.json
  - id: openwiki-source-0190f218684562b378eff2f1
    resource: repo://openswe/agent_api/agent.py
  - id: openwiki-source-813c25f6bac2408de322a1f5
    resource: repo://openswe/graphs/agent.py
  - id: openwiki-source-75a672d9a8b6d6c500b1cf8d
    resource: repo://openswe/middleware/dynamic_tools.py
  - id: openwiki-source-052a9a68c52dca5bb8277219
    resource: repo://openswe/middleware/prepare_run.py
  - id: openwiki-source-c950a10d3272291deaffd090
    resource: repo://openswe/prompt.py
  - id: openwiki-source-e9b2ac0cf383e184a317d349
    resource: repo://openswe/run_config.py
  - id: openwiki-source-1b32e9f41fa7e64702b380f6
    resource: repo://openswe/sandboxes/lifecycle.py
  - id: openwiki-source-919e16feae379651f2cbc1c9
    resource: repo://openswe/server.py
  - id: openwiki-source-659ef274df23f55f0ecc0366
    resource: repo://openswe/skill_store/run_skills.py
generated: { by: "openwiki/0.4.2", at: "2026-11-06T15:47:54.369Z" }
---

# Coding Agent Assembly and Execution

Open SWE's coding agent runs on Managed Deep Agents (MDA), a remote LangGraph service. The server calls `agent_catalog(config, surface)` to prepare and configure the graph before MDA executes it. This factory function is the customization seam for sandbox providers, model policy, tool surfaces, skills routes, subagents, and middleware. All per-thread state lives in the sandbox and thread metadata; the agent graph itself is stateless and rebuilt per thread.

## Entry and execution gate

The factory function `agent_catalog` receives a `RunnableConfig` carrying thread metadata and launch context in its `configurable` dict. It gates full assembly on the presence of a non-null `thread_id` within `RunConfig`, indicating an executable thread run. The function populates a `ToolSurface` object that MDA uses to configure the model loop, tools, middleware, models, and subagents.

`RunConfig` is the tolerant configuration contract: all declared fields are optional, unknown keys survive round trips, and parsing drops only invalid fields rather than losing an otherwise usable run configuration. This flexibility matters because different launchers and graph types add distinct keys.

## Per-run context and sandbox backend

`profile_login` is the person who triggered the run; it controls authorization and credentialed integrations. In contrast, model choices and repository instructions are stored in thread settings—initially seeded from a profile but then retained by the thread—so a later participant does not silently replace durable decisions.

The factory creates a cached `SandboxBackendProxy` and starts its reconnect task immediately, before resolving the rest of the graph. For bridged desktop runs, the sandbox connection is to the user's own machine via `BridgeSandboxBackend`; for hosted runs, the reconnect callback calls `ensure_sandbox_for_thread` with the workspace slug, which resolves the sandbox environment from thread metadata, refreshes proxy credentials, or creates and binds a new sandbox. The lifecycle deliberately raises for an unreachable existing sandbox rather than replacing potentially uncommitted work; a deleted sandbox is replaced because retaining its stale id would permanently block the thread.

## Model and effort routing

Main-agent and subagent model/effort pairs resolve by precedence:

1. **Team defaults** from workspace settings (default_agent_model, default_agent_subagent_model).
2. **Profile overrides** from the dashboard, with separate subagent override when provided.
3. **Stored thread settings** (persisted after each run and refreshed across participants).
4. **Per-run agent_model_id and agent_effort**, only if both are canonical `SUPPORTED_MODEL_IDS` and pass `model_supports_effort` validation.
5. **Image model override** when the primary model lacks image support and image input is detected.

Resolved pairs are persisted to thread settings before Fable gating, so a deployment-wide enablement decision applies on every run rather than freezing into thread settings. Provider-specific keyword arguments are computed separately for main, subagent, and title models. Construction failures defer to an error model, allowing the graph to compile and reporting provider setup failure at model-call time. A fallback middleware is installed only if its model id differs from the primary model.

Desktop runs skip thread-settings lookup and use workspace defaults directly; Slack `/oswe` questions use the triggering user's default model and disable adaptive routing.

**Adaptive model routing** enables when the workspace enables it, the thread has not completed a handoff, the source is dashboard or Slack, and the run is not an incident sweep, background task, or continuation. When adaptive routing is active, the graph populates `requested_models` with available model options and installs `ModelSelectionMiddleware` to gate dynamic model selection during the run. Image-unsupported models trigger automatic fallback to a dedicated vision model.

## System prompt and preparation

The factory supplies `ToolSurface` with a list of middleware that includes `PrepareAgentRunMiddleware`, which renders the per-thread prompt dynamically in its `abefore_agent` hook.

`construct_system_prompt` builds the main-agent system prompt in a fixed order: working environment (local-specific or sandbox-standard), dashboard/source context, source-guidance section, default-prompt foundation, optional repository scope, collaboration and co-author guidance, external-comment warnings, commit/PR guidance, repository instructions, workspace instructions, and recent-thread context. Sender identity, attribution, standing user instructions, and participant context are intentionally excluded from this durable system prompt to avoid rewriting cached history.

For hosted runs, preparation resolves the GitHub token, sandbox work directory, sender identity, instruction context, and thread participants. It adds the resulting sender context as a separate generated message after a human input, allowing the model to distinguish between user input and infrastructure context. A sandbox-unreachable failure posts a user-facing notification before being re-raised.

Preparation is checkpointed: `run_prepared_for` fingerprints the middleware class, latest message, and configuration. A resumed attempt with the same fingerprint skips setup, while a later invocation re-prepares fresh tokens, prompts, and context. Preparation implementations must be idempotent because failure before checkpoint persistence permits a retry.

## Backend and skills

The primary backend is a `CompositeBackend` whose default route is the sandbox proxy. It overlays read-only skill routes:

- **Bundled skills** (`/bundled-skills/`) come from `FilesystemBackend(BUNDLED_SKILLS_DIR)`.
- **Hosted organization skills** (`/organization-skills/`) come from a `StoreBackend` namespaced in the LangGraph store scoped to the workspace.
- **Hosted user skills** (`/skills/`) come from a `StoreBackend` namespaced to `credential_login` when one exists, providing access to private personal integrations.
- **Blobs** (`/blobs/`) on hosted runs use a `StoreBackend` routed to PostgreSQL (`ThreadBlobs`) so offloaded images can be read without sandbox access.

The ordered `skill_sources` list is supplied to both the parent agent and the general-purpose subagent, ensuring consistent skill availability across delegation. For hosted runs with personal integrations, user skills are checked first, then organization skills, then bundled skills; for runs without credential access, organization and bundled skills are available.

## Curated and dynamic tools

The parent static tool list is curated by context:

- **Slack tools** (manage_code_channel, slack_reply, etc.) require trusted Slack source context (a channel and thread timestamp) or schedule source.
- **Admin tools** (list_automations, publish_workspace, etc.) require the triggering sender to have workspace-admin access.
- **Sandbox download/service tools** (output_iframe, create_sandbox_file_download_url, expose_port) require LangSmith sandbox provider and are omitted for desktop and stop-summary runs.
- **Desktop runs** are restricted to http_request, fetch_url, and web_search.
- **Stop-summary runs** are restricted to slack_read_thread_messages and slack_reply.
- **Client-owned tools** replace server-side tools of the same name; their names are excluded from the server's tool surface.

`ExcludeToolsMiddleware` applies exclusions:

- In normal runs, it removes Deep Agents' `grep` tool (filesystem search).
- In stop-summary mode, it also removes mutating filesystem and delegation tools (delete, edit_file, execute, task, write_file).
- In `/oswe` question mode, it removes thread-specific tools that require a Slack thread_ts.

Integration tools (MCP/Corridor tools, Notion tools) are exposed through `DynamicToolMiddleware`, not appended directly to the static list. MCP tools are eagerly loaded during factory assembly with names available immediately (loader failures yield no tools). Tool schemas are loaded on demand after `load_integration_tools` is called. The middleware resets selected integration tools at run start, prevents tool calls before selection, serializes each group's construction, converts failures into unavailable-tool results, and reserves static and Deep Agent names to reject collisions.

## Deep Agents subagent configuration

The only configured subagent is the general-purpose Deep Agents subagent. It receives:

- **Model**: The subagent model and effort pair, constructed independently of the parent.
- **Tools**: Static tools filtered to exclude `save_user_settings` and parent-only tools (background_execute, Slack-specific tools except those usable from subagents, infrastructure tools, etc.).
- **Skills**: The same ordered skill_sources as the parent.
- **Middleware**: MDA compiles subagent middleware independently:
  - AnthropicPromptCachingMiddleware for prompt caching.
  - TranscriptMiddleware for call logging.
  - ExcludeToolsMiddleware filtering shell/search tools.
  - Dynamic-tool middleware if parent has integration tools.
  - Guard middleware (PullRequestCreationGuardMiddleware for hosted runs, none for desktop).
  - ConversationOffloadingMiddleware for history summarization.
  - Model guards: SanitizeOpenAIResponsesMiddleware, ModelErrorMiddleware, ModelCallTimeoutMiddleware.

The subagent's `mode` is `fork`, meaning it branches and collects results back into the parent message thread. Its description includes a suffix requiring Slack communication to be relayed through the parent.

## Middleware assembly and ordering

The parent middleware list is ordered outermost to innermost, making order part of the runtime contract. MDA runs the middleware provided by `ToolSurface.middleware` in sequence around the model loop, and timeouts must be innermost so fallback escalation works correctly.

**Layer 1: Outermost context and offloading**
- AnthropicPromptCachingMiddleware (request caching for cost optimization)
- ConversationOffloadingMiddleware (summarization and history eviction)
- PrepareAgentRunMiddleware (sender identity, context, prompt rendering, per-run setup)
- ReviewGuideMiddleware (optional, walkthrough guidance if present)

**Layer 2: Run management and tool mediation**
- TranscriptMiddleware (call logging)
- ClientToolsMiddleware (optional, client-side tool overrides)
- IncidentMiddleware (optional, incident-specific session context)
- ModelCallLimitMiddleware (enforce recursion limit, end run at MODEL_CALL_RECURSION_LIMIT)
- ExcludeToolsMiddleware (filter unavailable or restricted tools)
- TaskCoordinationMiddleware (optional, worker coordination state)
- RefreshGitHubProxyMiddleware (refresh GitHub token before model calls)
- MessageQueueCheckMiddleware, DeliverEventMatchesMiddleware (skip in stop-summary mode)

**Layer 3: Flow control and guards**
- RequireUserReplyMiddleware (Slack reply required unless tool offered)
- RequireCliResultMiddleware (optional, CLI bridge mode requires result proof)
- NotifyStepLimitMiddleware (notify when approaching step limit)
- RecordRunUsageMiddleware (log telemetry and usage)
- ModelSelectionMiddleware (optional, adaptive model routing)
- ModelFallbackMiddleware (fallback model on primary timeout/failure)
- ImageModelFallbackMiddleware (optional, vision fallback for text-only models)

**Layer 4: Innermost provider and model safety**
- DynamicToolMiddleware (optional, integration tools)
- SanitizeFireworksMessagesMiddleware (Fireworks response cleanup)
- SanitizeOpenAIResponsesMiddleware (OpenAI response cleanup)
- SanitizeThinkingBlocksMiddleware (thinking block removal)
- StableToolResultOrderMiddleware (deterministic tool-result ordering)
- ModelErrorMiddleware (handle model call errors)
- ModelCallTimeoutMiddleware (innermost: deadline covers provider call, escalates to fallback)

The innermost timeout measures the actual provider call and can escalate outward to the fallback model. The call limit ends the run at `MODEL_CALL_RECURSION_LIMIT`; task retry sits inside ToolErrorMiddleware.

## Execution flow on Managed Deep Agents

```mermaid
sequenceDiagram
    participant Client
    participant Server
    participant MDA as Managed Deep Agents
    participant Model as LLM Model
    participant Sandbox as SandboxBackend

    Client->>Server: POST /runs (with config)
    Server->>Server: agent_catalog(config, surface)
    
    Server->>Server: Resolve models, tools, middleware
    Server->>Server: Assemble subagent config
    Server->>Server: Build skills backend
    
    Server->>MDA: Create run with configured surface
    activate MDA
    
    MDA->>MDA: Load catalog, prepare tools
    MDA->>MDA: before_agent hooks (PrepareAgentRunMiddleware)
    MDA->>MDA: Render system prompt
    
    loop Until completion
        MDA->>MDA: before_model hooks
        MDA->>MDA: ModelSelectionMiddleware: route or use main model
        MDA->>MDA: ModelCallTimeoutMiddleware: set deadline
        
        MDA->>Model: awrap_model_call(request)
        activate Model
        Model-->>MDA: response
        deactivate Model
        
        MDA->>MDA: after_model hooks
        
        alt Tool call in response
            MDA->>MDA: Parse tool requests
            MDA->>MDA: DynamicToolMiddleware: ensure tool loaded
            MDA->>Sandbox: Execute tool
            Sandbox-->>MDA: tool result
            MDA->>MDA: Store result in messages
        else No tool call
            MDA->>MDA: End loop, return response
        end
    end
    
    deactivate MDA
    MDA-->>Server: Run complete
    Server-->>Client: Response with artifacts
```

The server-side factory work (resolving models, storing settings, loading MCPs) overlaps aggressively to minimize latency. The model loop is stateless—each turn rebuilds the middleware stack identically, so any middleware state that must survive a turn lives in the message thread or checkpointed in LangGraph's store.
