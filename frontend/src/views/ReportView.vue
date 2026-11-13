<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import dayjs from 'dayjs'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { api } from '@/api/client'
import type { EvalRunDetail, ReportRow, ReportView as ReportViewData } from '@/types'
import StatusTag from '@/components/StatusTag.vue'

use([CanvasRenderer, PieChart, BarChart, GridComponent, TitleComponent, TooltipComponent, LegendComponent])

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const run = ref<EvalRunDetail | null>(null)
const report = ref<ReportViewData | null>(null)
type ResultFilter = 'all' | 'pass' | 'fail' | 'error'

const filter = ref<ResultFilter>('all')
const keyword = ref('')
const selectedProvider = ref<string>('all')
const selectedPrompt = ref<string>('all')
const draftFilter = ref<ResultFilter>('all')
const draftKeyword = ref('')
const draftProvider = ref<string>('all')
const draftPrompt = ref<string>('all')
const matrixFiltersReady = ref(false)
const detailOpen = ref(false)
const detailRow = ref<ReportRow | null>(null)
let timer: number | undefined

const resultFilterOptions = [
  { label: '全部结果', value: 'all' },
  { label: '通过', value: 'pass' },
  { label: '失败', value: 'fail' },
  { label: '错误', value: 'error' },
]

type MatrixCol = {
  key: string
  prompt: string
  promptLabel: string
  provider: string
  pass: number
  fail: number
  error: number
  total: number
  passRate: number
}

type MatrixRow = {
  key: string
  testIdx: number
  description: string
  vars: Record<string, unknown>
  cells: Record<string, ReportRow | undefined>
}

function colKey(row: ReportRow) {
  return `${row.promptIdx ?? 0}::${row.provider}::${row.prompt}`
}

function testKey(row: ReportRow) {
  return `${row.testIdx ?? row.id}::${JSON.stringify(row.vars || {})}`
}

function inputPreview(vars: Record<string, unknown>) {
  const entries = Object.entries(vars || {})
  if (!entries.length) return '—'
  if (entries.length === 1) return String(entries[0][1] ?? '—')
  return entries.map(([k, v]) => `${k}: ${v ?? '—'}`).join('\n')
}

function rowTone(row: ReportRow) {
  if (row.error) return 'error'
  if (row.success) return 'pass'
  return 'fail'
}

function resultBadge(row: ReportRow) {
  const asserts = row.assertions || []
  if (asserts.length) {
    const passed = asserts.filter((a) => a.pass).length
    if (row.error) return `${asserts.length} ERROR`
    if (row.success) return `${passed} PASS`
    return `${asserts.length - passed} FAIL`
  }
  if (row.error) return 'ERROR'
  if (row.success) return 'PASS'
  return 'FAIL'
}

function latencyText(ms?: number | null) {
  if (ms == null || Number.isNaN(Number(ms))) return ''
  return `Latency: ${Math.round(Number(ms))}ms`
}

function openDetail(row: ReportRow) {
  detailRow.value = row
  detailOpen.value = true
}

function shortPrompt(text: string, index: number) {
  const oneLine = text.replace(/\s+/g, ' ').trim()
  if (!oneLine) return `提示词 ${index + 1}`
  return oneLine.length > 28 ? `${oneLine.slice(0, 28)}…` : oneLine
}

const matrixColumns = computed<MatrixCol[]>(() => {
  const rows = report.value?.table || []
  const map = new Map<string, MatrixCol>()
  const promptOrder: string[] = []
  for (const row of rows) {
    const key = colKey(row)
    let col = map.get(key)
    if (!col) {
      if (!promptOrder.includes(row.prompt)) promptOrder.push(row.prompt)
      col = {
        key,
        prompt: row.prompt,
        promptLabel: shortPrompt(row.prompt, promptOrder.indexOf(row.prompt)),
        provider: row.provider,
        pass: 0,
        fail: 0,
        error: 0,
        total: 0,
        passRate: 0,
      }
      map.set(key, col)
    }
    col.total += 1
    if (row.error) col.error += 1
    else if (row.success) col.pass += 1
    else col.fail += 1
  }
  for (const col of map.values()) {
    const graded = col.pass + col.fail
    col.passRate = graded ? Math.round((col.pass / graded) * 10000) / 100 : 0
  }
  return Array.from(map.values())
})

