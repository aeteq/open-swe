# Files

- [Context Engineering and Prompt Assembly](context-engineering.md) - Dynamic system prompt construction, context window strategy, skill routing, and instruction precedence in coded agent execution.
- [Follow-up Messages and Threaded Continuity](follow-up-messages.md) - Thread message routing, follow-up invocation from GitHub PR comments and Slack replies, run continuation and interruption coordination, and completion webhooks that coordinate concurrent work without losing user input.
- [Inbound Invocation to Durable Run](invocation.md) - How GitHub, Slack, Linear, dashboard, desktop, and scheduled automation inputs are admitted, attributed, routed to a thread, dispatched as durable LangGraph runs, and handled at completion.
- [Pull Request Creation and Updates](pr-creation.md) - How the agent opens and updates pull requests with attributed authorship, commit squashing, workflow-file change approval, and metadata recording.
- [Pull Request Review Workflow](pr-review.md) - How Open SWE starts GitHub pull-request reviews, prepares a diff-grounded reviewer run, persists and publishes findings, and reconciles replies, resolutions, and review checks across later pushes.
- [Scheduled and Background Work Dispatch](scheduling-and-baby-sit.md) - How the job queue routes cron and delayed work into durable automations, cost refreshes, background-task monitoring, CI watches, and thread wakeups without any LLM involvement.
