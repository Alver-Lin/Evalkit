from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.models.schemas import ProviderProbeRequest, ProviderProbeResponse


DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
PROBE_TIMEOUT = 20.0


def _trim(value: str | None) -> str:
    return (value or "").strip()


def resolve_provider_target(provider_id: str, api_host: str = "") -> tuple[str, str]:
    raw = _trim(provider_id)
    host = _trim(api_host)
    if not raw:
        return "", host

    lower = raw.lower()
    if lower == "deepseek" or lower.startswith("deepseek:"):
        # deepseek-chat retired; current API models are deepseek-flash / deepseek-v4-pro.
        model = (
            "deepseek-flash"
            if lower == "deepseek"
            else (raw.split(":", 1)[1].strip() or "deepseek-flash")
        )
        resolved_id = model if model.startswith("openai:") else f"openai:chat:{model}"
        return resolved_id, host or "https://api.deepseek.com/v1"

    return raw, host


def extract_openai_model(provider_id: str) -> str | None:
    parts = provider_id.split(":")
    if not parts or parts[0].lower() != "openai":
        return None
    if len(parts) == 1:
        return None
    if len(parts) == 2:
        return parts[1].strip() or None
    # openai:chat:model / openai:completion:model / openai:embeddings:model
    return ":".join(parts[2:]).strip() or None


def normalize_api_base(api_host: str, provider_id: str) -> str:
    host = _trim(api_host)
    if host:
        return host.rstrip("/")
    if provider_id.lower().startswith("openai:"):
        return os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_HOST") or DEFAULT_OPENAI_BASE
    return ""


def build_auth_headers(api_key: str, organization: str) -> tuple[dict[str, str], str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = _trim(api_key) or _trim(os.getenv("OPENAI_API_KEY"))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    org = _trim(organization) or _trim(os.getenv("OPENAI_ORGANIZATION"))
    if org:
        headers["OpenAI-Organization"] = org
    return headers, key


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None = None,
) -> tuple[int | None, Any, str | None, int]:
    started = time.perf_counter()
    try:
        response = await client.request(method, url, headers=headers, json=json_body)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        try:
            payload: Any = response.json()
        except Exception:
            payload = response.text[:500]
        return response.status_code, payload, None, elapsed_ms
    except httpx.TimeoutException:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return None, None, f"请求超时（>{int(PROBE_TIMEOUT)}s）：{url}", elapsed_ms
    except httpx.RequestError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return None, None, f"无法连接：{exc}", elapsed_ms


def _error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("code")
            if msg:
                return str(msg)
        detail = payload.get("detail")
        if detail:
            return str(detail)
        return str(payload)[:300]
    if payload is None:
        return "未知错误"
    return str(payload)[:300]


def _model_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
    return ids


async def probe_openai_compatible(
    *,
    provider_id: str,
    api_base: str,
    api_key: str,
    organization: str,
) -> ProviderProbeResponse:
    model = extract_openai_model(provider_id)
    if not model:
        return ProviderProbeResponse(
            ok=False,
            message="无法从 Provider ID 解析模型名，请使用 openai:chat:模型名",
            provider_id=provider_id,
            api_base=api_base,
        )

    headers, resolved_key = build_auth_headers(api_key, organization)
    if not resolved_key:
        return ProviderProbeResponse(
            ok=False,
            message="缺少 API Key：请在表单填写，或设置环境变量 OPENAI_API_KEY",
            provider_id=provider_id,
            api_base=api_base,
            model=model,
        )

    models_url = f"{api_base}/models"
    chat_url = f"{api_base}/chat/completions"
    details: dict[str, Any] = {"models_url": models_url, "chat_url": chat_url}

    # Bypass OS/HTTP proxies so LAN endpoints (e.g. 172.x) are not forced
    # through a local gateway that often returns 502 for private IPs.
    async with httpx.AsyncClient(
        timeout=PROBE_TIMEOUT,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        status, payload, err, models_ms = await _request_json(client, "GET", models_url, headers=headers)
        details["models_status"] = status
        details["models_latency_ms"] = models_ms

        if err:
            return ProviderProbeResponse(
                ok=False,
                message=err,
                provider_id=provider_id,
                api_base=api_base,
                model=model,
                latency_ms=models_ms,
                details=details,
            )

        model_list = _model_ids(payload)
        if status and status < 400 and model_list:
            details["available_models"] = model_list[:20]
            if model not in model_list:
                preview = ", ".join(model_list[:8])
                return ProviderProbeResponse(
                    ok=False,
                    message=f"服务可达，但模型 `{model}` 不在 /models 列表中。可用：{preview}",
                    provider_id=provider_id,
                    api_base=api_base,
                    model=model,
                    latency_ms=models_ms,
                    details=details,
                )

        # Always verify chat completions — this is what eval actually uses.
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
            "temperature": 0,
        }
        chat_status, chat_payload, chat_err, chat_ms = await _request_json(
            client,
            "POST",
            chat_url,
            headers=headers,
            json_body=body,
        )
        details["chat_status"] = chat_status
        details["chat_latency_ms"] = chat_ms
        total_ms = models_ms + chat_ms

        if chat_err:
            return ProviderProbeResponse(
                ok=False,
                message=chat_err,
                provider_id=provider_id,
                api_base=api_base,
                model=model,
                latency_ms=total_ms,
                details=details,
            )

        if chat_status is None or chat_status >= 400:
            detail = _error_message(chat_payload).strip()
            if status and status >= 400:
                models_detail = _error_message(payload).strip()
                prefix = f"/models 也返回 HTTP {status}"
                if models_detail:
                    prefix = f"{prefix}（{models_detail}）"
                detail = f"{detail}；{prefix}" if detail else prefix
            msg = f"Chat Completions 失败（HTTP {chat_status}）"
            if detail:
                msg = f"{msg}：{detail}"
            return ProviderProbeResponse(
                ok=False,
                message=msg,
                provider_id=provider_id,
                api_base=api_base,
                model=model,
                latency_ms=total_ms,
                details=details,
            )

        return ProviderProbeResponse(
            ok=True,
            message=f"连通正常：模型 `{model}` 可调用（{chat_ms}ms）",
            provider_id=provider_id,
            api_base=api_base,
            model=model,
            latency_ms=total_ms,
            details=details,
        )