const providerOptions = computed(() => {
  const names = Array.from(new Set(matrixColumns.value.map((c) => c.provider)))
  return [{ label: '全部供应商', value: 'all' }, ...names.map((n) => ({ label: n, value: n }))]
})

const promptOptions = computed(() => {
  const seen = new Map<string, { label: string; title: string }>()
  for (const col of matrixColumns.value) {
    if (draftProvider.value !== 'all' && col.provider !== draftProvider.value) continue
    if (!seen.has(col.prompt)) {
      const full = col.prompt.replace(/\s+/g, ' ').trim() || col.promptLabel
      seen.set(col.prompt, {
        // Closed select keeps a short label; dropdown option slot shows full text.
        label: col.promptLabel,
        title: full,
      })
    }
  }
  return [
    { label: '全部提示词', value: 'all', title: '全部提示词' },
    ...Array.from(seen.entries()).map(([value, meta]) => ({
      value,
      label: meta.label,
      title: meta.title,
    })),
  ]
})

const visibleMatrixColumns = computed(() =>
  matrixColumns.value.filter((col) => {
    if (selectedProvider.value !== 'all' && col.provider !== selectedProvider.value) return false
    if (selectedPrompt.value !== 'all' && col.prompt !== selectedPrompt.value) return false
    return true
  }),
)

const matrixRows = computed<MatrixRow[]>(() => {
  const rows = report.value?.table || []
  const map = new Map<string, MatrixRow>()
  for (const row of rows) {
    const key = testKey(row)
    let item = map.get(key)
    if (!item) {
      item = {
        key,
        testIdx: row.testIdx ?? row.id,
        description: row.description || `测试 ${((row.testIdx ?? row.id) as number) + 1}`,
        vars: row.vars || {},
        cells: {},
      }
      map.set(key, item)
    }
    item.cells[colKey(row)] = row
  }
  return Array.from(map.values()).sort((a, b) => a.testIdx - b.testIdx)
})

const filteredMatrixRows = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  const visibleKeys = new Set(visibleMatrixColumns.value.map((c) => c.key))
  return matrixRows.value.filter((row) => {
    const cells = visibleKeys.size
      ? (Object.entries(row.cells)
          .filter(([key]) => visibleKeys.has(key))
          .map(([, cell]) => cell)
          .filter(Boolean) as ReportRow[])
      : (Object.values(row.cells).filter(Boolean) as ReportRow[])
    if (filter.value === 'pass' && !cells.some((c) => c.success && !c.error)) return false
    if (filter.value === 'fail' && !cells.some((c) => !c.success && !c.error)) return false
    if (filter.value === 'error' && !cells.some((c) => !!c.error)) return false
    if (!q) return true
    const hay = `${row.description} ${inputPreview(row.vars)} ${cells
      .map((c) => `${c.provider} ${c.prompt} ${c.output}`)
      .join(' ')}`.toLowerCase()
    return hay.includes(q)
  })
})

const matrixTableColumns = computed(() => {
  const fixed = [
    { title: '测试项', key: 'description', dataIndex: 'description', width: 180, fixed: 'left' as const },
    { title: '输入', key: 'input', width: 220, fixed: 'left' as const },
  ]
  const dynamic = visibleMatrixColumns.value.map((col) => ({
    title: col.provider,
    key: col.key,
    width: 280,
  }))
  return [...fixed, ...dynamic]
})

const matrixColMap = computed(() => {
  const map = new Map<string, MatrixCol>()
  for (const col of visibleMatrixColumns.value) map.set(col.key, col)
  return map
})

function cellOf(record: MatrixRow, key: string | number) {
  return record.cells[String(key)]
}

function applyMatrixFilters() {
  filter.value = draftFilter.value
  keyword.value = draftKeyword.value
  selectedProvider.value = draftProvider.value
  selectedPrompt.value = draftPrompt.value
}

function resetMatrixFilters() {
  draftFilter.value = 'all'
  draftKeyword.value = ''
  draftProvider.value = 'all'
  draftPrompt.value = 'all'
  applyMatrixFilters()
}

