from __future__ import annotations

import json
from typing import Any

from screenwriter.domain.ports import ModelTask

SCRIPT_FORMAT_REFERENCE = "https://ycnbhmgr4z9b.feishu.cn/docx/QCEidXpT5ogM1HxeQXrcha7onXd"
REVIEW_STANDARD_REFERENCE = "https://ycnbhmgr4z9b.feishu.cn/docx/NSTidkU9YodkBPxL9yYcMnaLngb"


SCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "logline", "story_bible", "character_bible", "episodes"],
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "story_bible": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "world",
                "social_structure",
                "power_structure",
                "rules",
                "special_device",
                "main_conflict",
            ],
            "properties": {
                "world": {"type": "string"},
                "social_structure": {"type": "string"},
                "power_structure": {"type": "string"},
                "rules": {"type": "array", "items": {"type": "string"}},
                "special_device": {"type": "string"},
                "main_conflict": {"type": "string"},
            },
        },
        "character_bible": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "name",
                    "identity",
                    "desire",
                    "goal",
                    "fear",
                    "secret",
                    "action_logic",
                    "relationship",
                    "story_function",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "identity": {"type": "string"},
                    "desire": {"type": "string"},
                    "goal": {"type": "string"},
                    "fear": {"type": "string"},
                    "secret": {"type": "string"},
                    "action_logic": {"type": "string"},
                    "relationship": {"type": "string"},
                    "story_function": {"type": "string"},
                },
            },
        },
        "episodes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["episode", "title", "screenplay", "ending_hook"],
                "properties": {
                    "episode": {"type": "integer"},
                    "title": {"type": "string"},
                    "screenplay": {"type": "string"},
                    "ending_hook": {"type": "string"},
                },
            },
        },
    },
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["score", "findings"],
    "properties": {
        "score": {"type": "number", "minimum": 0, "maximum": 10},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "severity",
                    "episode_refs",
                    "evidence",
                    "judgment",
                    "audience_risk",
                ],
                "properties": {
                    "severity": {"type": "string", "enum": ["S", "A", "B"]},
                    "episode_refs": {"type": "array", "items": {"type": "integer"}},
                    "evidence": {"type": "string"},
                    "judgment": {"type": "string"},
                    "audience_risk": {"type": "string"},
                },
            },
        },
    },
}


def creative_brief_task(idea: str, config: dict[str, Any]) -> ModelTask:
    return ModelTask(
        name="creative_brief",
        role="brief",
        system_prompt="你是短剧 Creative Brief Agent。只定义创作约束，不直接写剧本。",
        user_prompt=f"灵感：{idea}\n项目配置：{json.dumps(config, ensure_ascii=False)}",
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["premise", "audience", "tone", "constraints"],
            "properties": {
                "premise": {"type": "string"},
                "audience": {"type": "string"},
                "tone": {"type": "string"},
                "constraints": {"type": "array", "items": {"type": "string"}},
            },
        },
    )


def writer_task(
    creative_brief: dict[str, Any],
    config: dict[str, Any],
    prior_script: dict[str, Any] | None,
    revision_brief: dict[str, Any] | None,
) -> ModelTask:
    format_rules = """
可交付剧本必须遵守《剧本标准格式说明》：
1. 剧名、集数、集间分隔清晰；
2. 场景标题为“集数-场景号  时间  内/外  地点”；
3. 场景标题下列出出场人物；动作行以 ▲ 开头；
4. 对白为 角色名（情绪）: \"English dialogue\"（中文翻译）；
5. OS、特效、字幕、黑场转场按标准标注。
"""
    payload = {
        "creative_brief": creative_brief,
        "project_config": config,
        "prior_script": prior_script,
        "revision_brief": revision_brief,
    }
    return ModelTask(
        name="writer",
        role="writer",
        system_prompt=(
            "你是系统中唯一拥有剧情创作权的 Story Writer。"
            f"格式权威文档：{SCRIPT_FORMAT_REFERENCE}\n{format_rules}"
        ),
        user_prompt=json.dumps(payload, ensure_ascii=False),
        output_schema=SCRIPT_SCHEMA,
        temperature=0.7,
    )


def reviewer_task(reviewer: str, focus: str, script: dict[str, Any]) -> ModelTask:
    return ModelTask(
        name=f"reviewer:{reviewer}",
        role="reviewer",
        system_prompt=(
            f"你是 {reviewer}。你只有诊断权，没有创作权。审查重点：{focus}。\n"
            f"统一审查标准：{REVIEW_STANDARD_REFERENCE}\n"
            "必须严格基于剧本，先讲可定位的事实证据，再讲判断；推测必须明确标注。"
            "优先检查第一集第一场、前三集、首个付费点前剧情、主角驱动力、冲突升级、"
            "爽点、集尾钩子、铺垫回收、人物功能和可拍摄性。"
        ),
        user_prompt=json.dumps(script, ensure_ascii=False),
        output_schema=REVIEW_SCHEMA,
    )


def editor_task(
    prior_script: dict[str, Any], reviews: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> ModelTask:
    return ModelTask(
        name="chief_editor",
        role="editor",
        system_prompt=(
            "你是 Chief Editor。把 Reviewer 诊断与人工批注整理成 Revision Brief。"
            "不得擅自增加人工未要求的新剧情；人工批注优先级高于 AI 建议。"
        ),
        user_prompt=json.dumps(
            {"prior_script": prior_script, "reviews": reviews, "human_comments": comments},
            ensure_ascii=False,
        ),
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["must_fix", "should_fix", "locked_elements"],
            "properties": {
                "must_fix": {"type": "array", "items": {"type": "string"}},
                "should_fix": {"type": "array", "items": {"type": "string"}},
                "locked_elements": {"type": "array", "items": {"type": "string"}},
            },
        },
    )


def verification_task(script: dict[str, Any], revision_brief: dict[str, Any] | None) -> ModelTask:
    return ModelTask(
        name="verification",
        role="reviewer",
        system_prompt=(
            "你是 Verification Agent。检查格式合规、回归问题、Revision Brief 是否落实。"
            "只报告证据和判断，不创作剧情。"
        ),
        user_prompt=json.dumps(
            {"script": script, "revision_brief": revision_brief}, ensure_ascii=False
        ),
        output_schema=REVIEW_SCHEMA,
    )
