from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from screenwriter.domain.ports import ModelTask
from screenwriter.infrastructure.config import SqliteModelSettingsStore


@dataclass(frozen=True, slots=True)
class ModelRouting:
    default: str
    writer: str
    reviewer: str
    editor: str

    def for_role(self, role: str) -> str:
        return {
            "writer": self.writer,
            "reviewer": self.reviewer,
            "editor": self.editor,
        }.get(role, self.default)


class OpenAICompatibleProvider:
    """OpenAI-compatible Chat Completions adapter with JSON Schema output."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        routing: ModelRouting,
        timeout_seconds: float = 180,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.routing = routing
        self.timeout_seconds = timeout_seconds

    async def generate_json(self, task: ModelTask) -> dict[str, Any]:
        model = self.routing.for_role(task.role)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": task.system_prompt},
                {"role": "user", "content": task.user_prompt},
            ],
            "temperature": task.temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": task.name.replace(":", "_").replace("&", "and"),
                    "strict": True,
                    "schema": task.output_schema,
                },
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            return content
        return json.loads(content)


class ConfigurableLLMProvider:
    """Loads the active model connection before each task so UI changes apply immediately."""

    def __init__(self, settings_store: SqliteModelSettingsStore) -> None:
        self.settings_store = settings_store
        self.mock = MockLLMProvider()

    async def generate_json(self, task: ModelTask) -> dict[str, Any]:
        settings = self.settings_store.get()
        if settings.provider == "mock":
            return await self.mock.generate_json(task)
        if not settings.api_key:
            raise RuntimeError("Configure an API key before using a remote model")
        provider = OpenAICompatibleProvider(
            base_url=settings.base_url,
            api_key=settings.api_key,
            routing=ModelRouting(
                default=settings.default_model,
                writer=settings.writer_model,
                reviewer=settings.reviewer_model,
                editor=settings.editor_model,
            ),
            timeout_seconds=settings.timeout_seconds,
        )
        return await provider.generate_json(task)


class MockLLMProvider:
    """Deterministic local provider used for tests and API smoke runs."""

    async def generate_json(self, task: ModelTask) -> dict[str, Any]:
        if task.name == "creative_brief":
            return {
                "premise": "一个处于绝境的普通人被迫揭开隐藏身份。",
                "audience": "海外竖屏短剧用户",
                "tone": "高冲突、强情绪、快节奏",
                "constraints": ["前三集讲清主线", "每集必须有钩子"],
            }
        if task.name == "writer":
            return {
                "title": "《Mock Story》剧本",
                "logline": "女主必须在身份暴露前找到真相。",
                "story_bible": {
                    "world": "当代都市",
                    "social_structure": "财富与身份分层明显",
                    "power_structure": "家族企业控制关键资源",
                    "rules": ["秘密一旦公开就会改变继承权"],
                    "special_device": "匿名信",
                    "main_conflict": "身份与信任",
                },
                "character_bible": [
                    {
                        "name": "艾拉",
                        "identity": "普通职员",
                        "desire": "保护家人",
                        "goal": "查清真相",
                        "fear": "失去唯一的家人",
                        "secret": "父亲并未真正死亡",
                        "action_logic": "先验证证据再冒险",
                        "relationship": "主角",
                        "story_function": "推动调查主线",
                    }
                ],
                "episodes": [
                    {
                        "episode": 1,
                        "title": "第一集",
                        "screenplay": (
                            "1-1  夜  外  别墅前院\n出场人物：艾拉\n\n"
                            "▲ 艾拉攥紧一封匿名信。\n\n"
                            '艾拉（紧张）: "Who sent this?"（是谁寄来的？）'
                        ),
                        "ending_hook": "匿名信上出现她失踪父亲的签名。",
                    }
                ],
            }
        if task.name == "chief_editor":
            return {
                "must_fix": ["落实全部人工批注"],
                "should_fix": [],
                "locked_elements": ["已确认的人物核心动机"],
            }
        return {
            "score": 8.0,
            "findings": [
                {
                    "severity": "B",
                    "episode_refs": [1],
                    "evidence": "EP1 结尾出现失踪父亲签名。",
                    "judgment": "集尾形成明确问题。",
                    "audience_risk": "风险较低，但下一集必须及时升级。",
                }
            ],
        }