function defaultProviderPrompt() {
  const cols = matrixColumns.value
  const providers = Array.from(new Set(cols.map((c) => c.provider)))
  const provider = providers[0] || 'all'
  return { provider, prompt: 'all' as const }
}

function syncMatrixFilters() {
  const cols = matrixColumns.value
  if (!cols.length) {
    draftProvider.value = 'all'
    draftPrompt.value = 'all'
    selectedProvider.value = 'all'
    selectedPrompt.value = 'all'
    matrixFiltersReady.value = false
    return
  }
  const providers = Array.from(new Set(cols.map((c) => c.provider)))
  if (!matrixFiltersReady.value) {
    const defaults = defaultProviderPrompt()
    draftProvider.value = defaults.provider
    draftPrompt.value = defaults.prompt
    draftFilter.value = 'all'
    draftKeyword.value = ''
    applyMatrixFilters()
    matrixFiltersReady.value = true
    return
  }
  if (draftProvider.value !== 'all' && !providers.includes(draftProvider.value)) {
    draftProvider.value = providers[0] || 'all'
  }
  if (selectedProvider.value !== 'all' && !providers.includes(selectedProvider.value)) {
    selectedProvider.value = providers[0] || 'all'
  }
  const draftPrompts = Array.from(
    new Set(
      cols
        .filter((c) => draftProvider.value === 'all' || c.provider === draftProvider.value)
        .map((c) => c.prompt),
    ),
  )
  if (draftPrompt.value !== 'all' && !draftPrompts.includes(draftPrompt.value)) {
    draftPrompt.value = 'all'
  }
  const appliedPrompts = Array.from(
    new Set(
      cols
        .filter((c) => selectedProvider.value === 'all' || c.provider === selectedProvider.value)
        .map((c) => c.prompt),
    ),
  )
  if (selectedPrompt.value !== 'all' && !appliedPrompts.includes(selectedPrompt.value)) {
    selectedPrompt.value = 'all'
  }
}

watch(matrixColumns, () => syncMatrixFilters(), { immediate: true })
watch(draftProvider, () => {
  if (!matrixFiltersReady.value) return
  const prompts = promptOptions.value.map((p) => p.value)
  if (draftPrompt.value !== 'all' && !prompts.includes(draftPrompt.value)) {
    draftPrompt.value = 'all'
  }
})

const pieOption = computed(() => {
  const s = report.value?.summary
  if (!s) return {}
  const stats = [
    { name: '通过', value: s.pass_count ?? 0, color: '#3d8b66' },
    { name: '失败', value: s.fail_count ?? 0, color: '#c45c5c' },
    { name: '错误', value: s.error_count ?? 0, color: '#b0893d' },
  ]
  const total = stats.reduce((sum, item) => sum + item.value, 0)
  const passRate = total ? Math.round(((s.pass_count ?? 0) / total) * 1000) / 10 : 0
  const pieData = stats
    .filter((item) => item.value > 0)
    .map((item) => ({
      name: item.name,
      value: item.value,
      itemStyle: { color: item.color },
    }))
  // Keep a full ring when every status is zero.
  const seriesData =
    pieData.length > 0
      ? pieData
      : [{ name: '暂无数据', value: 1, itemStyle: { color: '#d7dce5' }, tooltip: { show: false } }]

  return {
    animationDuration: 400,
    title: {
      text: total ? `${passRate}%` : '—',
      subtext: total ? `共 ${total} 条` : '暂无结果',
      left: 'center',
      top: '34%',
      textStyle: {
        fontSize: 26,
        fontWeight: 600,
        color: '#111827',
        fontFamily: 'IBM Plex Sans, sans-serif',
        lineHeight: 30,
      },
      subtextStyle: {
        fontSize: 12,
        color: '#6b7487',
        fontFamily: 'IBM Plex Sans, sans-serif',
        lineHeight: 18,
      },
      itemGap: 4,
    },
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: '#fff',
      borderColor: 'rgba(17,24,39,0.08)',
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: '#4b5565', fontSize: 12 },
      extraCssText: 'box-shadow: 0 4px 14px rgba(17,24,39,0.08); border-radius: 8px;',
      formatter: (p: { name: string; value: number; percent: number; color: string }) => {
        if (p.name === '暂无数据') return ''
        return `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.color};margin-right:6px;"></span>${p.name}<br/><span style="margin-left:14px">${p.value} 条 · ${p.percent}%</span>`
      },
    },
    legend: {
      bottom: 4,
      left: 'center',
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      itemGap: 18,
      textStyle: { color: '#4b5565', fontSize: 12, fontFamily: 'IBM Plex Sans, sans-serif' },
      data: stats.map((item) => ({
        name: item.name,
        itemStyle: { color: item.color },
      })),
      formatter: (name: string) => {
        const item = stats.find((d) => d.name === name)
        if (!item) return name
        const pct = total ? Math.round((item.value / total) * 1000) / 10 : 0
        return `${name}  ${item.value} · ${pct}%`
      },
    },
    series: [
      {
        name: '结果分布',
        type: 'pie',
        radius: ['54%', '74%'],
        center: ['50%', '44%'],
        silent: total === 0,
        stillShowZeroSum: false,
        avoidLabelOverlap: true,
        data: seriesData,
        label: { show: false },
        labelLine: { show: false },
        itemStyle: {
          borderColor: '#fff',
          borderWidth: 2,
        },
        emphasis: {
          scale: total > 0,
          scaleSize: 3,
          itemStyle: {
            shadowBlur: 0,
          },
        },
      },
    ],
  }
})

