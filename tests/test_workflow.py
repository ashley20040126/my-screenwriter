from __future__ import annotations

from pathlib import Path

import pytest

from screenwriter.application.orchestrator import ScreenwriterService
from screenwriter.domain.models import WorkflowStatus
from screenwriter.infrastructure.llm import MockLLMProvider
from screenwriter.infrastructure.notifications import RecordingNotificationAdapter
from screenwriter.infrastructure.repository import SqliteProjectRepository


@pytest.fixture
def service(tmp_path: Path):
    notifications = RecordingNotificationAdapter()
    repository = SqliteProjectRepository(str(tmp_path / "test.db"))
    return (
        ScreenwriterService(repository, MockLLMProvider(), notifications),
        repository,
        notifications,
    )


@pytest.mark.asyncio
async def test_iteration_pauses_for_human_review_and_notifies(service):
    app, repository, notifications = service
    project = app.create_project("Test", "一个身份错位的爱情故事")

    version = await app.generate_initial(project.id)
    current = repository.get_project(project.id)

    assert version.version_number == 1
    assert current.status == WorkflowStatus.WAITING_HUMAN_REVIEW
    assert current.human_review_token
    assert notifications.events[0]["version_id"] == version.id


@pytest.mark.asyncio
async def test_human_comment_is_consumed_by_next_iteration(service):
    app, repository, _ = service
    project = app.create_project("Test", "一个身份错位的爱情故事")
    first = await app.generate_initial(project.id)
    app.add_comment(project.id, 1, "这一集结尾的钩子需要更强", anchor="ending_hook")
    token = repository.get_project(project.id).human_review_token

    second = await app.generate_next(project.id, token)
    current = repository.get_project(project.id)

    assert second.parent_version_id == first.id
    assert second.revision_brief is not None
    assert current.iteration == 2
    assert current.status == WorkflowStatus.WAITING_HUMAN_REVIEW
    assert repository.list_open_comments(project.id, first.id) == []


@pytest.mark.asyncio
async def test_finalize_requires_and_consumes_review_token(service):
    app, repository, _ = service
    project = app.create_project("Test", "一个身份错位的爱情故事")
    await app.generate_initial(project.id)
    token = repository.get_project(project.id).human_review_token

    final = app.finalize(project.id, token)

    assert final.status == WorkflowStatus.FINAL
    with pytest.raises(RuntimeError):
        app.finalize(project.id, token)
