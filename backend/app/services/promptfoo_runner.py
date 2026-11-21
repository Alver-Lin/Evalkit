from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.schemas import EvalStatus
from app.services.chinese_rubric import ensure_chinese_rubric_prompt
from app.services.evalkit_asserts import ensure_evalkit_asserts
from app.services.http_sse import ensure_http_sse_transform
from app.services.html_report import build_evalkit_html_report
from app.services.report_builder import build_report_view, summarize_results
from app.services.run_progress import (
    apply_progress_to_summary,
    count_expected_results,
    progress_jsonl_path,
)
from app.services.store import run_store


class PromptfooRunner:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def start(
        self,
        run_id: str,
        config_id: str,
        max_concurrency: int = 2,
        cache: bool = False,
    ) -> None:
        if run_id in self._tasks and not self._tasks[run_id].done():
            raise RuntimeError(f"Run already in progress: {run_id}")
        self._tasks[run_id] = asyncio.create_task(
            self._execute(run_id, config_id, max_concurrency, cache)
        )

    async def _execute(
        self,
        run_id: str,
        config_id: str,
        max_concurrency: int,
        cache: bool,
    ) -> None:
        run_dir = run_store.run_dir(run_id)
        results_json = run_store.results_path(run_id)
        progress_jsonl = progress_jsonl_path(run_dir)

        # Stage config + helpers into the run directory so relative provider
        # paths (e.g. python:custom_provider.py) resolve correctly.
        config_yaml = self._stage_config(config_id, run_dir)
        expected_total = count_expected_results(config_yaml)

        summary = run_store.get(run_id)
        summary.status = EvalStatus.running
        summary.started_at = datetime.now(timezone.utc)
        summary.pass_count = 0
        summary.fail_count = 0
        summary.error_count = 0
        summary.completed_count = 0
        summary.pass_rate = 0.0
        summary.total_count = expected_total
        summary.error = None
        run_store.save(summary)

        cmd = [
            *settings.resolve_promptfoo_cmd(),
            "eval",
            "-c",
            str(config_yaml),
            "-j",
            str(max_concurrency),
            "--output",
            str(results_json),
            # Stream one JSON object per finished case for live progress.
            "--output",
            str(progress_jsonl),
            "--no-progress-bar",
        ]
        if not cache:
            cmd.append("--no-cache")

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(run_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._build_env(),
            )

            async def _pump(stream: asyncio.StreamReader | None, sink: list[str], log_name: str) -> None:
                if stream is None:
                    return
                chunks: list[bytes] = []
                while True:
                    block = await stream.read(65536)
                    if not block:
                        break
                    chunks.append(block)
                    text = b"".join(chunks).decode("utf-8", errors="replace")
                    sink.clear()
                    sink.append(text)
                    (run_dir / log_name).write_text(text, encoding="utf-8")

            stdout_task = asyncio.create_task(_pump(process.stdout, stdout_chunks, "stdout.log"))
            stderr_task = asyncio.create_task(_pump(process.stderr, stderr_chunks, "stderr.log"))
            progress_task = asyncio.create_task(self._watch_progress(run_id, run_dir))

            returncode = await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass

            # Final mid-run sync before reading results.json.
            summary = run_store.get(run_id)
            if apply_progress_to_summary(summary, run_dir):
                run_store.save(summary)

            (run_dir / "stdout.log").write_text("".join(stdout_chunks), encoding="utf-8")
            (run_dir / "stderr.log").write_text("".join(stderr_chunks), encoding="utf-8")

            summary = run_store.get(run_id)
            summary.finished_at = datetime.now(timezone.utc)
            if summary.started_at:
                summary.duration_ms = int(
                    (summary.finished_at - summary.started_at).total_seconds() * 1000
                )

            if returncode != 0 and not results_json.exists():
                summary.status = EvalStatus.failed
                summary.error = (
                    "".join(stderr_chunks).strip()
                    or "".join(stdout_chunks).strip()
                    or f"promptfoo exited with code {returncode}"
                )
                run_store.save(summary)
                return

            results = self._load_json(results_json)
            stats = summarize_results(results)
            summary.pass_count = stats["pass_count"]
            summary.fail_count = stats["fail_count"]
            summary.error_count = stats["error_count"]
            summary.total_count = stats["total_count"] or expected_total
            summary.completed_count = stats["total_count"]
            summary.pass_rate = stats["pass_rate"]
            # Process finished, but mark failed when any case failed/errored.
            if stats["fail_count"] or stats["error_count"]:
                summary.status = EvalStatus.failed
                parts: list[str] = []
                if stats["fail_count"]:
                    parts.append(f"{stats['fail_count']} 未通过")
                if stats["error_count"]:
                    parts.append(f"{stats['error_count']} 错误")
                summary.error = "，".join(parts) or "测评未全部通过"
            else:
                summary.status = EvalStatus.succeeded
                summary.error = None
            run_store.save(summary)
            # Write EvalKit-styled HTML (replaces promptfoo official report.html).
            try:
                html_text = build_evalkit_html_report(summary, build_report_view(results))
                run_store.html_path(run_id).write_text(html_text, encoding="utf-8")
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001
            summary = run_store.get(run_id)
            summary.status = EvalStatus.failed
            summary.finished_at = datetime.now(timezone.utc)
            if summary.started_at:
                summary.duration_ms = int(
                    (summary.finished_at - summary.started_at).total_seconds() * 1000
                )
            summary.error = str(exc)
            run_store.save(summary)
            (run_dir / "stderr.log").write_text(
                "\n".join(stderr_chunks + [str(exc)]), encoding="utf-8"
            )

    async def _watch_progress(self, run_id: str, run_dir: Path) -> None:
        """Poll streaming JSONL and persist live pass/fail/completed counts."""
        while True:
            try:
                summary = run_store.get(run_id)
                if apply_progress_to_summary(summary, run_dir):
                    run_store.save(summary)
            except Exception:
                # Never crash the eval because progress polling failed.
                pass
            await asyncio.sleep(1.0)

    def _stage_config(self, config_id: str, run_dir: Path) -> Path:
        src = settings.configs_dir / config_id
        dest_yaml = run_dir / "promptfooconfig.yaml"
        shutil.copy2(src / "promptfooconfig.yaml", dest_yaml)
        # Force Chinese llm-rubric / model-graded reasons (promptfoo default is English).
        ensure_chinese_rubric_prompt(dest_yaml)
        # Default SSE parser for custom HTTP providers (kept out of user YAML).
        ensure_http_sse_transform(dest_yaml)
        # Expand word-count + inject Thinking strip only when think is enabled.
        ensure_evalkit_asserts(dest_yaml)

        for item in src.iterdir():
            if item.name in {"meta.json", "promptfooconfig.yaml"}:
                continue
            target = run_dir / item.name
            if item.is_file():
                shutil.copy2(item, target)
            elif item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target)
        return dest_yaml

    @staticmethod
    def _build_env() -> dict[str, str]:
        import os

        env = os.environ.copy()
        env.setdefault("PROMPTFOO_DISABLE_TELEMETRY", "1")
        env.setdefault("CI", "1")
        # Avoid mid-stream "terminated" on slower thinking models.
        env.setdefault("REQUEST_TIMEOUT_MS", "300000")
        env.setdefault("PROMPTFOO_EVAL_TIMEOUT_MS", "600000")
        return env

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))


promptfoo_runner = PromptfooRunner()
