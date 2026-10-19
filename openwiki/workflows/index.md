# Files

- [Context and Prompt Engineering](context-engineering.md) - Workflow for assembling run input, managing dynamic context deduplication, and constructing layered system prompts from multiple instruction sources and sandbox configurations.
- [Follow-up Messages and Interruption](follow-up-messages.md) - Message queues for live handoffs, multitask strategies for follow-up dispatch, run completion webhooks, and emergency stop mechanics that coordinate concurrent work without losing user input.
- [Invocation: From Trigger to Durable Run](invocation.md)
- [Pull Request Creation and Workflow Approval](pr-creation.md) - How the agent creates and manages pull requests with attributed authorship, commits squashing, workflow-file change approval, and metadata recording.
- [Pull Request Review Workflow](pr-review.md) - How Open SWE starts GitHub pull-request reviews, prepares a diff-grounded reviewer run, persists and publishes findings, and reconciles replies, resolutions, and review checks across later pushes.
- [Scheduling, Background Work, and CI Monitoring](scheduling-and-baby-sit.md) - How the job queue and background handlers route cron and delayed work into recurring automations, reconciliation, cost refreshes, background-task monitoring, and opt-in pull-request CI recovery.
