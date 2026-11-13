from __future__ import annotations

import csv
import io
from typing import Any


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
            "summary": summary,
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
        grading = row.get("gradingResult") or {}
        provider = _provider_label(row)
        prompt = _prompt_label(row, prompts)
        output = ""
        response = row.get("response")
        if isinstance(response, dict):
            output = response.get("output") or response.get("text") or ""
        elif isinstance(response, str):
            output = response
        else:
            output = row.get("output") or ""

        success = bool(row.get("success") or row.get("pass"))
        has_grade = row.get("gradingResult") is not None or row.get("response") is not None
        test_case = row.get("testCase") if isinstance(row.get("testCase"), dict) else {}
        assertions = _assertion_details(grading)
        prompt_idx = row.get("promptIdx")
        test_idx = row.get("testIdx")
        table.append(
            {
                "id": idx,
                "testIdx": test_idx if isinstance(test_idx, int) else idx,
                "promptIdx": prompt_idx if isinstance(prompt_idx, int) else 0,
                "description": test_case.get("description") or "",
                "provider": provider,
                "prompt": prompt,
                "vars": row.get("vars") or test_case.get("vars") or {},
                "output": output,
                "success": success,
                "score": row.get("score"),
                "latencyMs": row.get("latencyMs") or row.get("latency"),
                "cost": row.get("cost"),
                "error": None if (success or has_grade) else row.get("error"),
                "reason": (grading.get("reason") if isinstance(grading, dict) else None)
                or (None if success else row.get("error")),
                "assertions": assertions,
            }
        )

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


def _assertion_details(grading: Any) -> list[dict[str, Any]]:
    if not isinstance(grading, dict):
        return []
    components = grading.get("componentResults") or []
    details = []
    for item in components:
        if not isinstance(item, dict):
            continue
        assertion = item.get("assertion") or {}
        details.append(
            {
                "type": assertion.get("type") if isinstance(assertion, dict) else None,
                "pass": item.get("pass"),
                "score": item.get("score"),
                "reason": item.get("reason"),
            }
        )
    return details


def _group_stats(table: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in table:
        name = str(row.get(key) or "unknown")
        bucket = buckets.setdefault(
            name,
            {"name": name, "pass": 0, "fail": 0, "error": 0, "total": 0, "pass_rate": 0.0},
        )
        bucket["total"] += 1
        if row.get("success"):
            bucket["pass"] += 1
        elif row.get("error"):
            bucket["error"] += 1
        else:
            bucket["fail"] += 1
    for bucket in buckets.values():
        graded = bucket["pass"] + bucket["fail"]
        bucket["pass_rate"] = round((bucket["pass"] / graded) * 100, 2) if graded else 0.0
    return sorted(buckets.values(), key=lambda b: b["name"])
