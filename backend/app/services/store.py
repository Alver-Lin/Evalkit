from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from app.core.config import settings
from app.models.schemas import ConfigMeta, EvalRunSummary, EvalStatus, GraderHttpHeader, GraderMeta
from app.services.chinese_rubric import strip_evalkit_rubric_prompt_text


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class ConfigStore:
    def list(self) -> list[ConfigMeta]:
        items: list[ConfigMeta] = []
        for meta_path in settings.configs_dir.glob("*/meta.json"):
            items.append(ConfigMeta(**_read_json(meta_path)))
        return sorted(items, key=lambda c: c.updated_at, reverse=True)

    def get(self, config_id: str) -> ConfigMeta:
        meta_path = settings.configs_dir / config_id / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Config not found: {config_id}")
        return ConfigMeta(**_read_json(meta_path))

    @staticmethod
    def _sanitize_yaml(yaml_content: str) -> str:
        return strip_evalkit_rubric_prompt_text(yaml_content)

    def create(
        self,
        name: str,
        description: str,
        yaml_content: str,
        max_concurrency: int = 2,
        cache: bool = False,
    ) -> ConfigMeta:
        yaml_content = self._sanitize_yaml(yaml_content)
        self._validate_yaml(yaml_content)
        config_id = uuid.uuid4().hex[:12]
        now = _now()
        meta = ConfigMeta(
            id=config_id,
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
            yaml_content=yaml_content,
            max_concurrency=max_concurrency,
            cache=cache,
        )
        self._persist(meta)
        return meta

    def update(
        self,
        config_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        yaml_content: Optional[str] = None,
        max_concurrency: Optional[int] = None,
        cache: Optional[bool] = None,
    ) -> ConfigMeta:
        meta = self.get(config_id)
        if name is not None:
            meta.name = name
        if description is not None:
            meta.description = description
        if yaml_content is not None:
            yaml_content = self._sanitize_yaml(yaml_content)
            self._validate_yaml(yaml_content)
            meta.yaml_content = yaml_content
        if max_concurrency is not None:
            meta.max_concurrency = max_concurrency
        if cache is not None:
            meta.cache = cache
        meta.updated_at = _now()
        self._persist(meta)
        return meta

    def delete(self, config_id: str) -> None:
        folder = settings.configs_dir / config_id
        if not folder.exists():
            raise FileNotFoundError(f"Config not found: {config_id}")
        for path in folder.glob("*"):
            path.unlink()
        folder.rmdir()

    def config_yaml_path(self, config_id: str) -> Path:
        return settings.configs_dir / config_id / "promptfooconfig.yaml"

    def _persist(self, meta: ConfigMeta) -> None:
        folder = settings.configs_dir / meta.id
        folder.mkdir(parents=True, exist_ok=True)
        self.config_yaml_path(meta.id).write_text(meta.yaml_content, encoding="utf-8")
        _write_json(folder / "meta.json", meta.model_dump(mode="json"))

    @staticmethod
    def _validate_yaml(content: str) -> None:
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            raise ValueError("YAML root must be a mapping")
        if "prompts" not in data:
            raise ValueError("YAML must include `prompts`")
        if "providers" not in data and "targets" not in data:
            raise ValueError("YAML must include `providers` or `targets`")


def _normalize_run_summary(summary: EvalRunSummary) -> EvalRunSummary:
    """Fix legacy runs marked succeeded despite failed/errored cases."""
    if summary.status == EvalStatus.succeeded and (summary.fail_count or summary.error_count):
        summary.status = EvalStatus.failed
        if not summary.error:
            parts: list[str] = []
            if summary.fail_count:
                parts.append(f"{summary.fail_count} 未通过")
            if summary.error_count:
                parts.append(f"{summary.error_count} 错误")
            summary.error = "，".join(parts) or "测评未全部通过"
    return summary


class RunStore:
    def list(self) -> list[EvalRunSummary]:
        items: list[EvalRunSummary] = []
        for meta_path in settings.runs_dir.glob("*/meta.json"):
            summary = _normalize_run_summary(EvalRunSummary(**_read_json(meta_path)))
            items.append(summary)
        return sorted(items, key=lambda r: r.created_at, reverse=True)

    def get(self, run_id: str) -> EvalRunSummary:
        meta_path = settings.runs_dir / run_id / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return _normalize_run_summary(EvalRunSummary(**_read_json(meta_path)))

    def create(
        self,
        config_id: str,
        config_name: str,
        description: str = "",
    ) -> EvalRunSummary:
        run_id = uuid.uuid4().hex[:12]
        now = _now()
        summary = EvalRunSummary(
            id=run_id,
            config_id=config_id,
            config_name=config_name,
            status=EvalStatus.pending,
            description=description,
            created_at=now,
        )
        folder = settings.runs_dir / run_id
        folder.mkdir(parents=True, exist_ok=True)
        self.save(summary)
        return summary

    def save(self, summary: EvalRunSummary) -> None:
        folder = settings.runs_dir / summary.id
        folder.mkdir(parents=True, exist_ok=True)
        _write_json(folder / "meta.json", summary.model_dump(mode="json"))

    def run_dir(self, run_id: str) -> Path:
        return settings.runs_dir / run_id

    def results_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "results.json"

    def html_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "report.html"

    def load_results(self, run_id: str) -> Optional[dict[str, Any]]:
        path = self.results_path(run_id)
        if not path.exists():
            return None
        return _read_json(path)

    def delete(self, run_id: str) -> None:
        folder = self.run_dir(run_id)
        if not folder.exists():
            raise FileNotFoundError(f"Run not found: {run_id}")
        shutil.rmtree(folder)


