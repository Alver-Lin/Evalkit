from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.schemas import EvalStatus
from app.services.report_builder import summarize_results
from app.services.store import config_store, run_store


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
        summary = run_store.get(run_id)
        summary.status = EvalStatus.running
        summary.started_at = datetime.now(timezone.utc)
        run_store.save(summary)

        run_dir = run_store.run_dir(run_id)
        results_json = run_store.results_path(run_id)
        report_html = run_store.html_path(run_id)

        # Stage config + helpers into the run directory so relative provider
        # paths (e.g. python:custom_provider.py) resolve correctly.
        config_yaml = self._stage_config(config_id, run_dir)

        cmd = [
            *settings.resolve_promptfoo_cmd(),
            "eval",
            "-c",
            str(config_yaml),
            "-j",
            str(max_concurrency),
            "--output",
            str(results_json),
            "--output",
            str(report_html),
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
            stdout_b, stderr_b = await process.communicate()
            stdout_chunks.append(stdout_b.decode("utf-8", errors="replace"))
            stderr_chunks.append(stderr_b.decode("utf-8", errors="replace"))

            (run_dir / "stdout.log").write_text("".join(stdout_chunks), encoding="utf-8")
            (run_dir / "stderr.log").write_text("".join(stderr_chunks), encoding="utf-8")

            summary = run_store.get(run_id)
            summary.finished_at = datetime.now(timezone.utc)
            if summary.started_at:
                summary.duration_ms = int(
                    (summary.finished_at - summary.started_at).total_seconds() * 1000
                )

            if process.returncode != 0 and not results_json.exists():
                summary.status = EvalStatus.failed
                summary.error = (
                    "".join(stderr_chunks).strip()
                    or "".join(stdout_chunks).strip()
                    or f"promptfoo exited with code {process.returncode}"
                )
                run_store.save(summary)
                return

            results = self._load_json(results_json)
            stats = summarize_results(results)
            summary.pass_count = stats["pass_count"]
            summary.fail_count = stats["fail_count"]
            summary.error_count = stats["error_count"]
            summary.total_count = stats["total_count"]
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

    def _stage_config(self, config_id: str, run_dir: Path) -> Path:
        src = settings.configs_dir / config_id
        dest_yaml = run_dir / "promptfooconfig.yaml"
        shutil.copy2(src / "promptfooconfig.yaml", dest_yaml)

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
        return env

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))


promptfoo_runner = PromptfooRunner()
