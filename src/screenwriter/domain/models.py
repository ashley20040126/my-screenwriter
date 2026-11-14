from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class WorkflowStatus(StrEnum):
    DRAFT = "DRAFT"
    GENERATING = "GENERATING"
    REVIEWING = "REVIEWING"
    WAITING_HUMAN_REVIEW = "WAITING_HUMAN_REVIEW"
    HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"
    FINAL = "FINAL"
    FAILED = "FAILED"


class Severity(StrEnum):
    S = "S"
    A = "A"
    B = "B"


class CommentStatus(StrEnum):
    OPEN = "OPEN"
    CONSUMED = "CONSUMED"
    RESOLVED = "RESOLVED"


@dataclass(slots=True)
class ProjectConfig:
    market: str = "欧美"
    episode_count: int = 60
    episode_duration_seconds: int = 120
    first_paywall_episode: int = 10
    budget_level: str = "中等"
    max_iteration_budget: int | None = None


@dataclass(slots=True)
class Project:
    id: str
    title: str
    idea: str
    config: ProjectConfig
    status: WorkflowStatus = WorkflowStatus.DRAFT
    iteration: int = 0
    current_version_id: str | None = None
    human_review_token: str | None = None
    last_error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class EpisodeDraft:
    episode: int
    title: str
    screenplay: str
    ending_hook: str


@dataclass(slots=True)
class ScriptDraft:
    title: str
    logline: str
    story_bible: dict[str, Any]
    character_bible: list[dict[str, Any]]
    episodes: list[EpisodeDraft]


@dataclass(slots=True)
class ReviewFinding:
    reviewer: str
    severity: Severity
    episode_refs: list[int]
    evidence: str
    judgment: str
    audience_risk: str


@dataclass(slots=True)
class ReviewReport:
    reviewer: str
    score: float
    findings: list[ReviewFinding]


@dataclass(slots=True)
class StoryVersion:
    id: str
    project_id: str
    version_number: int
    iteration: int
    parent_version_id: str | None
    creative_brief: dict[str, Any]
    script: ScriptDraft
    reviews: list[ReviewReport]
    verification: ReviewReport
    revision_brief: dict[str, Any] | None
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class HumanComment:
    id: str
    project_id: str
    version_id: str
    episode_id: int
    body: str
    anchor: str | None = None
    author_id: str = "human"
    status: CommentStatus = CommentStatus.OPEN
    created_at: str = field(default_factory=utc_now)


def to_dict(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value
