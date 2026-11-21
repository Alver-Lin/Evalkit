"""Mid-run progress from promptfoo JSONL stream + expected matrix size."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from app.models.schemas import EvalRunSummary, EvalStatus


def progress_jsonl_path(run_dir: Path) -> Path:
    return run_dir / "progress.jsonl"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def count_expected_results(config_yaml: Path) -> int:
    """Estimate prompt × provider × test matrix size from staged config."""
    try:
        data = yaml.safe_load(config_yaml.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0

    prompts = data.get("prompts")
    if isinstance(prompts, str):
        n_prompts = 1 if prompts.strip() else 0
    else:
        n_prompts = len(_as_list(prompts))

    providers = data.get("providers")
    if providers is None:
        providers = data.get("targets")
    n_providers = len(_as_list(providers))

    tests = data.get("tests")
    if tests is None:
        n_tests = 1
    elif isinstance(tests, str):
        n_tests = 1 if tests.strip() else 1
    else:
        n_tests = len(_as_list(tests)) or 1

    if n_prompts <= 0 or n_providers <= 0:
        return 0
    return n_prompts * n_providers * n_tests


def classify_jsonl_row(row: dict[str, Any]) -> str:
    if row.get("success") or row.get("pass"):
        return "pass"
    if row.get("gradingResult") is not None or row.get("response") is not None:
        return "fail"
    return "error"


def summarize_jsonl(path: Path) -> dict[str, int]:
    pass_count = 0
    fail_count = 0
    error_count = 0
    if not path.exists():
        return {
            "pass_count": 0,
            "fail_count": 0,
            "error_count": 0,
            "completed_count": 0,
        }
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {
            "pass_count": 0,
            "fail_count": 0,
            "error_count": 0,
            "completed_count": 0,
        }

    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            # Partial last line while writer is flushing — skip.
            continue
        if not isinstance(row, dict):
            continue
        kind = classify_jsonl_row(row)
        if kind == "pass":
            pass_count += 1
        elif kind == "fail":
            fail_count += 1
        else:
            error_count += 1

    return {
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "completed_count": pass_count + fail_count + error_count,
    }


def apply_progress_to_summary(summary: EvalRunSummary, run_dir: Path) -> bool:
    """
    Update in-flight summary counts from progress.jsonl.
    Returns True when meta changed.
    """
    if summary.status not in {EvalStatus.pending, EvalStatus.running}:
        return False

    stats = summarize_jsonl(progress_jsonl_path(run_dir))
    changed = False
    for key in ("pass_count", "fail_count", "error_count", "completed_count"):
        value = int(stats.get(key) or 0)
        if getattr(summary, key) != value:
            setattr(summary, key, value)
            changed = True

    graded = summary.pass_count + summary.fail_count
    pass_rate = round((summary.pass_count / graded) * 100, 2) if graded else 0.0
    if summary.pass_rate != pass_rate:
        summary.pass_rate = pass_rate
        changed = True
    return changed
