"""Mid-run progress from promptfoo JSONL stream + expected matrix size."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from app.models.schemas import EvalRunSummary, EvalStatus


def progress_jsonl_path(run_dir: Path) -> Path:
    return run_dir / "progress.jsonl"


def progress_segment_paths(run_dir: Path) -> list[Path]:
    """All progress segments in order (archived parts first, then live file)."""
    parts = sorted(run_dir.glob("progress.*.jsonl"))
    live = progress_jsonl_path(run_dir)
    if live.exists():
        parts.append(live)
    return parts


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

    stats = summarize_all_progress(run_dir)
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


def iter_progress_rows(run_dir: Path) -> list[dict[str, Any]]:
    """Load all progress JSONL rows across resume segments."""
    rows: list[dict[str, Any]] = []
    for path in progress_segment_paths(run_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def summarize_all_progress(run_dir: Path) -> dict[str, int]:
    pass_count = 0
    fail_count = 0
    error_count = 0
    for row in iter_progress_rows(run_dir):
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


def progress_rows_as_results(run_dir: Path) -> dict[str, Any] | None:
    rows = iter_progress_rows(run_dir)
    if not rows:
        return None
    return {"results": {"results": rows}}


def provider_key(provider: Any) -> str:
    if isinstance(provider, dict):
        return str(provider.get("label") or provider.get("id") or provider)
    return str(provider or "unknown")


def result_cell_key(row: dict[str, Any]) -> tuple[int, int, str]:
    prompt_idx = row.get("promptIdx")
    test_idx = row.get("testIdx")
    pi = prompt_idx if isinstance(prompt_idx, int) else 0
    ti = test_idx if isinstance(test_idx, int) else 0
    return pi, ti, provider_key(row.get("provider"))


def load_config_matrix(config_yaml: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(config_yaml.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    prompts = data.get("prompts")
    if isinstance(prompts, str):
        prompt_list = [prompts] if prompts.strip() else []
    else:
        prompt_list = _as_list(prompts)

    providers = data.get("providers")
    if providers is None:
        providers = data.get("targets")
    provider_list = _as_list(providers)

    tests = data.get("tests")
    if tests is None:
        test_list: list[Any] = [{}]
    elif isinstance(tests, str):
        test_list = [{"vars": {}, "description": tests}]
    else:
        test_list = _as_list(tests) or [{}]

    return {
        "prompts": prompt_list,
        "providers": provider_list,
        "tests": test_list,
    }


def completed_cell_keys(run_dir: Path) -> set[tuple[int, int, str]]:
    return {result_cell_key(row) for row in iter_progress_rows(run_dir)}


def remaining_test_indices(config_yaml: Path, run_dir: Path) -> list[int]:
    matrix = load_config_matrix(config_yaml)
    if not matrix:
        return []
    done = completed_cell_keys(run_dir)
    prompts = matrix["prompts"]
    providers = matrix["providers"]
    tests = matrix["tests"]
    remaining: list[int] = []
    for ti, _test in enumerate(tests):
        incomplete = False
        for pi, _prompt in enumerate(prompts):
            for provider in providers:
                if (pi, ti, provider_key(provider)) not in done:
                    incomplete = True
                    break
            if incomplete:
                break
        if incomplete:
            remaining.append(ti)
    return remaining


def archive_live_progress(run_dir: Path) -> None:
    """Move live progress.jsonl aside so a resume segment can start clean."""
    live = progress_jsonl_path(run_dir)
    if not live.exists() or live.stat().st_size == 0:
        return
    idx = 1
    while True:
        dest = run_dir / f"progress.{idx:03d}.jsonl"
        if not dest.exists():
            live.replace(dest)
            return
        idx += 1


def write_resume_test_map(run_dir: Path, original_indices: list[int]) -> None:
    path = run_dir / "resume_test_map.json"
    path.write_text(json.dumps(original_indices, ensure_ascii=False), encoding="utf-8")


def load_resume_test_map(run_dir: Path) -> list[int] | None:
    path = run_dir / "resume_test_map.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    return [int(x) for x in data]


def remap_progress_test_indices(run_dir: Path) -> None:
    """Rewrite the live progress segment so testIdx matches the full matrix."""
    mapping = load_resume_test_map(run_dir)
    if not mapping:
        return
    live = progress_jsonl_path(run_dir)
    if not live.exists():
        return
    rewritten: list[str] = []
    try:
        text = live.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            rewritten.append(raw)
            continue
        if isinstance(row, dict):
            ti = row.get("testIdx")
            if isinstance(ti, int) and 0 <= ti < len(mapping):
                row["testIdx"] = mapping[ti]
                # Keep original filtered index for debugging.
                row.setdefault("metadata", {})
                if isinstance(row["metadata"], dict):
                    row["metadata"]["evalkitResumeIdx"] = ti
            rewritten.append(json.dumps(row, ensure_ascii=False))
        else:
            rewritten.append(raw)
    live.write_text("\n".join(rewritten) + ("\n" if rewritten else ""), encoding="utf-8")
