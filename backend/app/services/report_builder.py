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
    """Export a CSV from raw promptfoo results or an EvalKit report view/table."""
    if isinstance(results, dict) and isinstance(results.get("table"), list):
        table = results["table"]
    else:
        table = build_report_view(results).get("table") or []
    return table_to_csv(table)


_CSV_ASSERT_LABELS: dict[str, str] = {
    "similar": "语义相似",
    "llm-rubric": "模型评分",
    "contains": "包含",
    "icontains": "包含忽略大小写",
    "equals": "完全相等",
    "starts-with": "以…开头",
    "contains-all": "包含全部",
    "contains-any": "包含任一项",
    "icontains-all": "包含全部忽略大小写",
    "icontains-any": "包含任一项忽略大小写",
    "word-count": "字符数",
    "javascript": "脚本断言",
    "js": "脚本断言",
}


def _csv_assert_label(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return "断言"
    lowered = text.lower()
    negated = lowered.startswith("not-")
    base = text[4:] if negated else text
    label = _CSV_ASSERT_LABELS.get(base.lower(), base)
    return f"非{label}" if negated else label


def _csv_format_input(vars_obj: Any) -> str:
    if not isinstance(vars_obj, dict) or not vars_obj:
        return "—"
    keys = [str(k) for k in vars_obj.keys()]
    width = min(max((len(k) for k in keys), default=0), 18)
    lines: list[str] = []
    for key, value in vars_obj.items():
        label = str(key)
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False)
        elif value is None or value == "":
            rendered = "—"
        else:
            rendered = str(value).replace("\r\n", "\n").strip() or "—"
        # Keep multi-line values indented under the key.
        if "\n" in rendered:
            first, *rest = rendered.split("\n")
            pad = " " * (width + 3)
            body = "\n".join([first] + [pad + line for line in rest])
            lines.append(f"{label.ljust(width)} : {body}")
        else:
            lines.append(f"{label.ljust(width)} : {rendered}")
    return "\n".join(lines)


def _csv_result_badge(row: dict[str, Any]) -> str:
    """Mirror ReportView resultBadge()."""
    if row.get("pending"):
        return "未评"
    asserts = [a for a in (row.get("assertions") or []) if isinstance(a, dict)]
    err_text = str(row.get("error") or "").strip()
    has_error = bool(err_text) and err_text not in {"未评", "未执行", "未测评"}
    if asserts:
        passed = sum(1 for a in asserts if a.get("pass"))
        if has_error:
            return f"{len(asserts)} ERROR"
        if row.get("success"):
            return f"{passed} PASS"
        return f"{len(asserts) - passed} FAIL"
    if has_error:
        return "ERROR"
    if row.get("success"):
        return "PASS"
    return "FAIL"


def _csv_format_result(row: dict[str, Any]) -> str:
    if row.get("pending"):
        return "未评"
    badge = _csv_result_badge(row)
    meta: list[str] = []
    latency = row.get("latencyMs")
    try:
        if latency is not None and str(latency) != "":
            meta.append(f"耗时 {int(round(float(latency)))} ms")
    except (TypeError, ValueError):
        pass
    score = row.get("score")
    if score is not None and str(score) != "":
        meta.append(f"得分 {score}")
    if not meta:
        return badge
    return f"{badge}\n" + " · ".join(meta)


def _csv_format_asserts(row: dict[str, Any]) -> str:
    if row.get("pending"):
        return "未评"
    asserts = row.get("assertions") or []
    if not asserts:
        reason = row.get("reason") or row.get("error") or ""
        return str(reason) if reason and str(reason) not in {"未评", "未执行", "未测评"} else "—"
    blocks: list[str] = []
    for idx, item in enumerate(asserts, start=1):
        if not isinstance(item, dict):
            continue
        ok = bool(item.get("pass"))
        label = _csv_assert_label(item.get("type"))
        metric = str(item.get("metric") or "").strip()
        if metric:
            label = f"{label}·{metric}"
        mark = "✓ 通过" if ok else "✗ 失败"
        reason = str(item.get("reason") or ("通过" if ok else "未通过")).strip()
        blocks.append(f"{idx}. [{mark}] {label}\n   {reason}")
    return "\n\n".join(blocks) if blocks else "—"


