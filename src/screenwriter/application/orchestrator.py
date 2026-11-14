from __future__ import annotations

import asyncio
from uuid import uuid4

from screenwriter.domain.models import (
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
    utc_now,
)
from screenwriter.domain.ports import LLMProvider, NotificationPort, ProjectRepository

from .prompts import (
    creative_brief_task,
    editor_task,
    reviewer_task,
    verification_task,
    writer_task,
)

REVIEWERS = {
    "Structure & Conflict Reviewer": "故事骨架、六要素闭环、核心事件和冲突质量",
    "Character Reviewer": "人物一致性、人物功能、欲望与行动逻辑",
    "Retention & Monetization Reviewer": "开场、前三集、集尾钩子、付费期待和爽点",
    "Continuity & Setup-Payoff Reviewer": "连续性、伏笔、铺垫回收和信息一致性",
    "Production Feasibility Reviewer": "可演、可拍、场景成本和视觉呈现",
}


class WorkflowConflict(RuntimeError):
    pass


class ScreenwriterService:
    def __init__(
        self,
        repository: ProjectRepository,
        llm: LLMProvider,
        notifications: NotificationPort,
        review_base_url: str = "http://localhost:8000",
    ) -> None:
        self.repository = repository
        self.llm = llm
        self.notifications = notifications
        self.review_base_url = review_base_url.rstrip("/")

    def create_project(self, title: str, idea: str, config: ProjectConfig | None = None) -> Project:
        project = Project(id=str(uuid4()), title=title, idea=idea, config=config or ProjectConfig())
        self.repository.create_project(project)
        return project

    async def generate_initial(self, project_id: str) -> StoryVersion:
        project = self.repository.get_project(project_id)
        if project.status != WorkflowStatus.DRAFT:
            raise WorkflowConflict("Initial generation is only allowed from DRAFT")
        return await self._run_iteration(project, comments=[])

    def add_comment(
        self,
        project_id: str,
        episode_id: int,
        body: str,
        anchor: str | None = None,
        author_id: str = "human",
    ) -> HumanComment:
        project = self.repository.get_project(project_id)
        if project.status not in {
            WorkflowStatus.WAITING_HUMAN_REVIEW,
            WorkflowStatus.HUMAN_DECISION_REQUIRED,
        }:
            raise WorkflowConflict("Comments are accepted only while waiting for human review")
        if not project.current_version_id:
            raise WorkflowConflict("Project has no reviewable version")
        version = self.repository.get_version(project.current_version_id)
        episode_ids = {episode.episode for episode in version.script.episodes}
        if episode_id not in episode_ids:
            raise WorkflowConflict(f"Episode {episode_id} does not exist in the current version")
        comment = HumanComment(
            id=str(uuid4()),
            project_id=project_id,
            version_id=project.current_version_id,
            episode_id=episode_id,
            body=body,
            anchor=anchor,
            author_id=author_id,
        )
        self.repository.add_comment(comment)
        return comment

    async def generate_next(
        self, project_id: str, review_token: str, no_changes_confirmed: bool = False
    ) -> StoryVersion:
        snapshot = self.repository.get_project(project_id)
        if not snapshot.current_version_id:
            raise WorkflowConflict("Project has no current version")
        if (
            snapshot.config.max_iteration_budget is not None
            and snapshot.iteration >= snapshot.config.max_iteration_budget
        ):
            snapshot.status = WorkflowStatus.HUMAN_DECISION_REQUIRED
            snapshot.updated_at = utc_now()
            self.repository.save_project(snapshot)
            raise WorkflowConflict("Iteration budget exhausted; human budget decision required")
        comments = self.repository.list_open_comments(project_id, snapshot.current_version_id)
        if not comments and not no_changes_confirmed:
            raise WorkflowConflict(
                "Add at least one comment or explicitly confirm that no changes are needed"
            )
        project = self.repository.claim_review_token(project_id, review_token)
        try:
            version = await self._run_iteration(project, comments=comments, already_claimed=True)
            self.repository.mark_comments_consumed([comment.id for comment in comments])
            return version
        except Exception:
            failed = self.repository.get_project(project_id)
            failed.status = WorkflowStatus.FAILED
            failed.last_error = "Iteration failed after human approval"
            failed.updated_at = utc_now()
            self.repository.save_project(failed)
            raise

    def finalize(self, project_id: str, review_token: str) -> Project:
        project = self.repository.claim_review_token(project_id, review_token)
        project.status = WorkflowStatus.FINAL
        project.updated_at = utc_now()
        self.repository.save_project(project)
        return project

    async def _run_iteration(
        self,
        project: Project,
        comments: list[HumanComment],
        already_claimed: bool = False,
    ) -> StoryVersion:
        if (
            project.config.max_iteration_budget is not None
            and project.iteration >= project.config.max_iteration_budget
        ):
            raise WorkflowConflict("Iteration budget exhausted; human budget decision required")

        project.status = WorkflowStatus.GENERATING
        project.last_error = None
        project.updated_at = utc_now()
        if not already_claimed:
            project.human_review_token = None
        self.repository.save_project(project)

        prior = (
            self.repository.get_version(project.current_version_id)
            if project.current_version_id
            else None
        )
        config = to_dict(project.config)

        if prior is None:
            creative_brief = await self.llm.generate_json(creative_brief_task(project.idea, config))
            revision_brief = None
        else:
            creative_brief = prior.creative_brief
            revision_brief = await self.llm.generate_json(
                editor_task(
                    to_dict(prior.script),
                    [to_dict(review) for review in [*prior.reviews, prior.verification]],
                    [to_dict(comment) for comment in comments],
                )
            )

        script_payload = await self.llm.generate_json(
            writer_task(
                creative_brief,
                config,
                to_dict(prior.script) if prior else None,
                revision_brief,
            )
        )
        script = self._parse_script(script_payload)

        project.status = WorkflowStatus.REVIEWING
        project.updated_at = utc_now()
        self.repository.save_project(project)

        review_payloads = await asyncio.gather(
            *[
                self.llm.generate_json(reviewer_task(name, focus, to_dict(script)))
                for name, focus in REVIEWERS.items()
            ]
        )
        reviews = [
            self._parse_review(name, payload)
            for name, payload in zip(REVIEWERS, review_payloads, strict=True)
        ]
        verification_payload = await self.llm.generate_json(
            verification_task(to_dict(script), revision_brief)
        )
        verification = self._parse_review("Verification Agent", verification_payload)

        version = StoryVersion(
            id=str(uuid4()),
            project_id=project.id,
            version_number=project.iteration + 1,
            iteration=project.iteration + 1,
            parent_version_id=prior.id if prior else None,
            creative_brief=creative_brief,
            script=script,
            reviews=reviews,
            verification=verification,
            revision_brief=revision_brief,
        )
        self.repository.add_version(version)

        project.iteration += 1
        project.current_version_id = version.id
        project.status = WorkflowStatus.WAITING_HUMAN_REVIEW
        project.human_review_token = str(uuid4())
        project.updated_at = utc_now()
        self.repository.save_project(project)

        await self.notifications.iteration_ready(
            project,
            version,
            f"{self.review_base_url}/projects/{project.id}/review",
        )
        return version

    @staticmethod
    def _parse_script(payload: dict) -> ScriptDraft:
        episodes = [EpisodeDraft(**episode) for episode in payload["episodes"]]
        return ScriptDraft(
            title=payload["title"],
            logline=payload["logline"],
            story_bible=payload["story_bible"],
            character_bible=payload["character_bible"],
            episodes=episodes,
        )

    @staticmethod
    def _parse_review(reviewer: str, payload: dict) -> ReviewReport:
        findings = [
            ReviewFinding(
                reviewer=reviewer,
                severity=Severity(item["severity"]),
                episode_refs=item["episode_refs"],
                evidence=item["evidence"],
                judgment=item["judgment"],
                audience_risk=item["audience_risk"],
            )
            for item in payload.get("findings", [])
        ]
        return ReviewReport(reviewer=reviewer, score=float(payload["score"]), findings=findings)