const barOption = computed(() => {
  const items = report.value?.by_provider || []
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 16, top: 24, bottom: 40 },
    xAxis: {
      type: 'category',
      data: items.map((i) => i.name),
      axisLabel: { interval: 0, rotate: items.length > 3 ? 20 : 0, color: '#6b7487' },
      axisLine: { lineStyle: { color: 'rgba(17,24,39,0.12)' } },
    },
    yAxis: {
      type: 'value',
      max: 100,
      axisLabel: { formatter: '{value}%', color: '#6b7487' },
      splitLine: { lineStyle: { color: 'rgba(17,24,39,0.06)' } },
    },
    series: [
      {
        type: 'bar',
        data: items.map((i) => i.pass_rate),
        itemStyle: { color: '#0f766e', borderRadius: [4, 4, 0, 0] },
        barWidth: 28,
      },
    ],
  }
})

async function load() {
  const id = String(route.params.id || '').trim()
  if (!id) {
    message.error('缺少运行 ID')
    router.push('/runs')
    return
  }
  loading.value = true
  report.value = null
  matrixFiltersReady.value = false
  draftFilter.value = 'all'
  draftKeyword.value = ''
  draftProvider.value = 'all'
  draftPrompt.value = 'all'
  filter.value = 'all'
  keyword.value = ''
  selectedProvider.value = 'all'
  selectedPrompt.value = 'all'
  try {
    run.value = await api.getRun(id)
    if (run.value.status === 'succeeded') {
      report.value = await api.getReport(id)
    }
  } catch (err: any) {
    const status = err?.response?.status
    const detail = err?.response?.data?.detail
    message.error(status === 404 ? '运行不存在' : detail || '加载报告失败')
    run.value = null
    report.value = null
    router.push('/runs')
  } finally {
    loading.value = false
  }
}

function reportFileUrl(kind: 'json' | 'html' | 'csv') {
  return `/api/runs/${route.params.id}/report.${kind}`
}

function download(kind: 'json' | 'html' | 'csv') {
  const url = reportFileUrl(kind)
  // Always open in a new tab. Never navigate the SPA away to /api/... (that breaks back/refresh).
  const opened = window.open(url, '_blank', 'noopener,noreferrer')
  if (!opened) {
    message.warning('浏览器拦截了新窗口，请允许弹窗后重试')
  }
}

onMounted(() => {
  load()
  timer = window.setInterval(async () => {
    if (!run.value) return
    if (run.value.status === 'pending' || run.value.status === 'running') {
      try {
        run.value = await api.getRun(String(route.params.id))
        if (run.value.status === 'succeeded') {
          report.value = await api.getReport(String(route.params.id))
        }
      } catch {
        // keep polling until user leaves
      }
    }
  }, 2000)
})

