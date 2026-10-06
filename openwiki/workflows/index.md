# Files

- [Context and Prompt Engineering](context-engineering.md) - Workflow for assembling run input, managing dynamic context deduplication, and constructing layered system prompts from multiple instruction sources.
- [Follow-up Messages and Polling](follow-up-messages.md) - Deferred message handling, store-backed message queues, and follow-up pickup between runs. Explains how the before-model middleware injects queued messages into active runs and how background systems dispatch follow-ups after terminal conditions.
- [Inbound Invocation to Durable Run](invocation.md) - How GitHub, Slack, Linear, dashboard, desktop, and scheduled automation inputs are admitted, attributed, routed to a thread, dispatched as durable LangGraph runs, and handled at completion.
- [Pull Request Delivery and Approval](pr-creation.md) - How an agent delivers code through GitHub branches and pull requests, including attributed creation, workflow-change approval, status visibility, CI handling, and review handoff.
- [Pull Request Review Workflow](pr-review.md) - How Open SWE starts GitHub pull-request reviews, prepares a diff-grounded reviewer run, persists and publishes findings, and reconciles replies, resolutions, and review checks across later pushes.
- [Scheduling, Background Work, and CI Monitoring](scheduling-and-baby-sit.md) - How the model-free scheduler routes cron and delayed work into recurring automations, reconciliation, cost refreshes, background-task monitoring, and opt-in pull-request CI recovery.
