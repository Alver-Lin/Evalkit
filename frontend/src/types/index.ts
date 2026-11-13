export type EvalStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface ConfigMeta {
  id: string
  name: string
  description: string
  created_at: string
  updated_at: string
  yaml_content: string
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
