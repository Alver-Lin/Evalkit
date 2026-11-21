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
    max_concurrency: int = Field(2, ge=1, le=20)
    cache: bool = False


class ConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = None
    yaml_content: Optional[str] = None
    max_concurrency: Optional[int] = Field(None, ge=1, le=20)
    cache: Optional[bool] = None


class ConfigMeta(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: datetime
    updated_at: datetime
    yaml_content: str
    max_concurrency: int = Field(2, ge=1, le=20)
    cache: bool = False


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
    completed_count: int = Field(
        0, description="Finished cases so far (pass+fail+error); useful while running"
    )
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
    headers: Optional[dict[str, str]] = None
    body: str = Field("", description="Request body for custom HTTP probe (prompt with vars filled)")
    timeout_sec: Optional[float] = Field(None, description="Optional timeout override for HTTP probe")


class ProviderProbeResponse(BaseModel):
    ok: bool
    message: str
    provider_id: Optional[str] = None
    api_base: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    details: Optional[dict[str, Any]] = None
    status_code: Optional[int] = None
    sample_text: Optional[str] = Field(
        None, description="Truncated raw response body for visual extract preview"
    )
    content_type: Optional[str] = None


class AiExtractSelectedValue(BaseModel):
    path: str = Field(..., min_length=1, description="JSON path, e.g. data.document.content[0].text")
    value: str = Field("", description="Example leaf value the user wants to keep")


class AiExtractRequest(BaseModel):
    sample_text: str = Field(..., min_length=1, description="Probe sample response body")
    source: str = Field("json", pattern="^(sse|json)$")
    selected_values: list[AiExtractSelectedValue] = Field(default_factory=list)
    hint: str = ""
    grader_id: str = Field(..., min_length=1, description="Grader from 模型评测配置")


class AiExtractResponse(BaseModel):
    ok: bool
    message: str
    ai_script: Optional[str] = None
    grader_id: Optional[str] = None
    grader_name: Optional[str] = None


class GraderHttpHeader(BaseModel):
    key: str = ""
    value: str = ""


class GraderCreate(BaseModel):
    kind: str = Field("openai", pattern="^(openai|http)$")
    name: str = Field(..., min_length=1, max_length=120, description="Display label")
    description: str = ""
    provider_id: str = Field("", description="OpenAI id or HTTP URL")
    api_key: str = ""
    api_host: str = ""
    organization: str = ""
    enable_thinking: bool = False
    max_tokens: Optional[int] = Field(1024, ge=1, le=128000)
    http_method: str = "POST"
    timeout_sec: Optional[float] = Field(60, ge=1, le=600)
    headers: list[GraderHttpHeader] = Field(default_factory=list)
    transform_response: str = ""


class GraderUpdate(BaseModel):
    kind: Optional[str] = Field(None, pattern="^(openai|http)$")
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = None
    provider_id: Optional[str] = None
    api_key: Optional[str] = None
    api_host: Optional[str] = None
    organization: Optional[str] = None
    enable_thinking: Optional[bool] = None
    max_tokens: Optional[int] = Field(None, ge=1, le=128000)
    http_method: Optional[str] = None
    timeout_sec: Optional[float] = Field(None, ge=1, le=600)
    headers: Optional[list[GraderHttpHeader]] = None
    transform_response: Optional[str] = None


class GraderMeta(BaseModel):
    id: str
    kind: str = "openai"
    name: str
    description: str = ""
    provider_id: str = ""
    api_key: str = ""
    api_host: str = ""
    organization: str = ""
    enable_thinking: bool = False
    max_tokens: Optional[int] = 1024
    http_method: str = "POST"
    timeout_sec: Optional[float] = 60
    headers: list[GraderHttpHeader] = Field(default_factory=list)
    transform_response: str = ""
    created_at: datetime
    updated_at: datetime
