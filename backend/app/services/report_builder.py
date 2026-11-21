from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any


_THINKING_PREFIX = re.compile(r"(?is)^\s*thinking\s*:\s*")


def split_thinking_output(raw: str) -> tuple[str, str]:
    """Split promptfoo's `Thinking: ...\\n\\nanswer` blob into (output, thinking)."""
    text = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
    stripped = text.strip()
    if not stripped or not _THINKING_PREFIX.match(stripped):
        return text, ""

    # Prefer the last block after 2+ blank lines as the final answer.
    parts = [p.strip() for p in re.split(r"\n\s*\n\s*\n+", stripped) if p.strip()]
    if len(parts) >= 2:
        final = parts[-1]
        thinking = "\n\n".join(parts[:-1])
        thinking = _THINKING_PREFIX.sub("", thinking, count=1).strip()
        return final, thinking

    # Fallback: last paragraph after a blank line.
    paras = [p.strip() for p in re.split(r"\n\s*\n+", stripped) if p.strip()]
    if len(paras) >= 2:
        final = paras[-1]
        thinking = "\n\n".join(paras[:-1])
        thinking = _THINKING_PREFIX.sub("", thinking, count=1).strip()
        # Avoid treating a trailing English meta sentence as the answer when it's
        # clearly still part of the scratchpad.
        if final.lower().startswith(("thinking:", "need ", "let's ", "we ", "i ")):
            thinking = _THINKING_PREFIX.sub("", stripped, count=1).strip()
            return "", thinking
        return final, thinking

    thinking = _THINKING_PREFIX.sub("", stripped, count=1).strip()
    return "", thinking


def summarize_results(results: dict[str, Any] | None) -> dict[str, Any]:
    if not results:
        return {
            "pass_count": 0,
            "fail_count": 0,
            "error_count": 0,
            "total_count": 0,
            "pass_rate": 0.0,
        }

    rows = _extract_rows(results)
    pass_count = 0
    fail_count = 0
    error_count = 0

    for row in rows:
        # promptfoo may put assertion failure text into `error` even for graded fails.
        if row.get("success") or row.get("pass"):
            pass_count += 1
        elif row.get("gradingResult") is not None or row.get("response") is not None:
            fail_count += 1
        else:
            error_count += 1

    total = len(rows)
    graded = pass_count + fail_count
    pass_rate = round((pass_count / graded) * 100, 2) if graded else 0.0
    return {
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "total_count": total,
        "pass_rate": pass_rate,
    }


def build_report_view(results: dict[str, Any] | None) -> dict[str, Any]:
    summary = summarize_results(results)
    if not results:
        return {
            "summary": {
                **summary,
                "pending_count": 0,
            },
            "prompts": [],
            "providers": [],
            "table": [],
            "by_provider": [],
            "by_prompt": [],
            "raw": None,
        }

    rows = _extract_rows(results)
    prompts = _as_list(results.get("results", {}).get("prompts") or results.get("prompts"))
    providers = _as_list(results.get("results", {}).get("providers") or results.get("providers"))

    table = []
    for idx, row in enumerate(rows):
        table.append(_row_to_table_item(row, idx, prompts))

    summary = _summary_from_table(table)
    return {
        "summary": summary,
        "prompts": prompts,
        "providers": providers,
        "table": table,
        "by_provider": _group_stats(table, "provider"),
        "by_prompt": _group_stats(table, "prompt"),
        "timestamp": results.get("timestamp") or results.get("createdAt"),
        "version": results.get("version"),
        "raw": results,
    }


