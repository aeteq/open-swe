# Files

- [Agent Graph & get_agent Factory](agent-graph.md) - How Open SWE compiles the main coding-agent graph for an executable thread run, including prompt preparation, thread-scoped resources, tool surfaces, subagents, and middleware ordering.
- [Middleware Stack](middleware-stack.md) - The ordered LangChain and Deep Agents middleware chain around Open SWE agent and reviewer model and tool calls, including failure boundaries, retries, and guardrails.
- [System Architecture Overview](overview.md) - High-level view of the five registered LangGraph graphs, the FastAPI app composition, durable dispatch, state ownership, and deployment targets.
- [Reviewer & Review-Style Analyzer Graphs](reviewer-and-analyzer.md) - How the read-only reviewer graph reviews one PR through a durable findings model and how the analyzer graph learns a per-repo review style in bootstrap and nightly continual modes.
- [Sandbox Lifecycle: Get-or-Create, Recovery, Proxy Management](sandbox-lifecycle.md)
