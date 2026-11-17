"""Default SSE transformResponse for custom HTTP providers (run-time only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Mirrors frontend DEFAULT_SSE_TRANSFORM_RESPONSE (injected at run, not in user YAML).
DEFAULT_SSE_TRANSFORM_RESPONSE = """(json, text) => {
  const chunks = [];
  for (const line of String(text || '').split('\\n')) {
    const t = line.trim();
    if (!t.startsWith('data:')) continue;
    const raw = t.replace(/^data:\\s?/, '');
    if (!raw || raw === '[DONE]') continue;
    chunks.push(raw);
  }
  return chunks.join('\\n') || text;
}"""

SSE_TRANSFORM_MARKER = "if (!t.startsWith('data:')) continue"


def _is_default_sse_transform(raw: Any) -> bool:
    if raw is None or raw == "":
        return False
    if not isinstance(raw, str):
        return False
    # Visual field-extract transforms include this marker and must be persisted.
    if "evalkit-extract:" in raw:
        return False
    return SSE_TRANSFORM_MARKER in raw


def _provider_id(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("id") or item.get("provider") or "")
    return ""


def _is_http_provider(item: Any) -> bool:
    pid = _provider_id(item).strip().lower()
    return pid.startswith("http://") or pid.startswith("https://")


def strip_default_sse_transform_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Remove EvalKit default SSE transformResponse from HTTP providers."""
    providers = data.get("providers") or data.get("targets")
    if not isinstance(providers, list):
        return data

    changed = False
    next_providers: list[Any] = []
    for item in providers:
        if not isinstance(item, dict) or not _is_http_provider(item):
            next_providers.append(item)
            continue
        config = item.get("config")
        if not isinstance(config, dict) or not _is_default_sse_transform(config.get("transformResponse")):
            next_providers.append(item)
            continue
        next_config = {k: v for k, v in config.items() if k != "transformResponse"}
        next_item = {**item}
        if next_config:
            next_item["config"] = next_config
        else:
            next_item.pop("config", None)
        next_providers.append(next_item)
        changed = True

    if not changed:
        return data
    next_data = {**data}
    if "providers" in data:
        next_data["providers"] = next_providers
    else:
        next_data["targets"] = next_providers
    return next_data


def strip_default_sse_transform_text(yaml_content: str) -> str:
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError:
        return yaml_content
    if not isinstance(data, dict):
        return yaml_content
    cleaned = strip_default_sse_transform_mapping(data)
    if cleaned is data:
        return yaml_content
    return yaml.safe_dump(
        cleaned,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )


def ensure_http_sse_transform(yaml_path: Path) -> None:
    """Inject default SSE transformResponse for HTTP providers missing one."""
    raw = yaml_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        return

    providers = data.get("providers") or data.get("targets")
    if not isinstance(providers, list):
        return

    changed = False
    next_providers: list[Any] = []
    for item in providers:
        if not isinstance(item, dict) or not _is_http_provider(item):
            next_providers.append(item)
            continue
        config = item.get("config")
        if not isinstance(config, dict):
            config = {}
        if config.get("transformResponse") not in (None, ""):
            next_providers.append(item)
            continue
        next_providers.append(
            {
                **item,
                "config": {**config, "transformResponse": DEFAULT_SSE_TRANSFORM_RESPONSE},
            }
        )
        changed = True

    if not changed:
        return

    next_data = {**data}
    if "providers" in data:
        next_data["providers"] = next_providers
    else:
        next_data["targets"] = next_providers

    yaml_path.write_text(
        yaml.safe_dump(
            next_data,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
    )