class GraderStore:
    def list(self) -> list[GraderMeta]:
        items: list[GraderMeta] = []
        for meta_path in settings.graders_dir.glob("*/meta.json"):
            items.append(GraderMeta(**_read_json(meta_path)))
        return sorted(items, key=lambda g: g.updated_at, reverse=True)

    def get(self, grader_id: str) -> GraderMeta:
        meta_path = settings.graders_dir / grader_id / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Grader not found: {grader_id}")
        return GraderMeta(**_read_json(meta_path))

    def create(
        self,
        *,
        kind: str,
        name: str,
        description: str = "",
        provider_id: str = "",
        api_key: str = "",
        api_host: str = "",
        organization: str = "",
        enable_thinking: bool = False,
        max_tokens: Optional[int] = 1024,
        http_method: str = "POST",
        timeout_sec: Optional[float] = 60,
        headers: Optional[list[GraderHttpHeader]] = None,
        transform_response: str = "",
    ) -> GraderMeta:
        kind = self._normalize_kind(kind)
        name = name.strip()
        if not name:
            raise ValueError("Name is required")
        provider_id = (provider_id or "").strip()
        if not provider_id:
            raise ValueError("Provider ID / URL is required")
        grader_id = uuid.uuid4().hex[:12]
        now = _now()
        meta = GraderMeta(
            id=grader_id,
            kind=kind,
            name=name,
            description=description or "",
            provider_id=provider_id,
            api_key=api_key or "",
            api_host=api_host or "",
            organization=organization or "",
            enable_thinking=bool(enable_thinking),
            max_tokens=max_tokens,
            http_method=(http_method or "POST").strip().upper() or "POST",
            timeout_sec=timeout_sec,
            headers=list(headers or []),
            transform_response=transform_response or "",
            created_at=now,
            updated_at=now,
        )
        self._persist(meta)
        return meta

    def update(
        self,
        grader_id: str,
        *,
        kind: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        provider_id: Optional[str] = None,
        api_key: Optional[str] = None,
        api_host: Optional[str] = None,
        organization: Optional[str] = None,
        enable_thinking: Optional[bool] = None,
        max_tokens: Optional[int] = None,
        http_method: Optional[str] = None,
        timeout_sec: Optional[float] = None,
        headers: Optional[list[GraderHttpHeader]] = None,
        transform_response: Optional[str] = None,
    ) -> GraderMeta:
        meta = self.get(grader_id)
        if kind is not None:
            meta.kind = self._normalize_kind(kind)
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Name is required")
            meta.name = name
        if description is not None:
            meta.description = description
        if provider_id is not None:
            provider_id = provider_id.strip()
            if not provider_id:
                raise ValueError("Provider ID / URL is required")
            meta.provider_id = provider_id
        if api_key is not None:
            meta.api_key = api_key
        if api_host is not None:
            meta.api_host = api_host
        if organization is not None:
            meta.organization = organization
        if enable_thinking is not None:
            meta.enable_thinking = bool(enable_thinking)
        if max_tokens is not None:
            meta.max_tokens = max_tokens
        if http_method is not None:
            meta.http_method = http_method.strip().upper() or "POST"
        if timeout_sec is not None:
            meta.timeout_sec = timeout_sec
        if headers is not None:
            meta.headers = list(headers)
        if transform_response is not None:
            meta.transform_response = transform_response
        meta.updated_at = _now()
        self._persist(meta)
        return meta

    def delete(self, grader_id: str) -> None:
        folder = settings.graders_dir / grader_id
        if not folder.exists():
            raise FileNotFoundError(f"Grader not found: {grader_id}")
        shutil.rmtree(folder)

    def _persist(self, meta: GraderMeta) -> None:
        folder = settings.graders_dir / meta.id
        folder.mkdir(parents=True, exist_ok=True)
        _write_json(folder / "meta.json", meta.model_dump(mode="json"))

    @staticmethod
    def _normalize_kind(kind: str) -> str:
        value = (kind or "openai").strip().lower()
        if value not in {"openai", "http"}:
            raise ValueError("kind must be openai or http")
        return value


config_store = ConfigStore()
run_store = RunStore()
grader_store = GraderStore()