def _export_rows(table: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in table:
        pending = bool(row.get("pending"))
        rows.append(
            {
                "测试项": str(row.get("description") or "—"),
                "输入": _csv_format_input(row.get("vars")),
                "测评结果": _csv_format_result(row),
                "输出": "未评" if pending else (str(row.get("output") or "").strip() or "—"),
                "断言": _csv_format_asserts(row),
            }
        )
    return rows


def table_to_csv(table: list[dict[str, Any]]) -> str:
    """Export columns matching the report UI: 测试项 / 输入 / 测评结果 / 输出 / 断言."""
    buffer = io.StringIO()
    fieldnames = ["测试项", "输入", "测评结果", "输出", "断言"]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in _export_rows(table):
        writer.writerow(row)
    return buffer.getvalue()


def table_to_xlsx(
    table: list[dict[str, Any]],
    *,
    summary: Any | None = None,
    view: dict[str, Any] | None = None,
) -> bytes:
    """
    Two-sheet workbook:
    - 概览: task meta + result distribution + provider pass rates
    - 详细结果: per-case columns
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    header_fill = PatternFill("solid", fgColor="0F766E")
    header_font = Font(name="Microsoft YaHei", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Microsoft YaHei", size=14, bold=True, color="0F766E")
    section_font = Font(name="Microsoft YaHei", size=11, bold=True, color="111827")
    label_font = Font(name="Microsoft YaHei", size=10, color="6B7280")
    body_font = Font(name="Microsoft YaHei", size=10, color="111827")
    mute_font = Font(name="Microsoft YaHei", size=10, color="6B7280")
    pass_font = Font(name="Microsoft YaHei", size=10, bold=True, color="15803D")
    fail_font = Font(name="Microsoft YaHei", size=10, bold=True, color="B91C1C")
    pending_font = Font(name="Microsoft YaHei", size=10, bold=True, color="A16207")
    value_font = Font(name="Microsoft YaHei", size=10, bold=True, color="111827")
    pass_fill = PatternFill("solid", fgColor="F0FDF4")
    fail_fill = PatternFill("solid", fgColor="FEF2F2")
    pending_fill = PatternFill("solid", fgColor="FFFBEB")
    zebra_fill = PatternFill("solid", fgColor="F8FAFC")
    card_fill = PatternFill("solid", fgColor="F0FDFA")
    thin = Border(
        left=Side(style="thin", color="E5E7EB"),
        right=Side(style="thin", color="E5E7EB"),
        top=Side(style="thin", color="E5E7EB"),
        bottom=Side(style="thin", color="E5E7EB"),
    )
    top_wrap = Alignment(vertical="top", wrap_text=True, horizontal="left")
    center = Alignment(vertical="center", horizontal="center", wrap_text=True)

    def _status_label(status: Any) -> str:
        raw = getattr(status, "value", status)
        text = str(raw or "").strip()
        if "." in text and text.lower().startswith("evalstatus."):
            text = text.split(".", 1)[-1]
        return {
            "pending": "等待中",
            "running": "运行中",
            "succeeded": "成功",
            "failed": "失败",
            "cancelled": "已暂停",
        }.get(text, text or "—")

    def _fmt_dt(value: Any) -> str:
        if value is None:
            return "—"
        if hasattr(value, "strftime"):
            try:
                return value.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        text = str(value).strip()
        if not text:
            return "—"
        if "T" in text:
            text = text.replace("T", " ").replace("Z", "")
            if "." in text:
                text = text.split(".", 1)[0]
        return text[:19]

    def _fmt_duration(ms: Any) -> str:
        try:
            n = float(ms)
        except (TypeError, ValueError):
            return "—"
        if n <= 0:
            return "—"
        return f"{n / 1000:.1f}s"

    # ----- Sheet 1: 概览 -----
    overview = wb.active
    overview.title = "概览"
    overview.column_dimensions["A"].width = 16
    overview.column_dimensions["B"].width = 42
    overview.column_dimensions["C"].width = 14
    overview.column_dimensions["D"].width = 14
    overview.column_dimensions["E"].width = 14

    stats = (view or {}).get("summary") or {}
    pass_count = int(stats.get("pass_count") if stats.get("pass_count") is not None else getattr(summary, "pass_count", 0) or 0)
    fail_count = int(stats.get("fail_count") if stats.get("fail_count") is not None else getattr(summary, "fail_count", 0) or 0)
    error_count = int(stats.get("error_count") if stats.get("error_count") is not None else getattr(summary, "error_count", 0) or 0)
    pending_count = int(stats.get("pending_count") or 0)
    total_count = int(
        stats.get("total_count")
        if stats.get("total_count") is not None
        else getattr(summary, "total_count", 0) or (pass_count + fail_count + error_count + pending_count)
    )
    graded = pass_count + fail_count
    pass_rate = float(
        stats.get("pass_rate")
        if stats.get("pass_rate") is not None
        else getattr(summary, "pass_rate", 0) or 0
    )
    if graded and not pass_rate:
        pass_rate = round((pass_count / graded) * 100, 2)

    task_name = getattr(summary, "config_name", None) or "未命名任务"
    overview["A1"] = "EvalKit 测评报告"
    overview["A1"].font = title_font
    overview.merge_cells("A1:B1")
    overview.row_dimensions[1].height = 28

    overview["A2"] = "任务名称"
    overview["B2"] = task_name
    overview["A3"] = "运行状态"
    overview["B3"] = _status_label(str(getattr(summary, "status", "") or ""))
    overview["A4"] = "通过率"
    overview["B4"] = f"{pass_rate:.2f}%"
    overview["A5"] = "结果统计"
    overview["B5"] = f"{pass_count} 通过 / {fail_count} 失败 / {pending_count} 未评 / {error_count} 错误"
    overview["A6"] = "完成进度"
    overview["B6"] = f"{pass_count + fail_count + error_count}/{total_count or '—'}"
    overview["A7"] = "耗时"
    overview["B7"] = _fmt_duration(getattr(summary, "duration_ms", None))
    overview["A8"] = "创建时间"
    overview["B8"] = _fmt_dt(getattr(summary, "created_at", None))
    overview["A9"] = "运行 ID"
    overview["B9"] = getattr(summary, "id", None) or "—"

    for r in range(2, 10):
        overview.cell(row=r, column=1).font = label_font
        overview.cell(row=r, column=1).fill = card_fill
        overview.cell(row=r, column=1).border = thin
        overview.cell(row=r, column=1).alignment = Alignment(vertical="center")
        overview.cell(row=r, column=2).font = value_font if r != 9 else mute_font
        overview.cell(row=r, column=2).border = thin
        overview.cell(row=r, column=2).alignment = Alignment(vertical="center", wrap_text=True)
        overview.row_dimensions[r].height = 22

    # Result distribution table (donut chart equivalent)
    overview["A11"] = "结果分布"
    overview["A11"].font = section_font
    overview.merge_cells("A11:C11")

    dist_headers = ["结果", "数量", "占比"]
    for col, title in enumerate(dist_headers, start=1):
        cell = overview.cell(row=12, column=col, value=title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center
        cell.border = thin

    dist_rows = [
        ("通过", pass_count, pass_fill, pass_font),
        ("失败", fail_count, fail_fill, fail_font),
        ("未评", pending_count, pending_fill, pending_font),
        ("错误", error_count, fail_fill, fail_font),
    ]
    for offset, (name, count, fill, font) in enumerate(dist_rows):
        r = 13 + offset
        pct = round((count / total_count) * 100, 1) if total_count else 0.0
        values = [name, count, f"{pct}%"]
        for col, value in enumerate(values, start=1):
            cell = overview.cell(row=r, column=col, value=value)
            cell.border = thin
            cell.alignment = center
            cell.font = font if col == 1 else body_font
            cell.fill = fill
        overview.row_dimensions[r].height = 20

    overview.cell(row=17, column=1, value="合计").font = value_font
    overview.cell(row=17, column=2, value=total_count).font = value_font
    overview.cell(row=17, column=3, value="100%" if total_count else "—").font = value_font
    for col in range(1, 4):
        overview.cell(row=17, column=col).border = thin
        overview.cell(row=17, column=col).alignment = center
        overview.cell(row=17, column=col).fill = zebra_fill

    # Assertion metrics (replaces provider pass-rate chart)
    overview["A19"] = "断言指标"
    overview["A19"].font = section_font
    overview.merge_cells("A19:E19")

    assert_headers = ["断言", "通过", "失败", "合计", "细则"]
    for col, title in enumerate(assert_headers, start=1):
        cell = overview.cell(row=20, column=col, value=title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center
        cell.border = thin
    overview.column_dimensions["E"].width = 48

    assert_items = assert_metric_buckets(table)
    if not assert_items:
        cell = overview.cell(row=21, column=1, value="暂无断言数据")
        cell.font = mute_font
        overview.merge_cells("A21:E21")
    else:
        for offset, item in enumerate(assert_items):
            r = 21 + offset
            pass_n = int(item.get("pass") or 0)
            fail_n = int(item.get("fail") or 0)
            values = [
                item.get("label") or "—",
                pass_n,
                fail_n,
                pass_n + fail_n,
                item.get("rule") or "—",
            ]
            for col, value in enumerate(values, start=1):
                cell = overview.cell(row=r, column=col, value=value)
                cell.border = thin
                cell.alignment = (
                    Alignment(vertical="top", wrap_text=True)
                    if col in {1, 5}
                    else center
                )
                if col == 2:
                    cell.font = pass_font
                    cell.fill = pass_fill
                elif col == 3:
                    cell.font = fail_font
                    cell.fill = fail_fill
                else:
                    cell.font = body_font
                    if r % 2 == 1:
                        cell.fill = zebra_fill
            overview.row_dimensions[r].height = 36

    note_row = 22 + max(len(assert_items), 1)
    overview.cell(
        row=note_row,
        column=1,
        value="说明：概览含结果分布与断言指标；用例明细见「详细结果」工作表。",
    )
    overview.cell(row=note_row, column=1).font = mute_font
    overview.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=5)

    # ----- Sheet 2: 详细结果 -----
    ws = wb.create_sheet("详细结果")
    headers = ["测试项", "输入", "测评结果", "输出", "断言"]
    widths = [28, 34, 18, 46, 46]

    for col_idx, (title, width) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=1, column=col_idx, value=title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center
        cell.border = thin
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:E{max(1, len(table) + 1)}"

    for row_idx, data in enumerate(_export_rows(table), start=2):
        values = [data[h] for h in headers]
        result_text = values[2]
        if "未评" in result_text:
            result_font, result_fill = pending_font, pending_fill
        elif "PASS" in result_text and "FAIL" not in result_text and "ERROR" not in result_text:
            result_font, result_fill = pass_font, pass_fill
        elif "FAIL" in result_text or "ERROR" in result_text:
            result_font, result_fill = fail_font, fail_fill
        else:
            result_font, result_fill = body_font, None

        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = top_wrap
            cell.border = thin
            cell.font = body_font
            if row_idx % 2 == 0:
                cell.fill = zebra_fill
            if col_idx == 3:
                cell.font = result_font
                if result_fill is not None:
                    cell.fill = result_fill
            elif col_idx == 5:
                if "✗ 失败" in str(value) and "✓ 通过" not in str(value):
                    cell.font = fail_font
                elif value == "未评":
                    cell.font = mute_font
            elif value in {"—", "未评"}:
                cell.font = mute_font

        line_counts = [str(v).count("\n") + 1 for v in values]
        approx = min(max(max(line_counts) * 15, 36), 140)
        ws.row_dimensions[row_idx].height = approx

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


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


def _is_char_count_assert(assertion: dict[str, Any], reason: Any = None) -> bool:
    value = assertion.get("value")
    value_text = value if isinstance(value, str) else ""
    reason_text = str(reason or "")
    return (
        "evalkit:char-count" in value_text
        or "字符数" in reason_text
        or ("const n = [...text].length" in value_text and "inRange" in value_text)
    )


def _display_assert_type(assertion: Any, reason: Any = None) -> str | None:
    """Map runtime-expanded asserts back to the visual type (e.g. javascript → word-count)."""
    if not isinstance(assertion, dict):
        return None
    raw = assertion.get("type")
    if raw is None:
        return None
    label = str(raw)
    lowered = label.lower()
    if _is_char_count_assert(assertion, reason) and lowered in {"javascript", "js"}:
        # Negated word-count expands to the same javascript type; reason still says 字符数.
        return "word-count"
    return label


def _assert_rule_text(assertion: Any, display_type: str | None, reason: Any = None) -> str | None:
    """Human-readable assertion rule / rubric for hover tooltips."""
    if not isinstance(assertion, dict):
        return None
    value = assertion.get("value")
    threshold = assertion.get("threshold")
    lowered = str(display_type or assertion.get("type") or "").lower()

    if lowered == "word-count" or (
        isinstance(value, str) and _is_char_count_assert(assertion, reason)
    ):
        value_text = value if isinstance(value, str) else ""
        min_m = re.search(r"const\s+min\s*=\s*([^;]+);", value_text)
        max_m = re.search(r"const\s+max\s*=\s*([^;]+);", value_text)
        min_v = (min_m.group(1).strip() if min_m else "").replace("null", "")
        max_v = (max_m.group(1).strip() if max_m else "").replace("null", "")
        if min_v and max_v:
            return f"字符数要求：{min_v}–{max_v}"
        if min_v:
            return f"字符数要求：不少于 {min_v}"
        if max_v:
            return f"字符数要求：不超过 {max_v}"
        return "字符数要求：见评分配置"

    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            text = str(value)
    elif value is None:
        text = ""
    else:
        text = str(value).strip()

    # Skip raw JS bodies that aren't char-count (not useful as 细则).
    if lowered in {"javascript", "js"} and text and "evalkit:char-count" not in text:
        if "function" in text or "const " in text or "return " in text:
            return None

    if not text:
        if threshold is not None:
            return f"阈值：{threshold}"
        return None

    if threshold is not None and lowered in {"llm-rubric", "similar"}:
        return f"{text}\n\n阈值：{threshold}"
    return text


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
        display_type = (
            _display_assert_type(assertion, reason) if isinstance(assertion, dict) else None
        )
        metric = None
        if isinstance(assertion, dict):
            raw_metric = assertion.get("metric")
            if raw_metric is not None and str(raw_metric).strip():
                metric = str(raw_metric).strip()
        details.append(
            {
                "type": display_type,
                "pass": item.get("pass"),
                "score": item.get("score"),
                "reason": reason,
                "value": _assert_rule_text(assertion, display_type, reason)
                if isinstance(assertion, dict)
                else None,
                "metric": metric,
            }
        )
    return details


def assert_metric_buckets(table: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate assertion pass/fail.

    Prefer `metric` (评分项) as the chart category when present; otherwise fall
    back to assertion type so legacy runs still group.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for row in table:
        if row.get("pending"):
            continue
        for item in row.get("assertions") or []:
            if not isinstance(item, dict):
                continue
            metric = str(item.get("metric") or "").strip()
            type_key = str(item.get("type") or "unknown")
            # Group key: scoring-item title when set, else assertion type.
            bucket_key = f"metric::{metric}" if metric else f"type::{type_key}"
            label = metric or _csv_assert_label(item.get("type"))
            rule = str(item.get("value") or "").strip()
            bucket = buckets.setdefault(
                bucket_key,
                {
                    "key": bucket_key,
                    "type": item.get("type"),
                    "label": label,
                    "pass": 0,
                    "fail": 0,
                    "rules": {},
                },
            )
            if item.get("pass"):
                bucket["pass"] += 1
            else:
                bucket["fail"] += 1
            if rule:
                rules: dict[str, dict[str, Any]] = bucket["rules"]
                rs = rules.setdefault(rule, {"rule": rule, "pass": 0, "fail": 0})
                if item.get("pass"):
                    rs["pass"] += 1
                else:
                    rs["fail"] += 1
    items: list[dict[str, Any]] = []
    for bucket in buckets.values():
        rules_map: dict[str, dict[str, Any]] = bucket.pop("rules") or {}
        bucket["rules"] = sorted(
            rules_map.values(),
            key=lambda r: -(int(r["pass"]) + int(r["fail"])),
        )
        # Keep a short preview rule for HTML title / Excel cell.
        top = bucket["rules"][0]["rule"] if bucket["rules"] else ""
        bucket["rule"] = top
        items.append(bucket)
    return sorted(
        items,
        key=lambda b: (-(int(b["pass"]) + int(b["fail"])), str(b["label"])),
    )


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
