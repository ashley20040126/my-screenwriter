from __future__ import annotations

import logging

from screenwriter.domain.models import Project, StoryVersion

logger = logging.getLogger(__name__)


class LoggingNotificationAdapter:
    async def iteration_ready(
        self, project: Project, version: StoryVersion, review_url: str
    ) -> None:
        logger.info(
            "iteration_ready project=%s iteration=%s version=%s review_url=%s",
            project.id,
            project.iteration,
            version.id,
            review_url,
        )


class RecordingNotificationAdapter:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def iteration_ready(
        self, project: Project, version: StoryVersion, review_url: str
    ) -> None:
        self.events.append(
            {
                "project_id": project.id,
                "iteration": project.iteration,
                "version_id": version.id,
                "review_url": review_url,
            }
        )
