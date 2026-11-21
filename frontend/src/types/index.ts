export type EvalStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface ConfigMeta {
  id: string
  name: string
  description: string
  created_at: string
  updated_at: string
  yaml_content: string
  max_concurrency?: number
  cache?: boolean
}

export interface EvalRunSummary {
  id: string
  config_id: string
  config_name: string
  status: EvalStatus
  description: string
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  error?: string | null
  pass_count: number
  fail_count: number
  error_count: number
  total_count: number
  /** Finished cases so far while running (pass+fail+error). */
  completed_count?: number
  pass_rate: number
  duration_ms?: number | null
}

export interface EvalRunDetail extends EvalRunSummary {
  results?: Record<string, unknown> | null
  report_html_url?: string | null
  report_json_url?: string | null
  stdout: string
  stderr: string
}

export interface DashboardStats {
  config_count: number
  run_count: number
  succeeded_count: number
  failed_count: number
  avg_pass_rate: number
  recent_runs: EvalRunSummary[]
}

export interface AssertionDetail {
  type?: string | null
  pass?: boolean
  score?: number
  reason?: string
}

export interface ReportRow {
  id: number
  testIdx?: number
  promptIdx?: number
  description?: string
  provider: string
  prompt: string
  vars: Record<string, unknown>
  output: string
  /** Model thinking / chain-of-thought, split from output when present. */
  thinking?: string | null
  success: boolean
  score?: number | null
  latencyMs?: number | null
  cost?: number | null
  error?: string | null
  reason?: string | null
  assertions: AssertionDetail[]
}

export interface ReportView {
  summary: {
    pass_count: number
    fail_count: number
    error_count: number
    total_count: number
    pass_rate: number
  }
  prompts: unknown[]
  providers: unknown[]
  table: ReportRow[]
  by_provider: Array<{ name: string; pass: number; fail: number; error: number; total: number; pass_rate: number }>
  by_prompt: Array<{ name: string; pass: number; fail: number; error: number; total: number; pass_rate: number }>
  timestamp?: string
  version?: number | string
  raw?: Record<string, unknown> | null
}

export interface ProviderProbeRequest {
  id: string
  api_key?: string
  api_host?: string
  organization?: string
  /** HTTP method for custom HTTP providers (e.g. POST). */
  method?: string
  headers?: Record<string, string>
  body?: string
  timeout_sec?: number
}

export interface ProviderProbeResponse {
  ok: boolean
  message: string
  provider_id?: string | null
  api_base?: string | null
  model?: string | null
  latency_ms?: number | null
  details?: Record<string, unknown> | null
  status_code?: number | null
  sample_text?: string | null
  content_type?: string | null
}

export type GraderKind = 'openai' | 'http'

export interface GraderHttpHeader {
  key: string
  value: string
}

export interface GraderMeta {
  id: string
  kind: GraderKind | string
  name: string
  description: string
  provider_id: string
  api_key: string
  api_host: string
  organization: string
  enable_thinking: boolean
  max_tokens?: number | null
  http_method: string
  timeout_sec?: number | null
  headers: GraderHttpHeader[]
  transform_response: string
  created_at: string
  updated_at: string
}

export type GraderPayload = {
  kind: GraderKind
  name: string
  description?: string
  provider_id: string
  api_key?: string
  api_host?: string
  organization?: string
  enable_thinking?: boolean
  max_tokens?: number | null
  http_method?: string
  timeout_sec?: number | null
  headers?: GraderHttpHeader[]
  transform_response?: string
}
