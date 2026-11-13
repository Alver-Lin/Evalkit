from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from app.core.config import settings
from app.models.schemas import ConfigMeta, EvalRunSummary, EvalStatus


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

    def create(self, name: str, description: str, yaml_content: str) -> ConfigMeta:
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
        )
        self._persist(meta)
        return meta

    def update(
        self,
        config_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        yaml_content: Optional[str] = None,
    ) -> ConfigMeta:
        meta = self.get(config_id)
        if name is not None:
            meta.name = name
        if description is not None:
            meta.description = description
        if yaml_content is not None:
            self._validate_yaml(yaml_content)
            meta.yaml_content = yaml_content
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


class RunStore:
    def list(self) -> list[EvalRunSummary]:
        items: list[EvalRunSummary] = []
        for meta_path in settings.runs_dir.glob("*/meta.json"):
            items.append(EvalRunSummary(**_read_json(meta_path)))
        return sorted(items, key=lambda r: r.created_at, reverse=True)

    def get(self, run_id: str) -> EvalRunSummary:
        meta_path = settings.runs_dir / run_id / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return EvalRunSummary(**_read_json(meta_path))

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


config_store = ConfigStore()
run_store = RunStore()
