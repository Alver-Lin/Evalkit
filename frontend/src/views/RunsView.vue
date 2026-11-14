<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import dayjs from 'dayjs'
import { api } from '@/api/client'
import type { EvalRunSummary } from '@/types'
import StatusTag from '@/components/StatusTag.vue'

const loading = ref(false)
const runs = ref<EvalRunSummary[]>([])
const page = ref(1)
const pageSize = 10
let timer: number | undefined

type StatusFilter = 'all' | 'succeeded' | 'failed' | 'running' | 'pending'
const draftKeyword = ref('')
const draftStatus = ref<StatusFilter>('all')
const keyword = ref('')
const statusFilter = ref<StatusFilter>('all')

const statusFilterOptions = [
  { label: '全部结果', value: 'all' },
  { label: '成功', value: 'succeeded' },
  { label: '失败', value: 'failed' },
  { label: '运行中', value: 'running' },
  { label: '等待中', value: 'pending' },
]

const panelRef = ref<HTMLElement | null>(null)
const bodyHeight = ref(pageSize * 56)
let resizeObserver: ResizeObserver | null = null

const rowHeight = computed(() => Math.max(48, bodyHeight.value / pageSize))
const scrollY = computed(() => Math.max(pageSize * 48, Math.floor(rowHeight.value * pageSize)))
const panelStyle = computed(() => ({ '--row-h': `${rowHeight.value}px` }))

const columns = [
  { title: '运行 ID', key: 'id', width: 140 },
  { title: '任务名称', dataIndex: 'config_name', key: 'config_name', ellipsis: true },
  { title: '运行结果', key: 'status', width: 110 },
  { title: '用例', key: 'total_count', width: 80 },
  { title: '通过 / 失败 / 错误', key: 'counts', width: 160 },
  { title: '通过率', key: 'pass_rate', width: 90 },
  { title: '创建时间', key: 'created_at', width: 170 },
  { title: '操作', key: 'actions', width: 108 },
]

const filteredRuns = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return runs.value.filter((run) => {
    if (statusFilter.value !== 'all' && run.status !== statusFilter.value) return false
    if (!q) return true
    const hay = `${run.id} ${run.config_name || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

function applyFilters() {
  keyword.value = draftKeyword.value
  statusFilter.value = draftStatus.value
  page.value = 1
  nextTick(measureBody)
}

function resetFilters() {
  draftKeyword.value = ''
  draftStatus.value = 'all'
  applyFilters()
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
    runs.value = await api.listRuns()
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

function confirmDelete(record: EvalRunSummary) {
  Modal.confirm({
    title: `删除报告「${record.id}」？`,
    content: '此操作不可恢复',
    okText: '确认',
    cancelText: '取消',
    okType: 'danger',
    async onOk() {
      await api.deleteRun(record.id)
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

  timer = window.setInterval(async () => {
    const hasActive = runs.value.some((r) => r.status === 'pending' || r.status === 'running')
    if (hasActive) {
      runs.value = await api.listRuns()
      await nextTick()
      measureBody()
    }
  }, 2500)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div class="page list-page">
    <div ref="panelRef" class="panel table-panel" :style="panelStyle">
      <div class="panel-toolbar">
        <div class="panel-toolbar-main">
          <h1 class="panel-title">测评报告</h1>
          <div class="filter-bar">
            <a-input
              v-model:value="draftKeyword"
              allow-clear
              placeholder="搜索运行 ID / 任务名称"
              class="filter-search"
              @pressEnter="applyFilters"
            />
            <a-select
              v-model:value="draftStatus"
              :options="statusFilterOptions"
              class="filter-select"
              placeholder="全部结果"
            />
            <a-space :size="8">
              <a-button type="primary" @click="applyFilters">查询</a-button>
              <a-button @click="resetFilters">重置</a-button>
            </a-space>
          </div>
        </div>
      </div>

      <a-table
        class="runs-table"
        :columns="columns"
        :data-source="filteredRuns"
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
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'id'">
            <span class="mono cell">{{ record.id }}</span>
          </template>
          <template v-else-if="column.key === 'config_name'">
            <span class="name">{{ record.config_name }}</span>
          </template>
          <template v-else-if="column.key === 'status'">
            <div class="status-wrap">
              <StatusTag :status="record.status" />
            </div>
          </template>
          <template v-else-if="column.key === 'total_count'">
            <span class="mono cell">{{ record.total_count || '—' }}</span>
          </template>
          <template v-else-if="column.key === 'counts'">
            <span v-if="record.total_count" class="mono cell">
              {{ record.pass_count }} / {{ record.fail_count }} / {{ record.error_count }}
            </span>
            <span v-else class="muted">—</span>
          </template>
          <template v-else-if="column.key === 'pass_rate'">
            <span class="mono cell">{{ record.total_count ? `${record.pass_rate}%` : '—' }}</span>
          </template>
          <template v-else-if="column.key === 'created_at'">
            <span class="mono time">{{ dayjs(record.created_at).format('YYYY-MM-DD HH:mm:ss') }}</span>
          </template>
          <template v-else-if="column.key === 'actions'">
            <div class="row-actions">
              <router-link :to="`/runs/${record.id}`">详情</router-link>
              <a class="danger" href="#" @click.prevent="confirmDelete(record)">删除</a>
            </div>
          </template>
        </template>
      </a-table>
    </div>
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

.runs-table :deep(.ant-table-thead > tr > th) {
  height: 40px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 500;
  color: var(--ek-muted);
  background: var(--ek-raised);
  border-bottom: 1px solid var(--ek-border);
  white-space: nowrap;
}

.runs-table :deep(.ant-table-tbody > tr > td) {
  height: var(--row-h);
  padding: 0 12px;
  vertical-align: middle;
  border-bottom: 1px solid rgba(17, 24, 39, 0.06);
  overflow: hidden;
}

.runs-table :deep(.ant-table-tbody > tr:hover > td) {
  background: rgba(15, 118, 110, 0.03);
}

.cell,
.time,
.muted {
  color: var(--ek-secondary);
  font-size: 12px;
  line-height: var(--row-h);
}

.muted {
  color: var(--ek-muted);
}

.name {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ek-ink);
  line-height: var(--row-h);
}

.status-wrap,
.row-actions {
  display: flex;
  align-items: center;
  height: var(--row-h);
}

.row-actions {
  gap: 12px;
  white-space: nowrap;
}

.danger {
  color: var(--ek-danger);
}

.danger:hover {
  color: #b91c1c;
}

.mono {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-variant-numeric: tabular-nums;
}
</style>
