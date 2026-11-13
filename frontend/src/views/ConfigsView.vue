<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import dayjs from 'dayjs'
import { api } from '@/api/client'
import StatusTag from '@/components/StatusTag.vue'
import type { ConfigMeta, EvalRunSummary } from '@/types'

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

const panelRef = ref<HTMLElement | null>(null)
const bodyHeight = ref(pageSize * 56)
let resizeObserver: ResizeObserver | null = null

const rowHeight = computed(() => Math.max(48, bodyHeight.value / pageSize))
const scrollY = computed(() => Math.max(pageSize * 48, Math.floor(rowHeight.value * pageSize)))
const panelStyle = computed(() => ({ '--row-h': `${rowHeight.value}px` }))

const columns = [
  { title: '序号', key: 'index', width: 72 },
  { title: '名称', dataIndex: 'name', key: 'name', width: 200, ellipsis: true },
  { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: '运行结果', key: 'result', width: 200 },
  { title: '更新时间', key: 'updated_at', width: 148 },
  { title: '操作', key: 'actions', width: 108 },
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

function buildDefaultYaml(description: string) {
  const escaped = description.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
  return `description: "${escaped || 'My eval'}"

prompts:
  - 'Answer: {{question}}'

providers:
  - id: python:mock_provider.py
    label: mock

tests:
  - vars:
      question: Hello
    assert:
      - type: contains
        value: Hello
`
}

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
  if (run.status === 'succeeded' && run.total_count) {
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
    <div class="page-header">
      <div>
        <h1>测评任务</h1>
        <p>定义 Prompt、Provider 与 Tests，保存后即可跑 promptfoo</p>
      </div>
      <a-button type="primary" @click="open = true">新建配置</a-button>
    </div>

    <div ref="panelRef" class="panel table-panel" :style="panelStyle">
      <a-table
        class="config-table"
        :columns="columns"
        :data-source="configs"
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
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="例如：翻译质量评测" />
        </a-form-item>
        <a-form-item label="描述">
          <a-input v-model:value="form.description" placeholder="可选说明" />
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
