from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class EvalStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    yaml_content: str = Field(..., min_length=1)


class ConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = None
    yaml_content: Optional[str] = None


class ConfigMeta(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: datetime
    updated_at: datetime
    yaml_content: str


class EvalRunRequest(BaseModel):
    config_id: str
    max_concurrency: int = Field(2, ge=1, le=20)
    cache: bool = False
    description: str = ""


class EvalRunSummary(BaseModel):
    id: str
    config_id: str
    config_name: str
    status: EvalStatus
    description: str = ""
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    pass_count: int = 0
    fail_count: int = 0
    error_count: int = 0
    total_count: int = 0
    pass_rate: float = 0.0
    duration_ms: Optional[int] = None


class EvalRunDetail(EvalRunSummary):
    results: Optional[dict[str, Any]] = None
    report_html_url: Optional[str] = None
    report_json_url: Optional[str] = None
    stdout: str = ""
    stderr: str = ""


class DashboardStats(BaseModel):
    config_count: int
    run_count: int
    succeeded_count: int
    failed_count: int
    avg_pass_rate: float
    recent_runs: list[EvalRunSummary]


class ReportExportRequest(BaseModel):
    format: str = Field("html", pattern="^(html|json|csv)$")


class ProviderProbeRequest(BaseModel):
    id: str = Field(..., min_length=1, description="Provider ID, e.g. openai:chat:qwen")
    api_key: str = ""
    api_host: str = ""
    organization: str = ""
    method: str = Field("", description="HTTP method for custom HTTP providers, e.g. POST")


class ProviderProbeResponse(BaseModel):
    ok: bool
    message: str
    provider_id: Optional[str] = None
    api_base: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    details: Optional[dict[str, Any]] = None