watch(
  () => String(route.params.id || ''),
  (id, prev) => {
    if (id && id !== prev) load()
  },
)

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>测评报告</h1>
        <p>
          <span class="mono">{{ route.params.id }}</span>
          <span class="sep">·</span>
          {{ run?.config_name }}
        </p>
      </div>
      <a-space>
        <a-button @click="router.push('/runs')">返回</a-button>
        <a-button :disabled="run?.status !== 'succeeded'" @click="download('json')">JSON</a-button>
        <a-button :disabled="run?.status !== 'succeeded'" @click="download('csv')">CSV</a-button>
        <a-button type="primary" :disabled="run?.status !== 'succeeded'" @click="download('html')">
          HTML
        </a-button>
      </a-space>
    </div>

    <a-spin :spinning="loading">
      <div class="report-body">
        <div class="panel meta" v-if="run">
          <div class="meta-row">
            <StatusTag :status="run.status" />
            <span class="meta-item">
              通过率
              <strong class="mono accent">{{ run.pass_rate }}%</strong>
            </span>
            <span class="meta-item mono">
              {{ run.pass_count }} 通过 / {{ run.fail_count }} 失败 / {{ run.error_count }} 错误
            </span>
            <span v-if="run.duration_ms" class="meta-item mono">
              {{ (run.duration_ms / 1000).toFixed(1) }}s
            </span>
            <span class="meta-item mono muted">
              {{ dayjs(run.created_at).format('YYYY-MM-DD HH:mm:ss') }}
            </span>
          </div>
          <a-alert
            v-if="run.status === 'failed'"
            class="meta-alert"
            type="error"
            show-icon
            :message="run.error || '测评失败'"
          />
          <a-alert
            v-if="run.status === 'running' || run.status === 'pending'"
            class="meta-alert"
            type="info"
            show-icon
            message="测评进行中，页面会自动刷新"
          />
        </div>

        <template v-if="report">
          <div class="charts">
            <div class="panel">
              <div class="section-title">结果分布</div>
              <VChart class="chart" :option="pieOption" autoresize />
            </div>
            <div class="panel">
              <div class="section-title">Provider 通过率</div>
              <VChart class="chart" :option="barOption" autoresize />
            </div>
          </div>

          <div class="panel detail-panel">
            <div class="section-title">详细结果</div>
            <div class="filter-bar">
              <a-input
                v-model:value="draftKeyword"
                allow-clear
                placeholder="搜索测试项 / 输入 / 输出"
                class="filter-search"
                @pressEnter="applyMatrixFilters"
              />
              <a-select
                v-model:value="draftFilter"
                :options="resultFilterOptions"
                class="filter-select"
                placeholder="测试结果"
              />
              <a-select
                v-model:value="draftProvider"
                :options="providerOptions"
                class="filter-select"
                placeholder="全部供应商"
              />
              <a-select
                v-model:value="draftPrompt"
                :options="promptOptions"
                class="filter-select filter-select-prompt"
                placeholder="全部提示词"
                option-label-prop="label"
                popup-class-name="prompt-filter-dropdown"
                :dropdown-match-select-width="false"
                :dropdown-style="{ minWidth: '420px', maxWidth: '560px' }"
              >
                <template #option="{ value, label, title }">
                  <div v-if="value === 'all'">{{ label }}</div>
                  <div v-else class="prompt-option-full">{{ title || value }}</div>
                </template>
              </a-select>
              <a-space :size="8">
                <a-button type="primary" @click="applyMatrixFilters">查询</a-button>
                <a-button @click="resetMatrixFilters">重置</a-button>
              </a-space>
            </div>

            <a-table
              class="detail-table"
              :columns="matrixTableColumns"
              :data-source="filteredMatrixRows"
              row-key="key"
              :scroll="{ x: 180 + 220 + Math.max(visibleMatrixColumns.length, 1) * 280 }"
              :pagination="{ pageSize: 10, showTotal: (total: number) => `共 ${total} 条` }"
            >
              <template #headerCell="{ column }">
                <template v-if="matrixColMap.get(String(column.key))">
                  <div class="col-head">
                    <div class="col-provider">{{ matrixColMap.get(String(column.key))!.provider }}</div>
                    <div
                      class="col-rate mono"
                      :class="{
                        ok: matrixColMap.get(String(column.key))!.passRate >= 80,
                        bad: matrixColMap.get(String(column.key))!.passRate < 50,
                      }"
                    >
                      {{ matrixColMap.get(String(column.key))!.passRate.toFixed(2) }}% passing
                      ({{ matrixColMap.get(String(column.key))!.pass }}/{{ matrixColMap.get(String(column.key))!.total }})
                    </div>
                    <div class="col-prompt">{{ matrixColMap.get(String(column.key))!.prompt }}</div>
                  </div>
                </template>
              </template>
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'description'">
                  <div class="case-title">{{ record.description || '—' }}</div>
                </template>
                <template v-else-if="column.key === 'input'">
                  <div class="vars-cell mono">{{ inputPreview(record.vars) }}</div>
                </template>
                <template v-else-if="cellOf(record, column.key)">
                  <div class="result-card">
                    <div class="result-top">
                      <span class="result-badge" :class="rowTone(cellOf(record, column.key)!)">
                        {{ resultBadge(cellOf(record, column.key)!) }}
                      </span>
                      <a
                        class="detail-link"
                        href="#"
                        @click.prevent="openDetail(cellOf(record, column.key)!)"
                      >
                        详情
                      </a>
                    </div>
                    <div class="result-output">
                      {{
                        cellOf(record, column.key)!.output ||
                        cellOf(record, column.key)!.error ||
                        cellOf(record, column.key)!.reason ||
                        '—'
                      }}
                    </div>
                    <div class="result-meta mono">
                      <span v-if="latencyText(cellOf(record, column.key)!.latencyMs)">
                        {{ latencyText(cellOf(record, column.key)!.latencyMs) }}
                      </span>
                      <span v-if="cellOf(record, column.key)!.score != null">
                        Score: {{ cellOf(record, column.key)!.score }}
                      </span>
                    </div>
                  </div>
                </template>
                <span v-else class="muted">—</span>
              </template>
            </a-table>
          </div>
        </template>

        <div class="panel" v-if="run?.stderr">
          <div class="section-title">执行日志</div>
          <pre class="log mono">{{ run.stderr }}</pre>
        </div>
      </div>
    </a-spin>

    <a-drawer
      v-model:open="detailOpen"
      :width="480"
      :title="detailRow ? `结果详情 #${detailRow.id + 1}` : '结果详情'"
      destroy-on-close
    >
      <div v-if="detailRow" class="drawer-body">
        <div class="field">
          <label>状态</label>
          <span class="result-badge" :class="rowTone(detailRow)">{{ resultBadge(detailRow) }}</span>
        </div>
        <div class="field">
          <label>测试项</label>
          <div>{{ detailRow.description || '—' }}</div>
        </div>
        <div class="field">
          <label>Prompt</label>
          <div class="mono">{{ detailRow.prompt }}</div>
        </div>
        <div class="field">
          <label>Provider</label>
          <div class="mono">{{ detailRow.provider }}</div>
        </div>
        <div class="field">
          <label>变量</label>
          <pre class="block mono">{{ JSON.stringify(detailRow.vars || {}, null, 2) }}</pre>
        </div>
        <div class="field">
          <label>输出</label>
          <pre class="block">{{ detailRow.output || detailRow.error || '—' }}</pre>
        </div>
        <div class="field meta-inline">
          <span v-if="latencyText(detailRow.latencyMs)" class="mono muted">{{ latencyText(detailRow.latencyMs) }}</span>
          <span v-if="detailRow.score != null" class="mono muted">Score: {{ detailRow.score }}</span>
        </div>
        <div class="field">
          <label>断言</label>
          <div v-if="detailRow.assertions?.length" class="assert-list">
            <div v-for="(a, idx) in detailRow.assertions" :key="idx" class="assert-line">
              <span class="assert-type" :class="a.pass ? 'ok' : 'fail'">{{ a.type || 'assert' }}</span>
              <span>{{ a.reason || (a.pass ? '通过' : '未通过') }}</span>
            </div>
          </div>
          <div v-else class="muted">{{ detailRow.reason || '暂无断言详情' }}</div>
        </div>
      </div>
    </a-drawer>
  </div>
