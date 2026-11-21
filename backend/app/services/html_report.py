"""EvalKit-styled standalone HTML report (matrix table matching ReportView)."""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from app.models.schemas import EvalRunSummary

_ASSERT_LABELS: dict[str, str] = {
    "similar": "语义相似",
    "llm-rubric": "模型评分标准",
    "contains": "包含",
    "icontains": "包含忽略大小写",
    "equals": "完全相等",
    "starts-with": "以…开头",
    "contains-all": "包含全部",
    "contains-any": "包含任一项",
    "icontains-all": "包含全部忽略大小写",
    "icontains-any": "包含任一项忽略大小写",
    "word-count": "字符数",
    "is-json": "是否为 JSON",
    "contains-json": "包含 JSON",
    "is-xml": "是否为 XML",
    "contains-xml": "包含 XML",
    "is-html": "是否为 HTML",
    "contains-html": "包含 HTML",
    "is-sql": "是否为 SQL",
    "contains-sql": "包含 SQL",
    "is-refusal": "是否拒答",
    "finish-reason": "结束原因",
    "cost": "单次成本阈值",
    "latency": "耗时阈值",
    "javascript": "脚本断言",
}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _assert_label(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return "断言"
    lowered = text.lower()
    negated = lowered.startswith("not-")
    base = text[4:] if negated else text
    label = _ASSERT_LABELS.get(base.lower(), base)
    return f"非{label}" if negated else label


def _status_label(status: str) -> str:
    return {
        "pending": "等待中",
        "running": "运行中",
        "succeeded": "成功",
        "failed": "失败",
    }.get(status, status)


def _short_prompt(text: str, index: int, max_len: int = 96) -> str:
    one_line = " ".join(str(text or "").split())
    if not one_line:
        return f"提示词 {index + 1}"
    return f"{one_line[:max_len]}..." if len(one_line) > max_len else one_line


def _input_preview(vars_obj: Any) -> str:
    if not isinstance(vars_obj, dict) or not vars_obj:
        return "—"
    entries = list(vars_obj.items())
    if len(entries) == 1:
        return "" if entries[0][1] is None else str(entries[0][1])
    lines: list[str] = []
    for key, value in entries:
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = "—" if value is None else str(value)
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines)


