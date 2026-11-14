from __future__ import annotations

from fastapi.testclient import TestClient

from screenwriter.api.app import get_model_settings_store, get_service, get_settings
from screenwriter.main import app


def test_api_human_review_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_service.cache_clear()
    get_settings.cache_clear()
    get_model_settings_store.cache_clear()

    with TestClient(app) as client:
        created = client.post(
            "/projects",
            json={"title": "API Test", "idea": "一个身份错位的爱情故事"},
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

        generated = client.post(f"/projects/{project_id}/iterations")
        assert generated.status_code == 201

        project = client.get(f"/projects/{project_id}").json()
        assert project["status"] == "WAITING_HUMAN_REVIEW"
        token = project["human_review_token"]

        comment = client.post(
            f"/projects/{project_id}/comments",
            json={"episode_id": 1, "body": "增强集尾钩子", "anchor": "ending_hook"},
        )
        assert comment.status_code == 201

        next_iteration = client.post(
            f"/projects/{project_id}/review/generate",
            json={"review_token": token},
        )
        assert next_iteration.status_code == 201
        assert next_iteration.json()["version_number"] == 2

    get_service.cache_clear()
    get_settings.cache_clear()
    get_model_settings_store.cache_clear()
