# Files

- [Coding Agent Assembly and Execution](agent-graph.md) - How the primary Deep Agents coding graph is assembled per executable thread run, covering factory entry, configuration resolution, model routing, backend and skills assembly, tool curation, subagent configuration, and middleware ordering.
- [Middleware Stack and Failure Boundaries](middleware-stack.md) - Ordering-sensitive middleware, retry/timeout policies, permission guards, queues, fallbacks, and failure reporting in the agent graph. Covers run setup, tool visibility, flow control, observability, and state checkpointing in the coding agent and reviewer.
- [Runtime and Product Architecture](overview.md) - LangGraph deployment, graph entrypoints, FastAPI ingress, durable dispatch, sandbox ownership, and the dashboard and desktop product surfaces.
- [Reviewer Graph and Code Review](reviewer-and-analyzer.md) - Architecture of the isolated reviewer deep-agent graph, including repository preparation, durable finding reconciliation and publication, input safety, and differential code review.
- [Thread Sandbox Lifecycle](sandbox-lifecycle.md) - How a thread acquires, persists, reconnects to, and deliberately replaces its sandbox. Covers provider selection, proxy-backed credentials, recovery safety, and operational lifecycle controls.
