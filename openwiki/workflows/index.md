# Files

- [Prompt and Context Assembly](context-engineering.md) - How input messages, source context, and prompts are built deterministically from events, assembled into model inputs, and prepared with proper instruction precedence.
- [Follow-ups, Interrupts, and Stop Control](follow-up-messages.md) - How Open SWE attaches new work to an existing thread, chooses durable run interruption or enqueueing, preserves checkpoint and sandbox context, and implements Slack and dashboard stop behavior.
- [Inbound Invocation to Durable Run](invocation.md) - How GitHub, Slack, Linear, dashboard, desktop, and scheduled automation inputs are admitted, attributed, routed to a thread, dispatched as durable LangGraph runs, and handled at completion.
- [Pull Request Opening and Iteration](pr-creation.md) - How an agent delivers code through GitHub branches and pull requests, including attributed creation, branch/commit handling, PR metadata and body construction, draft vs. ready state, thread resolution, workflow-change approval, and follow-up updates to open PRs.
- [Pull Request Review Workflow](pr-review.md) - How Open SWE starts GitHub pull-request reviews, prepares a diff-grounded reviewer run, persists and publishes findings, and reconciles replies, resolutions, and review checks across later pushes.
- [Scheduling, Background Work, and CI Monitoring](scheduling-and-baby-sit.md) - How the model-free scheduler routes cron and delayed work into recurring automations, reconciliation, cost refreshes, background-task monitoring, and opt-in pull-request CI recovery.
