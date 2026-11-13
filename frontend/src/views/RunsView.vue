<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import dayjs from 'dayjs'
import { api } from '@/api/client'
import type { EvalRunSummary } from '@/types'
import StatusTag from '@/components/StatusTag.vue'

const loading = ref(false)
const runs = ref<EvalRunSummary[]>([])
const page = ref(1)
const pageSize = 10
let timer: number | undefined

const panelRef = ref<HTMLElement | null>(null)
const bodyHeight = ref(pageSize * 56)
let resizeObserver: ResizeObserver | null = null

const rowHeight = computed(() => Math.max(48, bodyHeight.value / pageSize))
const scrollY = computed(() => Math.max(pageSize * 48, Math.floor(rowHeight.value * pageSize)))
const panelStyle = computed(() => ({ '--row-h': `${rowHeight.value}px` }))

const columns = [
  { title: '运行 ID', key: 'id', width: 140 },
  { title: '配置', dataIndex: 'config_name', key: 'config_name', ellipsis: true },
  { title: '状态', key: 'status', width: 110 },
  { title: '用例', key: 'total_count', width: 80 },
  { title: '通过 / 失败 / 错误', key: 'counts', width: 160 },
  { title: '通过率', key: 'pass_rate', width: 90 },
  { title: '创建时间', key: 'created_at', width: 170 },
  { title: '操作', key: 'actions', width: 80 },
]

function measureBody() {
  const panel = panelRef.value
  if (!panel) return
  const thead = panel.querySelector('.ant-table-thead') as HTMLElement | null
  const pager = panel.querySelector('.ant-pagination') as HTMLElement | null
  const styles = getComputedStyle(panel)
  const padY = (parseFloat(styles.paddingTop) || 0) + (parseFloat(styles.paddingBottom) || 0)
  const headH = thead?.offsetHeight || 40
  const pagerH = pager ? pager.offsetHeight + 8 : 40
  const next = Math.floor(panel.clientHeight - padY - headH - pagerH)
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
    <div class="page-header">
      <div>
        <h1>测评报告</h1>
        <p>查看 promptfoo 历史结果，下载 JSON / HTML / CSV</p>
      </div>
      <a-button @click="load">刷新</a-button>
    </div>

    <div ref="panelRef" class="panel table-panel" :style="panelStyle">
      <a-table
        class="runs-table"
        :columns="columns"
        :data-source="runs"
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
}

.table-panel {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 12px 16px 12px;
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

.mono {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-variant-numeric: tabular-nums;
}
</style>