def _fmt_ms(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return ""
    return f"Latency: {int(round(n))}ms"


def _result_badge(row: dict[str, Any]) -> tuple[str, str]:
    """Return (css_tone, badge_text)."""
    asserts = row.get("assertions") or []
    err = bool(row.get("error"))
    success = bool(row.get("success"))
    if asserts:
        passed = sum(1 for a in asserts if a.get("pass"))
        if err:
            return "error", f"{len(asserts)} ERROR"
        if success:
            return "pass", f"{passed} PASS"
        return "fail", f"{len(asserts) - passed} FAIL"
    if err:
        return "error", "ERROR"
    if success:
        return "pass", "PASS"
    return "fail", "FAIL"


def _col_key(row: dict[str, Any]) -> str:
    return f"{row.get('promptIdx') or 0}::{row.get('provider') or ''}::{row.get('prompt') or ''}"


def _test_key(row: dict[str, Any]) -> str:
    return f"{row.get('testIdx', row.get('id'))}::{json.dumps(row.get('vars') or {}, ensure_ascii=False, sort_keys=True)}"


def _build_matrix(table: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    columns: dict[str, dict[str, Any]] = {}
    prompt_order: list[str] = []
    for row in table:
        key = _col_key(row)
        col = columns.get(key)
        if not col:
            prompt = str(row.get("prompt") or "")
            if prompt not in prompt_order:
                prompt_order.append(prompt)
            col = {
                "key": key,
                "prompt": prompt,
                "prompt_label": _short_prompt(prompt, prompt_order.index(prompt), 120),
                "provider": str(row.get("provider") or "unknown"),
                "pass": 0,
                "fail": 0,
                "error": 0,
                "total": 0,
                "pass_rate": 0.0,
            }
            columns[key] = col
        col["total"] += 1
        if row.get("error"):
            col["error"] += 1
        elif row.get("success"):
            col["pass"] += 1
        else:
            col["fail"] += 1

    for col in columns.values():
        graded = col["pass"] + col["fail"]
        col["pass_rate"] = round((col["pass"] / graded) * 100, 2) if graded else 0.0

    rows_map: dict[str, dict[str, Any]] = {}
    for row in table:
        key = _test_key(row)
        item = rows_map.get(key)
        if not item:
            test_idx = row.get("testIdx")
            if not isinstance(test_idx, int):
                test_idx = int(row.get("id") or 0)
            item = {
                "key": key,
                "test_idx": test_idx,
                "description": row.get("description") or f"测试 {test_idx + 1}",
                "vars": row.get("vars") or {},
                "cells": {},
            }
            rows_map[key] = item
        item["cells"][_col_key(row)] = row

    matrix_rows = sorted(rows_map.values(), key=lambda r: r["test_idx"])
    return list(columns.values()), matrix_rows


def _render_result_cell(row: dict[str, Any] | None) -> str:
    if not row:
        return '<span class="muted">—</span>'
    tone, badge = _result_badge(row)
    latency = _fmt_ms(row.get("latencyMs"))
    score = row.get("score")
    meta_bits: list[str] = []
    if latency:
        meta_bits.append(_esc(latency))
    if score is not None:
        meta_bits.append(f"Score: {_esc(score)}")
    output = row.get("output") or row.get("error") or row.get("reason") or "—"
    thinking = row.get("thinking") or ""
    asserts = row.get("assertions") or []
    assert_html = []
    for a in asserts:
        a_ok = bool(a.get("pass"))
        assert_html.append(
            f"<div class='assert {'ok' if a_ok else 'fail'}'>"
            f"<strong>{_esc(_assert_label(a.get('type')))}</strong>"
            f"<span>{_esc(a.get('reason') or ('通过' if a_ok else '未通过'))}</span>"
            f"</div>"
        )
    detail_block = ""
    if assert_html or thinking:
        parts = []
        if thinking:
            parts.append(f"<h5>Thinking</h5><pre>{_esc(thinking)}</pre>")
        if assert_html:
            parts.append(f"<h5>断言</h5>{''.join(assert_html)}")
        detail_block = (
            "<details class='cell-detail'>"
            "<summary>详情</summary>"
            f"<div class='cell-detail-body'>{''.join(parts)}</div>"
            "</details>"
        )
    return f"""
      <div class="result-card" data-tone="{tone}">
        <div class="result-top">
          <span class="result-badge {tone}">{_esc(badge)}</span>
          {detail_block or '<span class="detail-spacer"></span>'}
        </div>
        <div class="result-output">{_esc(output)}</div>
        <div class="result-meta mono">{' · '.join(meta_bits)}</div>
      </div>
    """


def build_evalkit_html_report(summary: EvalRunSummary, view: dict[str, Any]) -> str:
    stats = view.get("summary") or {}
    table = view.get("table") or []
    by_provider = view.get("by_provider") or []
    pass_count = int(stats.get("pass_count") or summary.pass_count or 0)
    fail_count = int(stats.get("fail_count") or summary.fail_count or 0)
    error_count = int(stats.get("error_count") or summary.error_count or 0)
    total = int(stats.get("total_count") or summary.total_count or (pass_count + fail_count + error_count))
    pass_rate = float(stats.get("pass_rate") if stats.get("pass_rate") is not None else summary.pass_rate or 0)
    graded = pass_count + fail_count
    fail_rate = round((fail_count / graded) * 100, 1) if graded else 0.0
    error_rate = round((error_count / total) * 100, 1) if total else 0.0
    duration = f"{summary.duration_ms / 1000:.1f}s" if summary.duration_ms else ""
    created = (
        summary.created_at.astimezone().strftime("%Y-%m-%d %H:%M:%S") if summary.created_at else ""
    )
    status_value = getattr(summary.status, "value", str(summary.status))

    p1 = pass_rate if graded else 0
    p2 = p1 + fail_rate if graded else 0
    donut = (
        f"conic-gradient(#0f766e 0 {p1}%, #dc2626 {p1}% {p2}%, #94a3b8 {p2}% 100%)"
        if total
        else "#e5e7eb"
    )

    provider_bars = []
    for item in by_provider:
        name = str(item.get("name") or "unknown")
        rate = float(item.get("pass_rate") or 0)
        provider_bars.append(
            f"""
            <div class="bar-row">
              <div class="bar-label" title="{_esc(name)}">{_esc(name)}</div>
              <div class="bar-track"><div class="bar-fill" style="width:{rate:.2f}%"></div></div>
              <div class="bar-pct mono">{rate:.2f}%</div>
            </div>
            """
        )
    if not provider_bars:
        provider_bars.append('<div class="empty">暂无供应商数据</div>')

    matrix_cols, matrix_rows = _build_matrix(table)

    provider_options = sorted({c["provider"] for c in matrix_cols})
    prompt_options = []
    seen_prompts: set[str] = set()
    for c in matrix_cols:
        if c["prompt"] in seen_prompts:
            continue
        seen_prompts.add(c["prompt"])
        prompt_options.append((c["prompt"], _short_prompt(c["prompt"], len(prompt_options), 48)))

    thead_cells = [
        '<th class="col-desc">测试项</th>',
        '<th class="col-input">输入</th>',
    ]
    for col in matrix_cols:
        rate_cls = "ok" if col["pass_rate"] >= 80 else ("bad" if col["pass_rate"] < 50 else "")
        thead_cells.append(
            f"""
            <th class="col-result" data-col="{_esc(col['key'])}" data-provider="{_esc(col['provider'])}" data-prompt="{_esc(col['prompt'])}">
              <div class="col-head">
                <div class="col-provider">{_esc(col['provider'])}</div>
                <div class="col-prompt" title="{_esc(col['prompt'])}">{_esc(col['prompt_label'])}</div>
                <div class="col-rate mono {rate_cls}">{col['pass_rate']:.2f}% pass ({col['pass']}/{col['total']})</div>
              </div>
            </th>
            """
        )

    body_rows: list[str] = []
    for row in matrix_rows:
        cells_html = [
            f'<td class="col-desc"><div class="case-title">{_esc(row["description"])}</div></td>',
            f'<td class="col-input"><div class="vars-cell mono">{_esc(_input_preview(row["vars"]))}</div></td>',
        ]
        tones: list[str] = []
        search_bits = [str(row["description"]), _input_preview(row["vars"])]
        for col in matrix_cols:
            cell = row["cells"].get(col["key"])
            if cell:
                tone, _ = _result_badge(cell)
                tones.append(tone)
                search_bits.append(str(cell.get("output") or ""))
                search_bits.append(str(cell.get("error") or ""))
            cells_html.append(
                f'<td class="col-result" data-col="{_esc(col["key"])}" data-provider="{_esc(col["provider"])}" data-prompt="{_esc(col["prompt"])}">'
                f"{_render_result_cell(cell)}</td>"
            )
        # Aggregate tone for filtering: prefer fail/error if any
        if "error" in tones:
            row_tone = "error"
        elif "fail" in tones:
            row_tone = "fail"
        elif "pass" in tones:
            row_tone = "pass"
        else:
            row_tone = "empty"
        search_blob = _esc(" ".join(search_bits).lower())
        body_rows.append(
            f'<tr class="matrix-row" data-tone="{row_tone}" data-search="{search_blob}">'
            f'{"".join(cells_html)}</tr>'
        )

    if not body_rows:
        colspan = 2 + max(len(matrix_cols), 1)
        body_rows.append(f'<tr><td colspan="{colspan}" class="empty">暂无详细结果</td></tr>')

    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    title = summary.config_name or "EvalKit 测评报告"
    provider_opts_html = "".join(
        f'<option value="{_esc(p)}">{_esc(p)}</option>' for p in provider_options
    )
    prompt_opts_html = "".join(
        f'<option value="{_esc(full)}">{_esc(label)}</option>' for full, label in prompt_options
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_esc(title)} · EvalKit</title>
  <style>
    :root {{
      --ink: #111827;
      --muted: #6b7280;
      --secondary: #4b5563;
      --border: rgba(17, 24, 39, 0.08);
      --bg: #f5f7fa;
      --surface: #ffffff;
      --accent: #0f766e;
      --accent-ink: #0b5f59;
      --ok: #047857;
      --ok-bg: #ecfdf5;
      --fail: #b42318;
      --fail-bg: #fef3f2;
      --err: #92400e;
      --err-bg: #fffbeb;
      --raised: #f3f5f8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "PingFang SC", "Noto Sans SC", "Segoe UI", system-ui, sans-serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.5;
    }}
    .mono {{
      font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
      font-variant-numeric: tabular-nums;
    }}
    .wrap {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px 20px 48px;
    }}
    .brand {{
      display: flex;
      align-items: baseline;
      gap: 10px;
      margin-bottom: 16px;
    }}
    .brand h1 {{ margin: 0; font-size: 20px; font-weight: 600; }}
    .brand span {{ color: var(--muted); font-size: 13px; }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px 20px;
      margin-bottom: 12px;
    }}
    .meta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
      align-items: center;
    }}
    .task {{ font-size: 16px; font-weight: 600; margin-right: 4px; }}
    .status {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--secondary);
      font-size: 13px;
    }}
    .dot {{
      width: 8px; height: 8px; border-radius: 50%; background: #94a3b8;
    }}
    .dot.ok {{ background: #10b981; }}
    .dot.fail {{ background: #ef4444; }}
    .dot.run {{ background: #3b82f6; }}
    .chip {{ font-size: 13px; color: var(--secondary); }}
    .chip strong {{
      color: var(--accent-ink);
      font-weight: 600;
      margin-left: 4px;
    }}
    .alert {{
      margin-top: 12px;
      padding: 10px 12px;
      border-radius: 10px;
      background: var(--fail-bg);
      color: var(--fail);
      font-size: 13px;
    }}
    .charts {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 12px;
    }}
    @media (max-width: 900px) {{
      .charts {{ grid-template-columns: 1fr; }}
    }}
    .section-title {{
      font-size: 14px;
      font-weight: 600;
      margin: 0 0 14px;
    }}
    .donut-wrap {{
      display: flex;
      align-items: center;
      gap: 20px;
      min-height: 180px;
    }}
    .donut {{
      width: 150px;
      height: 150px;
      border-radius: 50%;
      background: {donut};
      position: relative;
      flex: 0 0 auto;
    }}
    .donut::after {{
      content: "";
      position: absolute;
      inset: 28px;
      border-radius: 50%;
      background: var(--surface);
    }}
    .donut-center {{
      position: absolute;
      inset: 0;
      z-index: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      color: var(--secondary);
    }}
    .donut-center strong {{
      font-size: 22px;
      color: var(--ink);
      line-height: 1.2;
    }}
    .legend {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      font-size: 13px;
      color: var(--secondary);
    }}
    .legend i {{
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 2px;
      margin-right: 8px;
    }}
    .bar-row {{
      display: grid;
      grid-template-columns: minmax(80px, 140px) 1fr 64px;
      gap: 10px;
      align-items: center;
      margin-bottom: 10px;
    }}
    .bar-label {{
      font-size: 12px;
      color: var(--secondary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .bar-track {{
      height: 10px;
      border-radius: 999px;
      background: #eef2f7;
      overflow: hidden;
    }}
    .bar-fill {{
      height: 100%;
      background: linear-gradient(90deg, #5f8f88, #0f766e);
      border-radius: 999px;
    }}
    .bar-pct {{
      font-size: 12px;
      color: var(--accent-ink);
      text-align: right;
    }}
    .filter-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-bottom: 12px;
    }}
    .filter-bar input,
    .filter-bar select {{
      height: 32px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0 10px;
      font: inherit;
      font-size: 13px;
      background: #fff;
      color: var(--ink);
    }}
    .filter-bar input {{ width: 220px; }}
    .filter-bar select {{ min-width: 140px; }}
    .filter-bar button {{
      height: 32px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: #fff;
      padding: 0 14px;
      font: inherit;
      font-size: 13px;
      cursor: pointer;
    }}
    .filter-bar button.primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    .table-scroll {{
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: 10px;
    }}
    table.detail-table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 860px;
      background: #fff;
    }}
    .detail-table th,
    .detail-table td {{
      border-bottom: 1px solid var(--border);
      vertical-align: top;
      padding: 12px 14px;
      text-align: left;
    }}
    .detail-table thead th {{
      background: #f8fafc;
      font-size: 12px;
      color: var(--secondary);
      font-weight: 600;
      position: sticky;
      top: 0;
      z-index: 2;
    }}
    .detail-table tbody tr:hover {{ background: #fafbfc; }}
    .detail-table tbody tr.hidden {{ display: none; }}
    .col-desc {{ width: 200px; min-width: 160px; }}
    .col-input {{ width: 220px; min-width: 180px; }}
    .col-result {{ min-width: 280px; }}
    .col-head {{ display: flex; flex-direction: column; gap: 4px; }}
    .col-provider {{ color: var(--ink); font-size: 13px; }}
    .col-prompt {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 400;
      max-width: 320px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .col-rate {{ font-size: 12px; color: var(--accent-ink); font-weight: 500; }}
    .col-rate.ok {{ color: var(--ok); }}
    .col-rate.bad {{ color: var(--fail); }}
    .case-title {{
      font-size: 13px;
      font-weight: 500;
      color: var(--ink);
      word-break: break-word;
    }}
    .vars-cell {{
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-word;
      color: var(--secondary);
      line-height: 1.55;
    }}
    .result-card {{ display: flex; flex-direction: column; gap: 8px; }}
    .result-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }}
    .result-badge {{
      display: inline-flex;
      align-items: center;
      font-size: 11px;
      font-weight: 600;
      padding: 1px 8px;
      border-radius: 999px;
      letter-spacing: 0.02em;
    }}
    .result-badge.pass {{ background: var(--ok-bg); color: var(--ok); }}
    .result-badge.fail {{ background: var(--fail-bg); color: var(--fail); }}
    .result-badge.error {{ background: var(--err-bg); color: var(--err); }}
    .result-output {{
      font-size: 13px;
      color: var(--ink);
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 160px;
      overflow: auto;
      line-height: 1.55;
    }}
    .result-meta {{
      font-size: 12px;
      color: var(--muted);
    }}
    .cell-detail summary {{
      list-style: none;
      cursor: pointer;
      color: var(--accent);
      font-size: 12px;
      user-select: none;
    }}
    .cell-detail summary::-webkit-details-marker {{ display: none; }}
    .cell-detail-body {{
      margin-top: 8px;
      padding: 10px;
      border-radius: 8px;
      background: var(--raised);
      border: 1px solid var(--border);
    }}
    .cell-detail-body h5 {{
      margin: 0 0 6px;
      font-size: 12px;
      color: var(--muted);
    }}
    .cell-detail-body pre {{
      margin: 0 0 10px;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      font-family: "IBM Plex Mono", ui-monospace, monospace;
    }}
    .assert {{
      display: grid;
      grid-template-columns: 108px minmax(0, 1fr);
      gap: 8px;
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .assert.ok strong {{ color: var(--ok); }}
    .assert.fail strong {{ color: var(--fail); }}
    .muted {{ color: var(--muted); }}
    .empty {{
      color: var(--muted);
      font-size: 13px;
      padding: 16px;
      text-align: center;
    }}
    .footer {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 12px;
      text-align: center;
    }}
    .filter-count {{
      margin-left: auto;
      font-size: 12px;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="brand">
      <h1>EvalKit</h1>
      <span>评测工作台 · 测评报告</span>
    </div>

    <section class="panel">
      <div class="meta-row">
        <span class="task">{_esc(title)}</span>
        <span class="status">
          <span class="dot {'ok' if status_value == 'succeeded' else ('fail' if status_value == 'failed' else 'run')}"></span>
          {_esc(_status_label(status_value))}
        </span>
        <span class="chip">通过率<strong class="mono">{pass_rate:.2f}%</strong></span>
        <span class="chip mono">{pass_count} 通过 / {fail_count} 失败 / {error_count} 错误</span>
        {f'<span class="chip mono">{_esc(duration)}</span>' if duration else ''}
        {f'<span class="chip mono">{_esc(created)}</span>' if created else ''}
      </div>
      {f'<div class="alert">{_esc(summary.error)}</div>' if summary.error else ''}
    </section>

    <div class="charts">
      <section class="panel">
        <div class="section-title">结果分布</div>
        <div class="donut-wrap">
          <div class="donut">
            <div class="donut-center">
              <strong class="mono">{pass_rate:.1f}%</strong>
              <span>共 {total} 条</span>
            </div>
          </div>
          <div class="legend">
            <div><i style="background:#0f766e"></i>通过 {pass_count} · {round((pass_count / total) * 100, 1) if total else 0}%</div>
            <div><i style="background:#dc2626"></i>失败 {fail_count} · {fail_rate}%</div>
            <div><i style="background:#94a3b8"></i>错误 {error_count} · {error_rate}%</div>
          </div>
        </div>
      </section>
      <section class="panel">
        <div class="section-title">供应商通过率</div>
        {''.join(provider_bars)}
      </section>
    </div>

    <section class="panel">
      <div class="section-title">详细结果</div>
      <div class="filter-bar">
        <input id="f-keyword" type="search" placeholder="搜索测试项 / 输入 / 输出" />
        <select id="f-result">
          <option value="all">全部结果</option>
          <option value="pass">通过</option>
          <option value="fail">失败</option>
          <option value="error">错误</option>
        </select>
        <select id="f-provider">
          <option value="">全部供应商</option>
          {provider_opts_html}
        </select>
        <select id="f-prompt">
          <option value="">全部提示词</option>
          {prompt_opts_html}
        </select>
        <button type="button" class="primary" id="f-apply">查询</button>
        <button type="button" id="f-reset">重置</button>
        <span class="filter-count mono" id="f-count">共 {len(matrix_rows)} 条</span>
      </div>
      <div class="table-scroll">
        <table class="detail-table" id="matrix-table">
          <thead>
            <tr>{''.join(thead_cells)}</tr>
          </thead>
          <tbody>
            {''.join(body_rows)}
          </tbody>
        </table>
      </div>
    </section>

    <div class="footer">由 EvalKit 生成 · {_esc(generated)}</div>
  </div>
  <script>
    (function () {{
      var keywordEl = document.getElementById('f-keyword');
      var resultEl = document.getElementById('f-result');
      var providerEl = document.getElementById('f-provider');
      var promptEl = document.getElementById('f-prompt');
      var countEl = document.getElementById('f-count');
      var rows = Array.prototype.slice.call(document.querySelectorAll('.matrix-row'));
      var resultCols = Array.prototype.slice.call(document.querySelectorAll('th.col-result, td.col-result'));

      function applyFilters() {{
        var q = (keywordEl.value || '').trim().toLowerCase();
        var tone = resultEl.value || 'all';
        var provider = providerEl.value || '';
        var prompt = promptEl.value || '';

        resultCols.forEach(function (el) {{
          var show = true;
          if (provider && el.getAttribute('data-provider') !== provider) show = false;
          if (prompt && el.getAttribute('data-prompt') !== prompt) show = false;
          el.style.display = show ? '' : 'none';
        }});

        var visible = 0;
        rows.forEach(function (row) {{
          var ok = true;
          if (tone !== 'all' && row.getAttribute('data-tone') !== tone) ok = false;
          if (ok && q) {{
            var hay = row.getAttribute('data-search') || '';
            if (hay.indexOf(q) === -1) ok = false;
          }}
          if (ok) {{
            // Hide row if all result cells are filtered out
            var cells = row.querySelectorAll('td.col-result');
            var anyVisible = false;
            cells.forEach(function (c) {{
              if (c.style.display !== 'none') anyVisible = true;
            }});
            if (!anyVisible && cells.length) ok = false;
          }}
          row.classList.toggle('hidden', !ok);
          if (ok) visible += 1;
        }});
        countEl.textContent = '共 ' + visible + ' 条';
      }}

      document.getElementById('f-apply').addEventListener('click', applyFilters);
      document.getElementById('f-reset').addEventListener('click', function () {{
        keywordEl.value = '';
        resultEl.value = 'all';
        providerEl.value = '';
        promptEl.value = '';
        applyFilters();
      }});
      keywordEl.addEventListener('keydown', function (e) {{
        if (e.key === 'Enter') applyFilters();
      }});
    }})();
  </script>
</body>
</html>
"""
