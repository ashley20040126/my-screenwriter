from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from screenwriter.application.orchestrator import ScreenwriterService, WorkflowConflict
from screenwriter.domain.models import ProjectConfig, to_dict
from screenwriter.infrastructure.config import ModelConnectionConfig, SqliteModelSettingsStore
from screenwriter.infrastructure.llm import ConfigurableLLMProvider
from screenwriter.infrastructure.notifications import LoggingNotificationAdapter
from screenwriter.infrastructure.repository import NotFoundError, SqliteProjectRepository


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_database_path: str = "./data/screenwriter.db"
    app_review_base_url: str = "http://localhost:8000"
    llm_provider: str = "mock"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_default_model: str = "gpt-5-mini"
    llm_writer_model: str = "gpt-5"
    llm_reviewer_model: str = "gpt-5-mini"
    llm_editor_model: str = "gpt-5-mini"
    llm_timeout_seconds: float = 180
    app_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"


class ProjectConfigInput(BaseModel):
    market: str = "欧美"
    episode_count: int = Field(default=60, ge=1, le=200)
    episode_duration_seconds: int = Field(default=120, ge=15, le=1800)
    first_paywall_episode: int = Field(default=10, ge=1)
    budget_level: str = "中等"
    max_iteration_budget: int | None = Field(default=None, ge=1)


class CreateProjectInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    idea: str = Field(min_length=1, max_length=10000)
    config: ProjectConfigInput = Field(default_factory=ProjectConfigInput)


class CommentInput(BaseModel):
    episode_id: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=10000)
    anchor: str | None = Field(default=None, max_length=1000)
    author_id: str = "human"


class ReviewActionInput(BaseModel):
    review_token: str
    no_changes_confirmed: bool = False


class ModelSettingsInput(BaseModel):
    provider: str = Field(pattern="^(mock|openai-compatible)$")
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str | None = Field(default=None, max_length=1000)
    default_model: str = Field(min_length=1, max_length=200)
    writer_model: str = Field(min_length=1, max_length=200)
    reviewer_model: str = Field(min_length=1, max_length=200)
    editor_model: str = Field(min_length=1, max_length=200)
    timeout_seconds: float = Field(default=180, ge=10, le=900)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_model_settings_store() -> SqliteModelSettingsStore:
    settings = get_settings()
    defaults = ModelConnectionConfig(
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        default_model=settings.llm_default_model,
        writer_model=settings.llm_writer_model,
        reviewer_model=settings.llm_reviewer_model,
        editor_model=settings.llm_editor_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return SqliteModelSettingsStore(settings.app_database_path, defaults)


@lru_cache
def get_service() -> ScreenwriterService:
    settings = get_settings()
    repository = SqliteProjectRepository(settings.app_database_path)
    llm = ConfigurableLLMProvider(get_model_settings_store())
    return ScreenwriterService(
        repository,
        llm,
        LoggingNotificationAdapter(),
        review_base_url=settings.app_review_base_url,
    )


ServiceDep = Annotated[ScreenwriterService, Depends(get_service)]


app = FastAPI(title="My Screenwriter API", version="0.1.0")
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.app_cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def guard(action):
    try:
        return action()
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Resource not found") from exc
    except (WorkflowConflict, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/projects", status_code=201)
def create_project(payload: CreateProjectInput, service: ServiceDep) -> dict[str, Any]:
    config = ProjectConfig(**payload.config.model_dump())
    project = service.create_project(payload.title, payload.idea, config)
    return to_dict(project)


@app.get("/projects")
def list_projects(service: ServiceDep) -> list[dict[str, Any]]:
    return [to_dict(project) for project in service.repository.list_projects()]


@app.get("/projects/{project_id}")
def get_project(project_id: str, service: ServiceDep) -> dict[str, Any]:
    return guard(lambda: to_dict(service.repository.get_project(project_id)))


@app.post("/projects/{project_id}/iterations", status_code=201)
async def generate_initial(project_id: str, service: ServiceDep) -> dict[str, Any]:
    try:
        return to_dict(await service.generate_initial(project_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except WorkflowConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/projects/{project_id}/comments", status_code=201)
def add_comment(
    project_id: str,
    payload: CommentInput,
    service: ServiceDep,
) -> dict[str, Any]:
    return guard(
        lambda: to_dict(
            service.add_comment(
                project_id,
                payload.episode_id,
                payload.body,
                payload.anchor,
                payload.author_id,
            )
        )
    )


@app.get("/projects/{project_id}/comments")
def list_comments(
    project_id: str,
    service: ServiceDep,
    version_id: str = Query(min_length=1),
) -> list[dict[str, Any]]:
    return [
        to_dict(comment)
        for comment in service.repository.list_open_comments(project_id, version_id)
    ]


@app.post("/projects/{project_id}/review/generate", status_code=201)
async def generate_next(
    project_id: str,
    payload: ReviewActionInput,
    service: ServiceDep,
) -> dict[str, Any]:
    try:
        version = await service.generate_next(
            project_id, payload.review_token, payload.no_changes_confirmed
        )
        return to_dict(version)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except (WorkflowConflict, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/projects/{project_id}/review/finalize")
def finalize(
    project_id: str,
    payload: ReviewActionInput,
    service: ServiceDep,
) -> dict[str, Any]:
    return guard(lambda: to_dict(service.finalize(project_id, payload.review_token)))


@app.get("/projects/{project_id}/versions")
def list_versions(project_id: str, service: ServiceDep) -> list[dict[str, Any]]:
    return [to_dict(version) for version in service.repository.list_versions(project_id)]


@app.get("/versions/{version_id}")
def get_version(version_id: str, service: ServiceDep) -> dict[str, Any]:
    return guard(lambda: to_dict(service.repository.get_version(version_id)))


@app.get("/settings/model")
def get_model_settings() -> dict[str, Any]:
    config = get_model_settings_store().get()
    return {
        "provider": config.provider,
        "base_url": config.base_url,
        "has_api_key": bool(config.api_key),
        "default_model": config.default_model,
        "writer_model": config.writer_model,
        "reviewer_model": config.reviewer_model,
        "editor_model": config.editor_model,
        "timeout_seconds": config.timeout_seconds,
    }


@app.put("/settings/model")
def update_model_settings(payload: ModelSettingsInput) -> dict[str, Any]:
    store = get_model_settings_store()
    current = store.get()
    config = ModelConnectionConfig(
        provider=payload.provider,
        base_url=payload.base_url.rstrip("/"),
        api_key=current.api_key if payload.api_key is None else payload.api_key,
        default_model=payload.default_model,
        writer_model=payload.writer_model,
        reviewer_model=payload.reviewer_model,
        editor_model=payload.editor_model,
        timeout_seconds=payload.timeout_seconds,
    )
    if config.provider != "mock" and not config.api_key:
        raise HTTPException(status_code=422, detail="API key is required for a remote model")
    store.save(config)
    return get_model_settings()