async def probe_http_url(url: str, method: str = "GET") -> ProviderProbeResponse:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ProviderProbeResponse(ok=False, message="HTTP Provider URL 无效", provider_id=url)

    verb = _trim(method).upper() or "GET"
    if verb not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
        verb = "GET"

    async with httpx.AsyncClient(
        timeout=PROBE_TIMEOUT,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        started = time.perf_counter()
        try:
            if verb == "GET":
                response = await client.get(url)
            elif verb == "HEAD":
                response = await client.head(url)
            elif verb == "OPTIONS":
                response = await client.options(url)
            else:
                # Lightweight connectivity probe — empty JSON body, no SSE parse.
                response = await client.request(
                    verb,
                    url,
                    headers={"Content-Type": "application/json", "Accept": "*/*"},
                    content=b"{}",
                )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
        except httpx.TimeoutException:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return ProviderProbeResponse(
                ok=False,
                message=f"请求超时（>{int(PROBE_TIMEOUT)}s）",
                provider_id=url,
                api_base=url,
                latency_ms=elapsed_ms,
                details={"method": verb},
            )
        except httpx.RequestError as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return ProviderProbeResponse(
                ok=False,
                message=f"无法连接：{exc}",
                provider_id=url,
                api_base=url,
                latency_ms=elapsed_ms,
                details={"method": verb},
            )

    # Raw HTTP providers still need body for eval; here we only check reachability.
    if response.status_code >= 500:
        return ProviderProbeResponse(
            ok=False,
            message=f"服务返回 HTTP {response.status_code}（{verb}）",
            provider_id=url,
            api_base=url,
            latency_ms=elapsed_ms,
            details={"method": verb, "hint": "自定义 HTTP 评测还需配置 Body / transformResponse"},
        )

    return ProviderProbeResponse(
        ok=True,
        message=f"地址可达（{verb} HTTP {response.status_code}）。评测请确认 Body 与响应提取配置",
        provider_id=url,
        api_base=url,
        latency_ms=elapsed_ms,
        details={"method": verb},
    )


async def probe_provider(payload: ProviderProbeRequest) -> ProviderProbeResponse:
    provider_id, api_host = resolve_provider_target(payload.id, payload.api_host)
    if not provider_id:
        return ProviderProbeResponse(ok=False, message="请先填写 Provider ID")

    lower = provider_id.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        return await probe_http_url(provider_id, method=payload.method or "GET")

    if lower.startswith("openai:"):
        api_base = normalize_api_base(api_host, provider_id)
        if not api_base:
            return ProviderProbeResponse(
                ok=False,
                message="缺少 API Host（apiBaseUrl），例如 http://host:port/v1",
                provider_id=provider_id,
            )
        # Guard common mistake: host ends with /models or /chat/completions
        bad_suffixes = ("/models", "/chat/completions", "/completions")
        for suffix in bad_suffixes:
            if api_base.endswith(suffix):
                return ProviderProbeResponse(
                    ok=False,
                    message=f"API Host 不应包含 `{suffix}`，请只填到 /v1",
                    provider_id=provider_id,
                    api_base=api_base,
                )
        return await probe_openai_compatible(
            provider_id=provider_id,
            api_base=api_base.rstrip("/"),
            api_key=payload.api_key,
            organization=payload.organization,
        )

    return ProviderProbeResponse(
        ok=False,
        message=f"暂不支持探测该类型 Provider：`{provider_id}`。OpenAI 兼容请用 openai:chat:模型名",
        provider_id=provider_id,
        api_base=_trim(api_host) or None,
    )
