import axios from 'axios'
import type {
  ConfigMeta,
  DashboardStats,
  EvalRunDetail,
  EvalRunSummary,
  ProviderProbeRequest,
  ProviderProbeResponse,
  ReportView,
} from '@/types'

const http = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

export const api = {
  getStats: () => http.get<DashboardStats>('/dashboard/stats').then((r) => r.data),
  listConfigs: () => http.get<ConfigMeta[]>('/configs').then((r) => r.data),
  getConfig: (id: string) => http.get<ConfigMeta>(`/configs/${id}`).then((r) => r.data),
  createConfig: (payload: { name: string; description?: string; yaml_content: string }) =>
    http.post<ConfigMeta>('/configs', payload).then((r) => r.data),
  updateConfig: (
    id: string,
    payload: Partial<{ name: string; description: string; yaml_content: string }>,
  ) => http.put<ConfigMeta>(`/configs/${id}`, payload).then((r) => r.data),
  deleteConfig: (id: string) => http.delete(`/configs/${id}`).then((r) => r.data),
  listRuns: () => http.get<EvalRunSummary[]>('/runs').then((r) => r.data),
  getRun: (id: string) => http.get<EvalRunDetail>(`/runs/${id}`).then((r) => r.data),
  createRun: (payload: {
    config_id: string
    max_concurrency?: number
    cache?: boolean
    description?: string
  }) => http.post<EvalRunSummary>('/runs', payload).then((r) => r.data),
  deleteRun: (id: string) => http.delete(`/runs/${id}`).then((r) => r.data),
  getReport: (id: string) => http.get<ReportView>(`/runs/${id}/report`).then((r) => r.data),
  probeProvider: (payload: ProviderProbeRequest) =>
    http.post<ProviderProbeResponse>('/providers/probe', payload).then((r) => r.data),
}

export default http
