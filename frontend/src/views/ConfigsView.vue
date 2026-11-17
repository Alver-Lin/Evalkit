<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import dayjs from 'dayjs'
import { api } from '@/api/client'
import StatusTag from '@/components/StatusTag.vue'
import type { ConfigMeta, EvalRunSummary } from '@/types'
import { visualToYaml, yamlToVisual } from '@/utils/promptfooConfig'

const router = useRouter()
const loading = ref(false)
const configs = ref<ConfigMeta[]>([])
const runs = ref<EvalRunSummary[]>([])
const page = ref(1)
const pageSize = 10
const open = ref(false)
const form = reactive({
  name: '',
  description: '',
})

type ResultFilter = 'all' | 'succeeded' | 'failed' | 'running' | 'pending' | 'none'
const draftKeyword = ref('')
const draftResult = ref<ResultFilter>('all')
const keyword = ref('')
const resultFilter = ref<ResultFilter>('all')

const resultFilterOptions = [
  { label: '全部结果', value: 'all' },
  { label: '成功', value: 'succeeded' },
  { label: '失败', value: 'failed' },
  { label: '运行中', value: 'running' },
  { label: '等待中', value: 'pending' },
  { label: '暂无运行', value: 'none' },
]

const panelRef = ref<HTMLElement | null>(null)
const bodyHeight = ref(pageSize * 56)
let resizeObserver: ResizeObserver | null = null

const rowHeight = computed(() => Math.max(48, bodyHeight.value / pageSize))
const scrollY = computed(() => Math.max(pageSize * 48, Math.floor(rowHeight.value * pageSize)))
const panelStyle = computed(() => ({ '--row-h': `${rowHeight.value}px` }))

const columns = [
  { title: '序号', key: 'index', width: 72 },
  { title: '任务名称', dataIndex: 'name', key: 'name', width: 200, ellipsis: true },
  { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: '运行结果', key: 'result', width: 200 },
  { title: '更新时间', key: 'updated_at', width: 148 },
  { title: '操作', key: 'actions', width: 148 },
]

const latestRunByConfig = computed(() => {
  const map = new Map<string, EvalRunSummary>()
  for (const run of runs.value) {
    const prev = map.get(run.config_id)
    if (!prev || dayjs(run.created_at).isAfter(dayjs(prev.created_at))) {
      map.set(run.config_id, run)
    }
  }
  return map
})

