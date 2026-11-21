"""Generate response-extract transform scripts with a grader model."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.models.schemas import AiExtractRequest, AiExtractResponse, GraderMeta
from app.services.provider_probe import (
    build_auth_headers,
    extract_openai_model,
    normalize_api_base,
    resolve_provider_target,
)

AI_EXTRACT_TIMEOUT = 60.0
MAX_SAMPLE_CHARS = 12000

SYSTEM_PROMPT = """你是 EvalKit 的响应提取助手。用户会提供一份 API 测试响应 JSON，以及他们勾选想保留的字段路径/示例值。
请编写一段 JavaScript 代码片段，用于从同类响应中提取纯文本 output。

硬性要求：
1. 只输出 JavaScript 代码，不要 markdown 代码围栏，不要解释。
2. 代码运行时作用域已有变量：obj（解析后的 JSON 对象，可能为 null）、text（原始响应字符串）、value（初始为 ''）。
3. 你的代码必须给 value 赋值为最终要评测的字符串。
4. 不要定义函数声明外层的 (json, text)=>，不要 return；只写片段。
5. 不要输出 JSON 结构字段名本身（如 type、paragraph），只要用户想要的正文内容。
6. 尽量写得可泛化：例如递归收集 content 树里所有 text 字段，而不是写死 content[0]。
7. 多个片段用换行 \\n 拼接。
8. 代码必须可在 promptfoo transformResponse 中安全执行。"""


def _trim_sample(sample: str) -> str:
    text = sample or ""
    if len(text) <= MAX_SAMPLE_CHARS:
        return text
    return text[:MAX_SAMPLE_CHARS] + "\n…(truncated)"


def _strip_code_fence(content: str) -> str:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:javascript|js|typescript|ts)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _looks_like_script(script: str) -> bool:
    body = script.strip()
    if not body or len(body) > 8000:
        return False
    # Must assign value somehow.
    if not re.search(r"\bvalue\s*=", body):
        return False
    # Reject full arrow wrappers — we inject into an existing function.
    if re.search(r"^\s*\(?\s*json\s*,\s*text\s*\)?\s*=>", body):
        return False
    return True


def _chat_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts)
    text = first.get("text")
    return str(text or "")


async def _call_openai_grader(grader: GraderMeta, user_prompt: str) -> tuple[str | None, str | None]:
    resolved_id, host = resolve_provider_target(grader.provider_id, grader.api_host)
    api_base = normalize_api_base(host, resolved_id)
    model = extract_openai_model(resolved_id)
    if not model:
        return None, "评分模型 Provider ID 无效，请使用 openai:chat:模型名"
    if not api_base:
        return None, "缺少 API Host"

    headers, key = build_auth_headers(grader.api_key, grader.organization)
    if not key:
        return None, "评分模型缺少 API Key（表单或环境变量 OPENAI_API_KEY）"

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    max_tokens = grader.max_tokens
    if max_tokens:
        body["max_tokens"] = int(max_tokens)

    url = f"{api_base.rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(
        timeout=AI_EXTRACT_TIMEOUT,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        try:
            response = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException:
            return None, f"模型请求超时（>{int(AI_EXTRACT_TIMEOUT)}s）"
        except httpx.RequestError as exc:
            return None, f"无法连接评分模型：{exc}"

    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text[:500]}

    if response.status_code >= 400:
        detail = ""
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or "")
            elif payload.get("detail"):
                detail = str(payload["detail"])
        return None, f"模型调用失败 HTTP {response.status_code}" + (f"：{detail}" if detail else "")

    content = _strip_code_fence(_chat_content(payload))
    if not content:
        return None, "模型未返回可用代码"
    if not _looks_like_script(content):
        return None, "模型返回的代码不符合约定（需给 value 赋值，且不要包一层 (json,text)=>）"
    return content, None


def _build_user_prompt(payload: AiExtractRequest) -> str:
    selected = []
    for item in payload.selected_values:
        selected.append({"path": item.path, "value": item.value})
    hint = (payload.hint or "").strip() or "只要正文，去除结构冗余"
    return (
        f"响应格式：{payload.source}\n"
        f"用户说明：{hint}\n"
        f"勾选路径与示例值：\n{json.dumps(selected, ensure_ascii=False, indent=2)}\n\n"
        f"测试响应：\n{_trim_sample(payload.sample_text)}\n\n"
        "请输出提取代码片段。"
    )


async def generate_ai_extract_script(
    payload: AiExtractRequest,
    grader: GraderMeta,
) -> AiExtractResponse:
    if grader.kind != "openai":
        return AiExtractResponse(
            ok=False,
            message="AI 取值目前仅支持 OpenAI 兼容的评分模型，请在「模型评测配置」中选择/新建",
        )
    if not payload.selected_values and not payload.hint.strip():
        return AiExtractResponse(ok=False, message="请先勾选测试响应中想保留的字段，或填写提取说明")
    if not (payload.sample_text or "").strip():
        return AiExtractResponse(ok=False, message="缺少测试响应，请先「测试连通」")

    script, err = await _call_openai_grader(grader, _build_user_prompt(payload))
    if err or not script:
        return AiExtractResponse(ok=False, message=err or "生成失败")
    return AiExtractResponse(
        ok=True,
        message="已生成提取规则",
        ai_script=script,
        grader_id=grader.id,
        grader_name=grader.name,
    )
