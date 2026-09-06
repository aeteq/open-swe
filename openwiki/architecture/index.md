# Files

- [Agent Graph & get_agent Factory](agent-graph.md) - How Open SWE compiles the main coding-agent graph for an executable thread run, including prompt preparation, thread-scoped resources, tool surfaces, subagents, and middleware ordering.
- [Middleware Stack & Safety Layers](middleware-stack.md) - Ordered middleware composition around model and tool calls, including failure recovery, user notifications, guardrails, and timeout protection.
- [System Architecture Overview](overview.md) - High-level map of the five LangGraph entrypoints, FastAPI routes, durable dispatch contract, and how sandbox and thread state flow through the runtime.
- [Reviewer & Review-Style Analyzer Graphs](reviewer-and-analyzer.md) - How the read-only reviewer graph reviews one PR through a durable findings model and how the analyzer graph learns a per-repo review style in bootstrap and nightly continual modes.
- [Sandbox Lifecycle & Providers](sandbox-lifecycle.md) - How each thread is bound to a per-thread sandbox through a get-or-create-then-reconnect lifecycle, how the SANDBOX_TYPE provider is selected, how the LangSmith GitHub proxy is configured, and how unreachable versus deleted sandboxes are handled.
