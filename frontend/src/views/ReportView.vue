<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import type { MenuProps } from 'ant-design-vue'
import { ArrowLeftOutlined, DownOutlined } from '@ant-design/icons-vue'
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
const canDownload = computed(() => {
  if (!run.value) return false
  if (run.value.status === 'pending' || run.value.status === 'running') return false
  return Boolean(run.value.total_count || run.value.report_json_url || run.value.report_html_url)
})
type ResultFilter = 'all' | 'pass' | 'fail' | 'error'

const filter = ref<ResultFilter>('all')
const keyword = ref('')
const selectedProvider = ref<string[]>([])
const selectedPrompt = ref<string[]>([])
const draftFilter = ref<ResultFilter>('all')
const draftKeyword = ref('')
const draftProvider = ref<string[]>([])
const draftPrompt = ref<string[]>([])
const matrixFiltersReady = ref(false)
const detailOpen = ref(false)
const detailRow = ref<ReportRow | null>(null)
const matrixPage = ref(1)
const matrixPageSize = 10
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
  return oneLine.length > 8 ? `${oneLine.slice(0, 8)}...` : oneLine
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
  return names.map((n) => ({ label: n, value: n, title: n }))
})

const promptOptions = computed(() => {
  const seen = new Map<string, { label: string; full: string }>()
  for (const col of matrixColumns.value) {
    if (draftProvider.value.length && !draftProvider.value.includes(col.provider)) continue
    if (!seen.has(col.prompt)) {
      const full = col.prompt.replace(/\s+/g, ' ').trim() || col.promptLabel
      seen.set(col.prompt, {
        label: shortPrompt(full, 0),
        full,
      })
    }
  }
  return Array.from(seen.entries()).map(([value, meta]) => ({
    value,
    label: meta.label,
    full: meta.full,
    title: meta.full,
  }))
})

