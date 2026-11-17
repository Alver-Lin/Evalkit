"""Expand EvalKit declarative asserts at run time (keep user YAML clean)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Keep in sync with frontend STRIP_THINKING_TRANSFORM.
STRIP_THINKING_TRANSFORM = (
    '(() => { const t = String(output ?? ""); if (!/^\\s*Thinking\\s*:/i.test(t)) return t; '
    "const parts = t.trim().split(/\\n\\s*\\n\\s*\\n+/).map((s) => s.trim()).filter(Boolean); "
    "if (parts.length >= 2) return parts[parts.length - 1]; "
    "const paras = t.trim().split(/\\n\\s*\\n+/).map((s) => s.trim()).filter(Boolean); "
    "return paras.length >= 2 ? paras[paras.length - 1] : t; })()"
)

CHAR_COUNT_MARKER = "/* evalkit:char-count */"


def _finite_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n


def _build_char_count_script(min_n: int | None, max_n: int | None, negated: bool) -> str:
    min_lit = "null" if min_n is None else str(min_n)
    max_lit = "null" if max_n is None else str(max_n)
    pass_expr = "!inRange" if negated else "inRange"
    return "\n".join(
        [
            CHAR_COUNT_MARKER,
            "const text = String(output ?? '').replace(/\\s/g, '');",
            "const n = [...text].length;",
            f"const min = {min_lit};",
            f"const max = {max_lit};",
            "const inRange = (min == null || n >= min) && (max == null || n <= max);",
            f"const pass = {pass_expr};",
            "if (pass) return true;",
            "const rangeLabel = min != null && max != null ? (min + '-' + max) : min != null ? ('>=' + min) : ('<=' + max);",
            "return { pass: false, score: 0, reason: '字符数 ' + n + ' 不在范围 ' + rangeLabel };",
        ]
    )


def _providers_enable_thinking(data: dict[str, Any]) -> bool:
    providers = data.get("providers") or data.get("targets")
    if not isinstance(providers, list):
        return False
    for item in providers:
        if not isinstance(item, dict):
            continue
        config = item.get("config")
        if not isinstance(config, dict):
            continue
        if config.get("showThinking") is True:
            return True
        passthrough = config.get("passthrough")
        if isinstance(passthrough, dict):
            thinking = passthrough.get("thinking")
            if isinstance(thinking, dict) and str(thinking.get("type", "")).lower() == "enabled":
                return True
            kwargs = passthrough.get("chat_template_kwargs")
            if isinstance(kwargs, dict) and kwargs.get("enable_thinking") is True:
                return True
    return False


def _expand_assert(item: Any, *, strip_thinking: bool) -> Any:
    if not isinstance(item, dict):
        return item
    raw_type = str(item.get("type") or "").strip()
    lowered = raw_type.lower()
    negated = lowered.startswith("not-")
    base = lowered[4:] if negated else lowered

    next_item = dict(item)
    if base == "word-count":
        min_n = _finite_or_none(item.get("min"))
        max_n = _finite_or_none(item.get("max"))
        value = item.get("value")
        if min_n is None and max_n is None:
            if isinstance(value, dict):
                min_n = _finite_or_none(value.get("min"))
                max_n = _finite_or_none(value.get("max"))
            else:
                n = _finite_or_none(value)
                if n is not None:
                    min_n = n
                    max_n = n
        next_item = {
            "type": "javascript",
            "value": _build_char_count_script(min_n, max_n, negated),
        }

    if strip_thinking and not next_item.get("transform"):
        next_item = {**next_item, "transform": STRIP_THINKING_TRANSFORM}
    return next_item


def _map_assert_list(raw: Any, *, strip_thinking: bool) -> list[Any] | Any:
    if not isinstance(raw, list):
        return raw
    return [_expand_assert(item, strip_thinking=strip_thinking) for item in raw]


def ensure_evalkit_asserts(yaml_path: Path) -> None:
    """Expand word-count and optionally inject Thinking strip transforms for the run copy."""
    raw = yaml_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        return

    strip_thinking = _providers_enable_thinking(data)
    next_data = dict(data)
    changed = False

    default_test = data.get("defaultTest")
    if isinstance(default_test, dict) and isinstance(default_test.get("assert"), list):
        next_asserts = _map_assert_list(default_test["assert"], strip_thinking=strip_thinking)
        if next_asserts != default_test["assert"]:
            next_data["defaultTest"] = {**default_test, "assert": next_asserts}
            changed = True

    tests = data.get("tests")
    if isinstance(tests, list):
        next_tests: list[Any] = []
        tests_changed = False
        for test in tests:
            if not isinstance(test, dict) or not isinstance(test.get("assert"), list):
                next_tests.append(test)
                continue
            next_asserts = _map_assert_list(test["assert"], strip_thinking=strip_thinking)
            if next_asserts != test["assert"]:
                next_tests.append({**test, "assert": next_asserts})
                tests_changed = True
            else:
                next_tests.append(test)
        if tests_changed:
            next_data["tests"] = next_tests
            changed = True

    if not changed:
        return

    yaml_path.write_text(
        yaml.safe_dump(
            next_data,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
    )
