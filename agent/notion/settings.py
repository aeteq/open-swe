"""Notion task integration settings, read from the environment on every call."""

from dataclasses import dataclass

from agent.config import ENV


def normalize_notion_id(value: str) -> str:
    """Notion ids appear both dashed and undashed; compare them undashed."""
    return value.replace("-", "").strip().lower()


def _id_set(raw: str) -> frozenset[str]:
    return frozenset(normalize_notion_id(part) for part in raw.split(",") if part.strip())


def _name_set(raw: str) -> frozenset[str]:
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class NotionSettings:
    api_key: str
    webhook_secret: str
    agent_user_ids: frozenset[str]
    task_data_source_ids: frozenset[str]
    documents_data_source_id: str
    assignee_property: str
    repo_property: str
    status_property: str
    pr_property: str
    startable_statuses: frozenset[str]
    status_in_progress: str
    status_in_review: str
    design_property: str
    design_status_property: str
    design_approved_status: str

    def is_agent_user(self, user_id: str) -> bool:
        return normalize_notion_id(user_id) in self.agent_user_ids

    def is_task_data_source(self, data_source_id: str | None) -> bool:
        return bool(data_source_id) and (
            normalize_notion_id(data_source_id or "") in self.task_data_source_ids
        )

    def is_documents_data_source(self, data_source_id: str | None) -> bool:
        return bool(data_source_id and self.documents_data_source_id) and (
            normalize_notion_id(data_source_id or "") == self.documents_data_source_id
        )


def notion_settings() -> NotionSettings:
    return NotionSettings(
        api_key=ENV.NOTION_API_KEY.get(),
        webhook_secret=ENV.NOTION_WEBHOOK_SECRET.get(),
        agent_user_ids=_id_set(ENV.NOTION_AGENT_USER_IDS.get()),
        task_data_source_ids=_id_set(ENV.NOTION_TASKS_DATA_SOURCE_ID.get()),
        documents_data_source_id=normalize_notion_id(ENV.NOTION_DOCUMENTS_DATA_SOURCE_ID.get()),
        assignee_property=ENV.NOTION_ASSIGNEE_PROPERTY.get(),
        repo_property=ENV.NOTION_REPO_PROPERTY.get(),
        status_property=ENV.NOTION_STATUS_PROPERTY.get(),
        pr_property=ENV.NOTION_PR_PROPERTY.get(),
        startable_statuses=_name_set(ENV.NOTION_STARTABLE_STATUSES.get()),
        status_in_progress=ENV.NOTION_STATUS_IN_PROGRESS.get(),
        status_in_review=ENV.NOTION_STATUS_IN_REVIEW.get(),
        design_property=ENV.NOTION_DESIGN_PROPERTY.get(),
        design_status_property=ENV.NOTION_DESIGN_STATUS_PROPERTY.get(),
        design_approved_status=ENV.NOTION_DESIGN_APPROVED_STATUS.get(),
    )