</template>

<style scoped>
.sep {
  margin: 0 6px;
  color: var(--ek-muted);
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
}

.meta-item {
  font-size: 13px;
  color: var(--ek-secondary);
}

.meta-item strong {
  font-weight: 500;
  margin-left: 4px;
}

.meta-item .accent {
  color: var(--ek-accent-ink);
}

.meta-item.muted {
  color: var(--ek-muted);
}

.report-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.meta-alert {
  margin-top: 12px;
}

.charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.chart {
  height: 240px;
}

.detail-panel {
  padding-top: 16px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 12px;
  flex-wrap: wrap;
}

.filter-search {
  width: 220px;
}

.filter-select {
  width: 150px;
}

.filter-select-prompt {
  width: 240px;
}

.detail-table :deep(.ant-table-thead > tr > th) {
  font-size: 12px;
  font-weight: 500;
  color: var(--ek-muted);
  background: var(--ek-raised);
  padding: 10px 12px;
  vertical-align: top;
}

.detail-table :deep(.ant-table-tbody > tr > td) {
  padding: 12px;
  vertical-align: top;
  border-bottom: 1px solid rgba(17, 24, 39, 0.06);
}

.col-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.col-provider {
  font-size: 13px;
  font-weight: 500;
  color: var(--ek-ink);
}