const filteredConfigs = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return configs.value.filter((cfg) => {
    const run = latestRunByConfig.value.get(cfg.id)
    if (resultFilter.value === 'none' && run) return false
    if (resultFilter.value !== 'all' && resultFilter.value !== 'none') {
      if (!run || run.status !== resultFilter.value) return false
    }
    if (!q) return true
    const hay = `${cfg.name} ${cfg.description || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

function applyFilters() {
  keyword.value = draftKeyword.value
  resultFilter.value = draftResult.value
  page.value = 1
  nextTick(measureBody)
}

function resetFilters() {
  draftKeyword.value = ''
  draftResult.value = 'all'
  applyFilters()
}

function buildDefaultYaml(description: string) {
  const escaped = description.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
  return `description: "${escaped}"

prompts:
  - ""

providers:
  - id: ""
    label: ""

tests: []
`
}

function measureBody() {
  const panel = panelRef.value
  if (!panel) return
  const toolbar = panel.querySelector('.panel-toolbar') as HTMLElement | null
  const thead = panel.querySelector('.ant-table-thead') as HTMLElement | null
  const pager = panel.querySelector('.ant-pagination') as HTMLElement | null
  const styles = getComputedStyle(panel)
  const padY = (parseFloat(styles.paddingTop) || 0) + (parseFloat(styles.paddingBottom) || 0)
  const toolbarH = toolbar ? toolbar.offsetHeight + 12 : 0
  const headH = thead?.offsetHeight || 40
  const pagerH = pager ? pager.offsetHeight + 8 : 40
  const next = Math.floor(panel.clientHeight - padY - toolbarH - headH - pagerH)
  if (next > 0) bodyHeight.value = next
}

async function load() {
  loading.value = true
  try {
    const [configList, runList] = await Promise.all([api.listConfigs(), api.listRuns()])
    configs.value = configList
    runs.value = runList
  } finally {
    loading.value = false
    await nextTick()
    measureBody()
  }
}

function onPageChange(next: number) {
  page.value = next
  nextTick(measureBody)
}

function rowIndex(index: number) {
  return (page.value - 1) * pageSize + index + 1
}

function latestRun(configId: string) {
  return latestRunByConfig.value.get(configId)
}

function resultLabel(run: EvalRunSummary) {
  if ((run.status === 'succeeded' || run.status === 'failed') && run.total_count) {
    return `${run.pass_rate}% · ${run.pass_count}/${run.total_count}`
  }
  if (run.status === 'failed') return '失败'
  if (run.status === 'running') return '运行中'
  if (run.status === 'pending') return '等待中'
  return ''
}

async function createConfig() {
  if (!form.name.trim()) {
    message.warning('请填写名称')
    return
  }
  try {
    const created = await api.createConfig({
      name: form.name,
      description: form.description,
      yaml_content: buildDefaultYaml(form.description),
    })
    message.success('配置已创建')
    open.value = false
    form.name = ''
    form.description = ''
    await load()
    router.push(`/configs/${created.id}`)
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '创建失败')
  }
}

function copyName(name: string) {
  const base = name.trim() || '未命名任务'
  const suffix = ' (副本)'
  const maxLen = 120
  if (base.length + suffix.length <= maxLen) return `${base}${suffix}`
  return `${base.slice(0, Math.max(1, maxLen - suffix.length))}${suffix}`
}

async function copyConfig(record: ConfigMeta) {
  try {
    const source = await api.getConfig(record.id)
    const visual = yamlToVisual(source.yaml_content, source.description || '')
    const description = (source.description || '').trim() || visual.description || ''
    visual.description = description
    const created = await api.createConfig({
      name: copyName(source.name),
      description,
      yaml_content: visualToYaml(visual, source.yaml_content),
      max_concurrency: source.max_concurrency ?? 2,
      cache: Boolean(source.cache),
    })
    message.success('已复制')
    await load()
    router.push(`/configs/${created.id}`)
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '复制失败')
  }
}

function confirmDelete(record: ConfigMeta) {
  Modal.confirm({
    title: `删除配置「${record.name}」？`,
    content: '此操作不可恢复',
    okText: '确认',
    cancelText: '取消',
    okType: 'danger',
    async onOk() {
      await api.deleteConfig(record.id)
      message.success('已删除')
      await load()
    },
  })
}

onMounted(async () => {
  await load()
  await nextTick()
  measureBody()
  resizeObserver = new ResizeObserver(() => measureBody())
  if (panelRef.value) resizeObserver.observe(panelRef.value)
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div class="page list-page">
    <div ref="panelRef" class="panel table-panel" :style="panelStyle">
      <div class="panel-toolbar">
        <div class="panel-toolbar-main">
          <h1 class="panel-title">测评任务</h1>
          <div class="filter-bar">
            <a-input
              v-model:value="draftKeyword"
              allow-clear
              placeholder="搜索名称 / 描述"
              class="filter-search"
              @pressEnter="applyFilters"
            />
            <a-select
              v-model:value="draftResult"
              :options="resultFilterOptions"
              class="filter-select"
              placeholder="运行结果"
            />
            <a-space :size="8">
              <a-button type="primary" @click="applyFilters">查询</a-button>
              <a-button @click="resetFilters">重置</a-button>
            </a-space>
          </div>
        </div>
        <a-button type="primary" @click="open = true">新建配置</a-button>
      </div>

      <a-table
        class="config-table"
        :columns="columns"
        :data-source="filteredConfigs"
        :loading="loading"
        row-key="id"
        :scroll="{ y: scrollY }"
        :pagination="{
          current: page,
          pageSize,
          hideOnSinglePage: false,
          showSizeChanger: false,
          showTotal: (total: number) => `共 ${total} 条`,
          onChange: onPageChange,
        }"
      >
        <template #bodyCell="{ column, record, index }">
          <template v-if="column.key === 'index'">
            <span class="mono idx">{{ rowIndex(index) }}</span>
          </template>
          <template v-else-if="column.key === 'name'">
            <router-link class="name-link" :to="`/configs/${record.id}`">{{ record.name }}</router-link>
          </template>
          <template v-else-if="column.key === 'description'">
            <span class="desc">{{ record.description || '—' }}</span>
          </template>
          <template v-else-if="column.key === 'result'">
            <template v-if="latestRun(record.id)">
              <router-link class="result-cell" :to="`/runs/${latestRun(record.id)!.id}`">
                <StatusTag :status="latestRun(record.id)!.status" />
                <span v-if="resultLabel(latestRun(record.id)!)" class="result-meta mono">
                  {{ resultLabel(latestRun(record.id)!) }}
                </span>
              </router-link>
            </template>
            <span v-else class="muted">—</span>
          </template>
          <template v-else-if="column.key === 'updated_at'">
            <span class="mono time">{{ dayjs(record.updated_at).format('YYYY-MM-DD HH:mm') }}</span>
          </template>
          <template v-else-if="column.key === 'actions'">
            <div class="row-actions">
              <router-link :to="`/configs/${record.id}`">编辑</router-link>
              <a href="#" @click.prevent="copyConfig(record)">复制</a>
              <a class="danger" href="#" @click.prevent="confirmDelete(record)">删除</a>
            </div>
          </template>
        </template>
      </a-table>
    </div>

    <a-modal
      v-model:open="open"
      title="新建测评任务"
      ok-text="创建"
      cancel-text="取消"
      @ok="createConfig"
    >
      <a-form layout="vertical">
        <a-form-item label="任务名称" required>
          <a-input v-model:value="form.name" placeholder="请录入任务名称" />
        </a-form-item>
        <a-form-item label="描述">
          <a-input v-model:value="form.description" placeholder="请录入描述内容" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<style scoped>
.list-page {
  min-height: 0;
  height: 100%;
  overflow: hidden;
  gap: 0;
}

.panel-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  flex: 0 0 auto;
  margin-bottom: 12px;
}

.panel-toolbar-main {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  flex: 1 1 auto;
}

.panel-title {
  margin: 0;
  font-size: 20px;
  font-weight: 500;
  line-height: 1.3;
  color: var(--ek-ink);
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.filter-search {
  width: 220px;
}

.filter-select {
  width: 150px;
}

.table-panel {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 16px 16px 12px;
  --row-h: 56px;
}

.table-panel :deep(.ant-table-wrapper),
.table-panel :deep(.ant-spin-nested-loading),
.table-panel :deep(.ant-spin-container),
.table-panel :deep(.ant-table) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.table-panel :deep(.ant-table-container) {
  flex: 0 0 auto;
}

.table-panel :deep(.ant-table-pagination) {
  flex: 0 0 auto;
  margin: 8px 0 0 !important;
}

.table-panel :deep(.ant-table-body) {
  overflow-x: hidden !important;
  overflow-y: hidden !important;
}

.config-table :deep(.ant-table-thead > tr > th) {
  height: 40px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 500;
  color: var(--ek-muted);
  background: var(--ek-raised);
  border-bottom: 1px solid var(--ek-border);
  white-space: nowrap;
}

.config-table :deep(.ant-table-tbody > tr > td) {
  height: var(--row-h);
  padding: 0 12px;
  vertical-align: middle;
  border-bottom: 1px solid rgba(17, 24, 39, 0.06);
  overflow: hidden;
}

.config-table :deep(.ant-table-tbody > tr:hover > td) {
  background: rgba(15, 118, 110, 0.03);
}

.idx,
.time,
.muted {
  color: var(--ek-secondary);
  font-size: 12px;
  line-height: var(--row-h);
}

.muted {
  color: var(--ek-muted);
}

.name-link {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
  color: var(--ek-ink);
  line-height: var(--row-h);
}

.name-link:hover {
  color: var(--ek-accent-ink);
}

.desc {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ek-secondary);
  font-size: 13px;
  line-height: var(--row-h);
}

.result-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  overflow: hidden;
  color: inherit;
  line-height: var(--row-h);
}

.result-meta {
  font-size: 12px;
  color: var(--ek-muted);
  white-space: nowrap;
}

.result-cell:hover .result-meta {
  color: var(--ek-accent-ink);
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  white-space: nowrap;
  height: var(--row-h);
}

.row-actions a.danger {
  color: var(--ek-danger) !important;
}

.row-actions a.danger:hover {
  color: #b91c1c !important;
}

.mono {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-variant-numeric: tabular-nums;
}
</style>
