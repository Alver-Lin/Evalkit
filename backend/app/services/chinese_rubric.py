"""Chinese grading prompt for promptfoo model-graded assertions (llm-rubric etc.)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Mirrors frontend/src/utils/promptfooConfig.ts CHINESE_RUBRIC_PROMPT.
CHINESE_RUBRIC_PROMPT: list[dict[str, str]] = [
    {
        "role": "system",
        "content": (
            "你是评分助手，根据用户给定的评分标准（rubric）评判模型输出。\n"
            "若评分标准中的陈述对输出成立，则判定通过。\n"
            '你必须只返回如下 JSON 对象：{"reason": string, "pass": boolean, "score": number}。\n'
            "reason 字段必须用简体中文简要说明判定依据，不要使用英文。\n"
            "\n"
            "示例：\n"
            "\n"
            "<Output>你好，世界</Output>\n"
            "<Rubric>内容包含问候</Rubric>\n"
            '{"reason": "输出包含问候语「你好」", "pass": true, "score": 1.0}\n'
            "\n"
            "<Output>阿弥陀佛，施主请进</Output>\n"
            "<Rubric>不以古风语气说话</Rubric>\n"
            '{"reason": "「阿弥陀佛」「施主」属于古风用语，不符合标准", "pass": false, "score": 0.0}'
        ),
    },
    {
        "role": "user",
        "content": "<Output>\n{{ output }}\n</Output>\n<Rubric>\n{{ rubric }}\n</Rubric>",
    },
]


EVALKIT_RUBRIC_MARKER = "你是评分助手，根据用户给定的评分标准（rubric）评判模型输出。"


def _is_evalkit_rubric_prompt(raw: Any) -> bool:
    if raw is None or raw == "":
        return False
    if isinstance(raw, str):
        return EVALKIT_RUBRIC_MARKER in raw
    if not isinstance(raw, list):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str) and EVALKIT_RUBRIC_MARKER in content:
            return True
    return False


def strip_evalkit_rubric_prompt_text(yaml_content: str) -> str:
    """Remove EvalKit-injected rubricPrompt from user-facing YAML text."""
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError:
        return yaml_content
    if not isinstance(data, dict):
        return yaml_content

    cleaned = strip_evalkit_rubric_prompt_mapping(data)
    if cleaned is data:
        return yaml_content
    return yaml.safe_dump(
        cleaned,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )


def strip_evalkit_rubric_prompt_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Return mapping without EvalKit default rubricPrompt (may return same object)."""
    default_test = data.get("defaultTest")
    if not isinstance(default_test, dict):
        return data

    options = default_test.get("options")
    if not isinstance(options, dict) or not _is_evalkit_rubric_prompt(options.get("rubricPrompt")):
        return data

    next_options = {k: v for k, v in options.items() if k != "rubricPrompt"}
    next_default = {**default_test}
    if next_options:
        next_default["options"] = next_options
    else:
        next_default.pop("options", None)

    next_data = {**data}
    if next_default:
        next_data["defaultTest"] = next_default
    else:
        next_data.pop("defaultTest", None)
    return next_data


def ensure_chinese_rubric_prompt(yaml_path: Path) -> None:
    """Inject Chinese rubricPrompt into defaultTest.options when unset.

    Applies to staged run configs only — user-facing YAML stays clean.
    """
    raw = yaml_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        return

    default_test = data.get("defaultTest")
    if not isinstance(default_test, dict):
        default_test = {}

    options = default_test.get("options")
    if not isinstance(options, dict):
        options = {}

    if options.get("rubricPrompt") not in (None, ""):
        return

    options = {**options, "rubricPrompt": CHINESE_RUBRIC_PROMPT}
    default_test = {**default_test, "options": options}
    data = {**data, "defaultTest": default_test}

    yaml_path.write_text(
        yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
    )


def apply_to_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of config mapping with Chinese rubricPrompt if missing."""
    default_test = data.get("defaultTest")
    if not isinstance(default_test, dict):
        default_test = {}
    options = default_test.get("options")
    if not isinstance(options, dict):
        options = {}
    if options.get("rubricPrompt") not in (None, ""):
        return data
    return {
        **data,
        "defaultTest": {
            **default_test,
            "options": {**options, "rubricPrompt": CHINESE_RUBRIC_PROMPT},
        },
    }