.col-rate {
  font-size: 11px;
  color: var(--ek-secondary);
}

.col-rate.ok {
  color: var(--ek-ok);
}

.col-rate.bad {
  color: var(--ek-danger);
}

.col-prompt {
  font-size: 11px;
  color: var(--ek-muted);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.case-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--ek-ink);
  line-height: 1.4;
}

.vars-cell {
  font-size: 12px;
  color: var(--ek-secondary);
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

.result-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.result-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.result-badge {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  line-height: 1;
}

.result-badge.pass {
  color: #166534;
  background: rgba(22, 163, 74, 0.12);
}

.result-badge.fail {
  color: #991b1b;
  background: rgba(220, 38, 38, 0.12);
}

.result-badge.error {
  color: #92400e;
  background: rgba(161, 98, 7, 0.12);
}

.detail-link {
  font-size: 12px;
  flex-shrink: 0;
}

.result-output {
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 96px;
  overflow: auto;
  font-size: 13px;
  line-height: 1.5;
  color: var(--ek-ink);
}

.result-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  font-size: 11px;
  color: var(--ek-muted);
}

.drawer-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-size: 12px;
  color: var(--ek-muted);
}

.block {
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: var(--ek-raised);
  border: 1px solid var(--ek-border);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.5;
  max-height: 220px;
  overflow: auto;
}

.meta-inline {
  flex-direction: row;
  gap: 12px;
}

.assert-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.assert-line {
  color: var(--ek-muted);
  font-size: 13px;
  display: flex;
  gap: 8px;
  align-items: baseline;
}

.assert-type {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 12px;
  color: var(--ek-secondary);
  flex-shrink: 0;
}

.assert-type.ok {
  color: var(--ek-ok);
}

.assert-type.fail {
  color: var(--ek-danger);
}

.muted {
  color: var(--ek-muted);
}

.log {
  margin: 0;
  max-height: 240px;
  overflow: auto;
  background: var(--ek-ink);
  color: #e5e7eb;
  padding: 14px 16px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 960px) {
  .charts {
    grid-template-columns: 1fr;
  }
}
</style>

<style>
.prompt-filter-dropdown.ant-select-dropdown {
  max-width: min(560px, 92vw);
}

.prompt-filter-dropdown .ant-select-item {
  height: auto !important;
  min-height: 32px;
  padding-top: 8px;
  padding-bottom: 8px;
  white-space: normal;
  line-height: 1.45;
}

.prompt-filter-dropdown .ant-select-item-option-content {
  white-space: normal;
  word-break: break-word;
  overflow: visible;
  text-overflow: unset;
}

.prompt-option-full {
  white-space: normal;
  word-break: break-word;
  line-height: 1.45;
  color: var(--ek-ink, #111827);
}
</style>