def build_run_report_view(run_dir: Path, results: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build report for a run dir, falling back to progress JSONL and filling 未评 cells."""
    from app.services.run_progress import (  # local import to avoid cycle
        load_config_matrix,
        progress_rows_as_results,
    )

    if results is None:
        results_path = run_dir / "results.json"
        if results_path.exists():
            try:
                results = json.loads(results_path.read_text(encoding="utf-8"))
            except Exception:
                results = None
        if results is None:
            results = progress_rows_as_results(run_dir)

    view = build_report_view(results)
    config_yaml = run_dir / "promptfooconfig.full.yaml"
    if not config_yaml.exists():
        config_yaml = run_dir / "promptfooconfig.yaml"
    matrix = load_config_matrix(config_yaml)
    if not matrix:
        return view
    return _expand_table_with_pending(view, matrix)


def _row_to_table_item(row: dict[str, Any], idx: int, prompts: list[Any]) -> dict[str, Any]:
    grading = row.get("gradingResult") or {}
    provider = _provider_label(row)
    prompt = _prompt_label(row, prompts)
    raw_output = ""
    response = row.get("response")
    if isinstance(response, dict):
        raw_output = response.get("output") or response.get("text") or ""
    elif isinstance(response, str):
        raw_output = response
    else:
        raw_output = row.get("output") or ""
    if not isinstance(raw_output, str):
        raw_output = str(raw_output)
    output, thinking = split_thinking_output(raw_output)

    pending = bool(row.get("pending"))
    success = bool(row.get("success") or row.get("pass"))
    has_grade = row.get("gradingResult") is not None or row.get("response") is not None
    test_case = row.get("testCase") if isinstance(row.get("testCase"), dict) else {}
    assertions = _assertion_details(grading)
    prompt_idx = row.get("promptIdx")
    test_idx = row.get("testIdx")
    return {
        "id": idx,
        "testIdx": test_idx if isinstance(test_idx, int) else idx,
        "promptIdx": prompt_idx if isinstance(prompt_idx, int) else 0,
        "description": test_case.get("description") or row.get("description") or "",
        "provider": provider,
        "prompt": prompt,
        "vars": row.get("vars") or test_case.get("vars") or {},
        "output": output,
        "thinking": thinking,
        "success": False if pending else success,
        "pending": pending,
        "score": None if pending else row.get("score"),
        "latencyMs": None if pending else (row.get("latencyMs") or row.get("latency")),
        "cost": None if pending else row.get("cost"),
        "error": "未评" if pending else (None if (success or has_grade) else row.get("error")),
        "reason": None
        if pending
        else (
            (grading.get("reason") if isinstance(grading, dict) else None)
            or (None if success else row.get("error"))
        ),
        "assertions": [] if pending else assertions,
    }


def _summary_from_table(table: list[dict[str, Any]]) -> dict[str, Any]:
    pass_count = 0
    fail_count = 0
    error_count = 0
    pending_count = 0
    for row in table:
        if row.get("pending"):
            pending_count += 1
        elif row.get("success"):
            pass_count += 1
        elif row.get("error"):
            error_count += 1
        else:
            fail_count += 1
    graded = pass_count + fail_count
    return {
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "pending_count": pending_count,
        "total_count": len(table),
        "pass_rate": round((pass_count / graded) * 100, 2) if graded else 0.0,
    }


def _prompt_text(item: Any, index: int) -> str:
    if isinstance(item, dict):
        return str(item.get("raw") or item.get("display") or item.get("label") or f"提示词 {index + 1}")
    text = str(item or "").strip()
    return text or f"提示词 {index + 1}"


def _expand_table_with_pending(view: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any]:
    prompts = matrix["prompts"]
    providers = matrix["providers"]
    tests = matrix["tests"]
    existing = {
        (int(row.get("promptIdx") or 0), int(row.get("testIdx") or 0), str(row.get("provider") or "")): row
        for row in view.get("table") or []
    }
    table: list[dict[str, Any]] = []
    next_id = 0
    for ti, test in enumerate(tests):
        test_obj = test if isinstance(test, dict) else {}
        description = ""
        vars_obj: dict[str, Any] = {}
        if isinstance(test_obj, dict):
            description = str(test_obj.get("description") or "")
            raw_vars = test_obj.get("vars")
            if isinstance(raw_vars, dict):
                vars_obj = raw_vars
        for pi, prompt in enumerate(prompts):
            prompt_text = _prompt_text(prompt, pi)
            for provider in providers:
                from app.services.run_progress import provider_key

                prov_label = provider_key(provider)
                key = (pi, ti, prov_label)
                row = existing.get(key)
                if row:
                    row = {**row, "id": next_id, "description": row.get("description") or description}
                    table.append(row)
                else:
                    table.append(
                        {
                            "id": next_id,
                            "testIdx": ti,
                            "promptIdx": pi,
                            "description": description,
                            "provider": prov_label,
                            "prompt": prompt_text,
                            "vars": vars_obj,
                            "output": "",
                            "thinking": "",
                            "success": False,
                            "pending": True,
                            "score": None,
                            "latencyMs": None,
                            "cost": None,
                            "error": "未评",
                            "reason": None,
                            "assertions": [],
                        }
                    )
                next_id += 1

    summary = _summary_from_table(table)
    return {
        **view,
        "summary": summary,
        "table": table,
        "by_provider": _group_stats(table, "provider"),
        "by_prompt": _group_stats(table, "prompt"),
    }


def results_to_csv(results: dict[str, Any] | None) -> str:
    view = build_report_view(results)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "id",
            "provider",
            "prompt",
            "vars",
            "output",
            "thinking",
            "success",
            "score",
            "latencyMs",
            "cost",
            "error",
            "reason",
        ],
    )
    writer.writeheader()
    for row in view["table"]:
        writer.writerow(
            {
                **row,
                "vars": str(row.get("vars") or {}),
                "assertions": None,
            }
        )
    return buffer.getvalue()


def _extract_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(results.get("results"), dict):
        nested = results["results"]
        if isinstance(nested.get("results"), list):
            return [r for r in nested["results"] if isinstance(r, dict)]
        if isinstance(nested.get("outputs"), list):
            return [r for r in nested["outputs"] if isinstance(r, dict)]
    if isinstance(results.get("results"), list):
        return [r for r in results["results"] if isinstance(r, dict)]
    if isinstance(results.get("outputs"), list):
        return [r for r in results["outputs"] if isinstance(r, dict)]
    return []


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _provider_label(row: dict[str, Any]) -> str:
    provider = row.get("provider")
    if isinstance(provider, dict):
        return provider.get("label") or provider.get("id") or str(provider)
    if provider:
        return str(provider)
    return "unknown"


def _prompt_label(row: dict[str, Any], prompts: list[Any]) -> str:
    prompt = row.get("prompt")
    if isinstance(prompt, dict):
        return prompt.get("label") or prompt.get("raw") or prompt.get("display") or str(prompt)
    if isinstance(prompt, str) and prompt:
        return prompt
    idx = row.get("promptIdx")
    if isinstance(idx, int) and 0 <= idx < len(prompts):
        item = prompts[idx]
        if isinstance(item, dict):
            return item.get("raw") or item.get("display") or str(item)
        return str(item)
    return "prompt"


def _display_assert_type(assertion: Any, reason: Any = None) -> str | None:
    """Map runtime-expanded asserts back to the visual type (e.g. javascript → word-count)."""
    if not isinstance(assertion, dict):
        return None
    raw = assertion.get("type")
    if raw is None:
        return None
    label = str(raw)
    lowered = label.lower()
    value = assertion.get("value")
    value_text = value if isinstance(value, str) else ""
    reason_text = str(reason or "")
    is_char_count = (
        "evalkit:char-count" in value_text
        or "字符数" in reason_text
        or ("const n = [...text].length" in value_text and "inRange" in value_text)
    )
    if is_char_count and lowered in {"javascript", "js"}:
        # Negated word-count expands to the same javascript type; reason still says 字符数.
        return "word-count"
    return label


def _assertion_details(grading: Any) -> list[dict[str, Any]]:
    if not isinstance(grading, dict):
        return []
    components = grading.get("componentResults") or []
    details = []
    for item in components:
        if not isinstance(item, dict):
            continue
        assertion = item.get("assertion") or {}
        reason = item.get("reason")
        details.append(
            {
                "type": _display_assert_type(assertion, reason)
                if isinstance(assertion, dict)
                else None,
                "pass": item.get("pass"),
                "score": item.get("score"),
                "reason": reason,
            }
        )
    return details


def _group_stats(table: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in table:
        name = str(row.get(key) or "unknown")
        bucket = buckets.setdefault(
            name,
            {
                "name": name,
                "pass": 0,
                "fail": 0,
                "error": 0,
                "pending": 0,
                "total": 0,
                "pass_rate": 0.0,
            },
        )
        bucket["total"] += 1
        if row.get("pending"):
            bucket["pending"] += 1
        elif row.get("success"):
            bucket["pass"] += 1
        elif row.get("error"):
            bucket["error"] += 1
        else:
            bucket["fail"] += 1
    for bucket in buckets.values():
        graded = bucket["pass"] + bucket["fail"]
        bucket["pass_rate"] = round((bucket["pass"] / graded) * 100, 2) if graded else 0.0
    return sorted(buckets.values(), key=lambda b: b["name"])
