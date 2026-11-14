from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from screenwriter.domain.models import (
    CommentStatus,
    EpisodeDraft,
    HumanComment,
    Project,
    ProjectConfig,
    ReviewFinding,
    ReviewReport,
    ScriptDraft,
    Severity,
    StoryVersion,
    WorkflowStatus,
    to_dict,
)


class NotFoundError(KeyError):
    pass


class SqliteProjectRepository:
    def __init__(self, database_path: str) -> None:
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS versions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(project_id, version_number)
                );
                CREATE TABLE IF NOT EXISTS comments (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )

    def create_project(self, project: Project) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO projects (id, payload) VALUES (?, ?)",
                (project.id, json.dumps(to_dict(project), ensure_ascii=False)),
            )

    def get_project(self, project_id: str) -> Project:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(project_id)
        return self._project_from_dict(json.loads(row["payload"]))

    def list_projects(self) -> list[Project]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM projects ORDER BY json_extract(payload, '$.updated_at') DESC"
            ).fetchall()
        return [self._project_from_dict(json.loads(row["payload"])) for row in rows]

    def save_project(self, project: Project) -> None:
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE projects SET payload = ? WHERE id = ?",
                (json.dumps(to_dict(project), ensure_ascii=False), project.id),
            )
            if result.rowcount != 1:
                raise NotFoundError(project.id)

    def claim_review_token(self, project_id: str, review_token: str) -> Project:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(project_id)
            project = self._project_from_dict(json.loads(row["payload"]))
            if project.status not in {
                WorkflowStatus.WAITING_HUMAN_REVIEW,
                WorkflowStatus.HUMAN_DECISION_REQUIRED,
            }:
                raise RuntimeError("Project is not waiting for human review")
            if project.human_review_token != review_token:
                raise RuntimeError("Review token is invalid or already consumed")
            project.status = WorkflowStatus.GENERATING
            project.human_review_token = None
            connection.execute(
                "UPDATE projects SET payload = ? WHERE id = ?",
                (json.dumps(to_dict(project), ensure_ascii=False), project.id),
            )
        return project

    def add_version(self, version: StoryVersion) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO versions (id, project_id, version_number, payload) VALUES (?, ?, ?, ?)",
                (
                    version.id,
                    version.project_id,
                    version.version_number,
                    json.dumps(to_dict(version), ensure_ascii=False),
                ),
            )

    def get_version(self, version_id: str) -> StoryVersion:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM versions WHERE id = ?", (version_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(version_id)
        return self._version_from_dict(json.loads(row["payload"]))

    def list_versions(self, project_id: str) -> list[StoryVersion]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM versions WHERE project_id = ? ORDER BY version_number",
                (project_id,),
            ).fetchall()
        return [self._version_from_dict(json.loads(row["payload"])) for row in rows]

    def add_comment(self, comment: HumanComment) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO comments (id, project_id, version_id, status, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    comment.id,
                    comment.project_id,
                    comment.version_id,
                    comment.status.value,
                    json.dumps(to_dict(comment), ensure_ascii=False),
                ),
            )

    def list_open_comments(self, project_id: str, version_id: str) -> list[HumanComment]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM comments WHERE project_id = ? AND version_id = ? "
                "AND status = ? ORDER BY rowid",
                (project_id, version_id, CommentStatus.OPEN.value),
            ).fetchall()
        return [self._comment_from_dict(json.loads(row["payload"])) for row in rows]

    def mark_comments_consumed(self, comment_ids: list[str]) -> None:
        if not comment_ids:
            return
        with self._connect() as connection:
            for comment_id in comment_ids:
                row = connection.execute(
                    "SELECT payload FROM comments WHERE id = ?", (comment_id,)
                ).fetchone()
                if row is None:
                    continue
                comment = self._comment_from_dict(json.loads(row["payload"]))
                comment.status = CommentStatus.CONSUMED
                connection.execute(
                    "UPDATE comments SET status = ?, payload = ? WHERE id = ?",
                    (
                        comment.status.value,
                        json.dumps(to_dict(comment), ensure_ascii=False),
                        comment_id,
                    ),
                )

    @staticmethod
    def _project_from_dict(data: dict) -> Project:
        data["config"] = ProjectConfig(**data["config"])
        data["status"] = WorkflowStatus(data["status"])
        return Project(**data)

    @staticmethod
    def _review_from_dict(data: dict) -> ReviewReport:
        findings = [
            ReviewFinding(
                reviewer=item["reviewer"],
                severity=Severity(item["severity"]),
                episode_refs=item["episode_refs"],
                evidence=item["evidence"],
                judgment=item["judgment"],
                audience_risk=item["audience_risk"],
            )
            for item in data["findings"]
        ]
        return ReviewReport(reviewer=data["reviewer"], score=data["score"], findings=findings)

    @classmethod
    def _version_from_dict(cls, data: dict) -> StoryVersion:
        script_data = data["script"]
        script = ScriptDraft(
            title=script_data["title"],
            logline=script_data["logline"],
            story_bible=script_data["story_bible"],
            character_bible=script_data["character_bible"],
            episodes=[EpisodeDraft(**item) for item in script_data["episodes"]],
        )
        return StoryVersion(
            id=data["id"],
            project_id=data["project_id"],
            version_number=data["version_number"],
            iteration=data["iteration"],
            parent_version_id=data["parent_version_id"],
            creative_brief=data["creative_brief"],
            script=script,
            reviews=[cls._review_from_dict(item) for item in data["reviews"]],
            verification=cls._review_from_dict(data["verification"]),
            revision_brief=data["revision_brief"],
            created_at=data["created_at"],
        )

    @staticmethod
    def _comment_from_dict(data: dict) -> HumanComment:
        data["status"] = CommentStatus(data["status"])
        return HumanComment(**data)