const visibleMatrixColumns = computed(() =>
  matrixColumns.value.filter((col) => {
    if (selectedProvider.value.length && !selectedProvider.value.includes(col.provider)) return false
    if (selectedPrompt.value.length && !selectedPrompt.value.includes(col.prompt)) return false
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

const matrixTotal = computed(() => filteredMatrixRows.value.length)

const pagedMatrixRows = computed(() => {
  const start = (matrixPage.value - 1) * matrixPageSize
  return filteredMatrixRows.value.slice(start, start + matrixPageSize)
})

const matrixScrollX = computed(
  () => 180 + 220 + Math.max(visibleMatrixColumns.value.length, 1) * 280,
)

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
  selectedProvider.value = [...draftProvider.value]
  selectedPrompt.value = [...draftPrompt.value]
  matrixPage.value = 1
}

function clampMatrixPage() {
  const maxPage = Math.max(1, Math.ceil(matrixTotal.value / matrixPageSize) || 1)
  if (matrixPage.value > maxPage) matrixPage.value = maxPage
}

watch(matrixTotal, () => clampMatrixPage())

function resetMatrixFilters() {
  draftFilter.value = 'all'
  draftKeyword.value = ''
  draftProvider.value = []
  draftPrompt.value = []
  applyMatrixFilters()
}

function pruneSelection(selected: string[], allowed: string[]) {
  if (!selected.length) return []
  return selected.filter((item) => allowed.includes(item))
}

function multiSelectSummary(omitted: unknown[] | undefined, selectedCount: number) {
  const extra = Array.isArray(omitted) ? omitted.length : 0
  const total = selectedCount || extra
  return total > 1 ? `已选 ${total}` : `+${extra}`
}

function syncMatrixFilters() {
  const cols = matrixColumns.value
  if (!cols.length) {
    draftProvider.value = []
    draftPrompt.value = []
    selectedProvider.value = []
    selectedPrompt.value = []
    matrixFiltersReady.value = false
    return
  }
  const providers = Array.from(new Set(cols.map((c) => c.provider)))
  if (!matrixFiltersReady.value) {
    draftProvider.value = []
    draftPrompt.value = []
    draftFilter.value = 'all'
    draftKeyword.value = ''
    applyMatrixFilters()
    matrixFiltersReady.value = true
    return
  }
  draftProvider.value = pruneSelection(draftProvider.value, providers)
  selectedProvider.value = pruneSelection(selectedProvider.value, providers)
  const draftAllowed = Array.from(
    new Set(
      cols
        .filter((c) => !draftProvider.value.length || draftProvider.value.includes(c.provider))
        .map((c) => c.prompt),
    ),
  )
  draftPrompt.value = pruneSelection(draftPrompt.value, draftAllowed)
  const appliedAllowed = Array.from(
    new Set(
      cols
        .filter((c) => !selectedProvider.value.length || selectedProvider.value.includes(c.provider))
        .map((c) => c.prompt),
    ),
  )
  selectedPrompt.value = pruneSelection(selectedPrompt.value, appliedAllowed)
}

watch(matrixColumns, () => syncMatrixFilters(), { immediate: true })
watch(draftProvider, () => {
  if (!matrixFiltersReady.value) return
  const allowed = promptOptions.value.map((p) => p.value)
  draftPrompt.value = pruneSelection(draftPrompt.value, allowed)
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
  draftProvider.value = []
  draftPrompt.value = []
  filter.value = 'all'
  keyword.value = ''
  selectedProvider.value = []
  selectedPrompt.value = []
  try {
    run.value = await api.getRun(id)
    if (run.value.status === 'succeeded' || run.value.status === 'failed') {
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

const onExportMenuClick: MenuProps['onClick'] = ({ key }) => {
  if (key === 'json' || key === 'csv' || key === 'html') {
    download(key)
  }
}

function popupContainer() {
  return document.body
}

onMounted(() => {
  load()
  timer = window.setInterval(async () => {
    if (!run.value) return
    if (run.value.status === 'pending' || run.value.status === 'running') {
      try {
        run.value = await api.getRun(String(route.params.id))
        if (run.value.status === 'succeeded' || run.value.status === 'failed') {
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
  <div class="page report-page">
    <div class="page-spin">
      <a-spin :spinning="loading">
      <div class="report-body">
        <div class="panel meta" v-if="run">
          <div class="meta-row">
            <div class="meta-main">
              <a-tooltip title="返回列表">
                <a-button type="text" class="back-btn" @click="router.push('/runs')">
                  <ArrowLeftOutlined />
                </a-button>
              </a-tooltip>
              <span class="task-name" :title="run.config_name">{{ run.config_name || '未命名任务' }}</span>
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
            <div class="export-wrap">
              <a-dropdown
                :disabled="!canDownload"
                :trigger="['click']"
                placement="bottomRight"
                :get-popup-container="popupContainer"
              >
                <a-button type="primary">
                  导出
                  <DownOutlined />
                </a-button>
                <template #overlay>
                  <a-menu @click="onExportMenuClick">
                    <a-menu-item key="json">导出 JSON</a-menu-item>
                    <a-menu-item key="csv">导出 CSV</a-menu-item>
                    <a-menu-item key="html">导出 HTML</a-menu-item>
                  </a-menu>
                </template>
              </a-dropdown>
            </div>
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
              <div class="section-title">供应商通过率</div>
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
                mode="multiple"
                allow-clear
                show-search
                :max-tag-count="1"
                :max-tag-text-length="8"
                :options="providerOptions"
                class="filter-select filter-select-multi"
                placeholder="全部供应商"
                option-filter-prop="label"
              >
                <template #maxTagPlaceholder="omittedValues">
                  <span class="multi-more">{{ multiSelectSummary(omittedValues, draftProvider.length) }}</span>
                </template>
              </a-select>
              <a-select
                v-model:value="draftPrompt"
                mode="multiple"
                allow-clear
                show-search
                :max-tag-count="1"
                :options="promptOptions"
                class="filter-select filter-select-multi"
                placeholder="全部提示词"
                option-label-prop="label"
                option-filter-prop="label"
                popup-class-name="prompt-filter-dropdown"
              >
                <template #option="{ value, label, full }">
                  <a-tooltip placement="right" :overlay-style="{ maxWidth: '420px' }">
                    <template #title>
                      <div class="prompt-tooltip-full">{{ full || value }}</div>
                    </template>
                    <span class="prompt-option-short">{{ label }}</span>
                  </a-tooltip>
                </template>
                <template #maxTagPlaceholder="omittedValues">
                  <span class="multi-more">{{ multiSelectSummary(omittedValues, draftPrompt.length) }}</span>
                </template>
              </a-select>
              <a-space :size="8">
                <a-button type="primary" @click="applyMatrixFilters">查询</a-button>
                <a-button @click="resetMatrixFilters">重置</a-button>
              </a-space>
            </div>

            <div class="detail-body">
              <div class="table-scroll">
                <a-table
                  class="detail-table"
                  :columns="matrixTableColumns"
                  :data-source="pagedMatrixRows"
                  row-key="key"
                  :scroll="{ x: matrixScrollX }"
                  :pagination="false"
                >
                  <template #headerCell="{ column }">
                    <template v-if="matrixColMap.get(String(column.key))">
                      <div class="col-head">
                        <div class="col-provider">{{ matrixColMap.get(String(column.key))!.provider }}</div>
                        <a-tooltip
                          placement="topLeft"
                          :overlay-style="{ maxWidth: '420px' }"
                        >
                          <template #title>
                            <div class="prompt-tooltip-full">
                              {{ matrixColMap.get(String(column.key))!.prompt }}
                            </div>
                          </template>
                          <div class="col-prompt">
                            {{ matrixColMap.get(String(column.key))!.promptLabel }}
                          </div>
                        </a-tooltip>
                        <div
                          class="col-rate mono"
                          :class="{
                            ok: matrixColMap.get(String(column.key))!.passRate >= 80,
                            bad: matrixColMap.get(String(column.key))!.passRate < 50,
                          }"
                        >
                          {{ matrixColMap.get(String(column.key))!.passRate.toFixed(2) }}% pass
                          ({{ matrixColMap.get(String(column.key))!.pass }}/{{ matrixColMap.get(String(column.key))!.total }})
                        </div>
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
              <div class="pager">
                <a-pagination
                  v-model:current="matrixPage"
                  :total="matrixTotal"
                  :page-size="matrixPageSize"
                  size="small"
                  show-less-items
                  :show-total="(total: number) => `共 ${total} 条`"
                />
              </div>
            </div>
          </div>
        </template>

        <div class="panel" v-if="run?.stderr">
          <div class="section-title">执行日志</div>
          <pre class="log mono">{{ run.stderr }}</pre>
        </div>
      </div>
      </a-spin>
    </div>

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
.back-btn {
  width: 28px;
  height: 28px;
  padding: 0;
  margin-right: -4px;
  color: var(--ek-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.back-btn:hover {
  color: var(--ek-ink);
}

.task-name {
  max-width: 220px;
  font-size: 14px;
  font-weight: 500;
  color: var(--ek-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
}

.meta-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  min-width: 0;
}

.export-wrap {
  flex-shrink: 0;
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

.report-page {
  height: 100%;
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.page-spin {
  flex: 1;
  min-height: 0;
  height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.page-spin :deep(.ant-spin-nested-loading),
.page-spin :deep(.ant-spin-container) {
  flex: 1;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.report-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.report-body > .meta,
.report-body > .charts {
  flex: 0 0 auto;
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
  height: 220px;
}

.detail-panel {
  padding: 20px 24px 0;
  flex: 1 1 auto;
  min-height: 0;
  height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.detail-panel .section-title,
.detail-panel .filter-bar {
  flex: 0 0 auto;
}

.detail-body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.table-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.pager {
  flex: 0 0 auto;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  min-height: 40px;
  padding: 12px 0;
  margin-top: 8px;
  border-top: 1px solid var(--ek-border);
  background: var(--ek-surface);
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

.filter-select-multi {
  width: 150px;
}

.filter-select-multi :deep(.ant-select-selector) {
  align-items: center;
  padding-inline: 8px !important;
}

.filter-select-multi :deep(.ant-select-selection-overflow) {
  flex-wrap: nowrap;
  overflow: hidden;
}

.filter-select-multi :deep(.ant-select-selection-item) {
  max-width: 72px;
  margin-inline-end: 4px !important;
  height: 22px !important;
  line-height: 20px !important;
  border: none !important;
  background: var(--ek-raised) !important;
  border-radius: 4px !important;
  font-size: 12px;
}

.filter-select-multi :deep(.ant-select-selection-item-content) {
  overflow: hidden;
  text-overflow: ellipsis;
}

.filter-select-multi :deep(.ant-select-selection-placeholder) {
  inset-inline-start: 8px !important;
}

.detail-table {
  width: 100%;
}

.detail-table :deep(.ant-table) {
  width: 100% !important;
  background: transparent;
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
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
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
  width: 100%;
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
.prompt-option-short {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.prompt-tooltip-full {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.45;
  max-width: 400px;
}

.multi-more {
  font-size: 12px;
  color: var(--ek-secondary, #4b5565);
}
</style>
