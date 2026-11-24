<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import dayjs from 'dayjs'
import { ApiOutlined } from '@ant-design/icons-vue'
import { api } from '@/api/client'
import type { GraderKind, GraderMeta, GraderPayload } from '@/types'
import { headersToProbeRecord } from '@/utils/promptfooConfig'

const loading = ref(false)
const saving = ref(false)
const probing = ref(false)
const graders = ref<GraderMeta[]>([])
const page = ref(1)
const pageSize = 10
const draftKeyword = ref('')
const keyword = ref('')

const kindModalOpen = ref(false)
const drawerOpen = ref(false)
const editingId = ref<string | null>(null)

const httpMethodOptions = [
  { value: 'POST', label: 'POST' },
  { value: 'GET', label: 'GET' },
  { value: 'PUT', label: 'PUT' },
  { value: 'PATCH', label: 'PATCH' },
  { value: 'DELETE', label: 'DELETE' },
]

type FormState = {
  kind: GraderKind
  name: string
  description: string
  provider_id: string
  api_key: string
  api_host: string
  organization: string
  enable_thinking: boolean
  max_tokens: number | null
  http_method: string
  timeout_sec: number | null
  headers: Array<{ key: string; value: string }>
  transform_response: string
}

function emptyForm(kind: GraderKind = 'openai'): FormState {
  if (kind === 'http') {
    return {
      kind: 'http',
      name: '',
      description: '',
      provider_id: '',
      api_key: '',
      api_host: '',
      organization: '',
      enable_thinking: false,
      max_tokens: 1024,
      http_method: 'POST',
      timeout_sec: 60,
      headers: [{ key: 'Content-Type', value: 'application/json' }],
      transform_response: '',
    }
  }
  return {
    kind: 'openai',
    name: '',
    description: '',
    provider_id: '',
    api_key: '',
    api_host: '',
    organization: '',
    enable_thinking: false,
    max_tokens: 1024,
    http_method: 'POST',
    timeout_sec: 60,
    headers: [],
    transform_response: '',
  }
}

const form = reactive<FormState>(emptyForm())

const panelRef = ref<HTMLElement | null>(null)
const bodyHeight = ref(pageSize * 56)
let resizeObserver: ResizeObserver | null = null

const rowHeight = computed(() => Math.max(48, bodyHeight.value / pageSize))
const scrollY = computed(() => Math.max(pageSize * 48, Math.floor(rowHeight.value * pageSize)))
const panelStyle = computed(() => ({ '--row-h': `${rowHeight.value}px` }))

const columns = [
  { title: '序号', key: 'index', width: 72 },
  { title: '名称', dataIndex: 'name', key: 'name', width: 180, ellipsis: true },
  { title: '类型', key: 'kind', width: 100 },
  { title: 'Provider / URL', key: 'provider_id', ellipsis: true },
  { title: '更新时间', key: 'updated_at', width: 148 },
  { title: '操作', key: 'actions', width: 120 },
]

const filteredGraders = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return graders.value
  return graders.value.filter((item) => {
    const hay = `${item.name} ${item.description || ''} ${item.provider_id || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

function applyFilters() {
  keyword.value = draftKeyword.value
  page.value = 1
  nextTick(measureBody)
}

function resetFilters() {
  draftKeyword.value = ''
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
  bodyHeight.value = Math.max(pageSize * 48, panel.clientHeight - padY - toolbarH - headH - pagerH)
}

function onPageChange(next: number) {
  page.value = next
  nextTick(measureBody)
}

function rowIndex(index: number) {
  return (page.value - 1) * pageSize + index + 1
}

async function loadGraders() {
  loading.value = true
  try {
    graders.value = await api.listGraders()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || err?.message || '加载失败')
  } finally {
    loading.value = false
    nextTick(measureBody)
  }
}

function openKindModal() {
  kindModalOpen.value = true
}

function startCreate(kind: GraderKind) {
  kindModalOpen.value = false
  editingId.value = null
  Object.assign(form, emptyForm(kind))
  drawerOpen.value = true
}

function startEdit(item: GraderMeta) {
  editingId.value = item.id
  const kind: GraderKind = item.kind === 'http' ? 'http' : 'openai'
  const headers =
    item.headers?.length > 0
      ? item.headers.map((h) => ({ key: h.key || '', value: h.value || '' }))
      : kind === 'http'
        ? [{ key: 'Content-Type', value: 'application/json' }]
        : []
  Object.assign(form, {
    kind,
    name: item.name || '',
    description: item.description || '',
    provider_id: item.provider_id || '',
    api_key: item.api_key || '',
    api_host: item.api_host || '',
    organization: item.organization || '',
    enable_thinking: Boolean(item.enable_thinking),
    max_tokens: item.max_tokens ?? 1024,
    http_method: (item.http_method || 'POST').toUpperCase(),
    timeout_sec: item.timeout_sec ?? 60,
    headers,
    transform_response: item.transform_response || '',
  })
  drawerOpen.value = true
}

function addHeader() {
  form.headers.push({ key: '', value: '' })
}

function removeHeader(index: number) {
  if (form.headers.length <= 1) {
    form.headers = [{ key: '', value: '' }]
    return
  }
  form.headers.splice(index, 1)
}

function toPayload(): GraderPayload {
  return {
    kind: form.kind,
    name: form.name.trim(),
    description: form.description.trim(),
    provider_id: form.provider_id.trim(),
    api_key: form.api_key,
    api_host: form.api_host.trim(),
    organization: form.organization.trim(),
    enable_thinking: form.enable_thinking,
    max_tokens: form.max_tokens,
    http_method: form.http_method,
    timeout_sec: form.timeout_sec,
    headers: form.headers
      .map((h) => ({ key: h.key.trim(), value: h.value }))
      .filter((h) => h.key || h.value),
    transform_response: form.transform_response,
  }
}

function validateForm(): string | null {
  if (!form.name.trim()) return '请填写名称'
  if (!form.provider_id.trim()) {
    return form.kind === 'http' ? '请填写 URL' : '请填写 Provider ID'
  }
  return null
}

async function saveGrader() {
  const err = validateForm()
  if (err) {
    message.error(err)
    return
  }
  saving.value = true
  try {
    const payload = toPayload()
    if (editingId.value) {
      await api.updateGrader(editingId.value, payload)
      message.success('已保存')
    } else {
      await api.createGrader(payload)
      message.success('已创建')
    }
    drawerOpen.value = false
    await loadGraders()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function testConnectivity() {
  if (!form.provider_id.trim()) {
    message.warning(form.kind === 'http' ? '请先填写 URL' : '请先填写 Provider ID')
    return
  }
  probing.value = true
  try {
    const res = await api.probeProvider({
      id: form.provider_id.trim(),
      api_key: form.api_key,
      api_host: form.api_host.trim(),
      organization: form.organization.trim(),
      method: form.kind === 'http' ? form.http_method : undefined,
      headers: form.kind === 'http' ? headersToProbeRecord(form.headers) : undefined,
      body: form.kind === 'http' ? 'ping' : undefined,
      timeout_sec: form.kind === 'http' ? form.timeout_sec ?? undefined : undefined,
    })
    if (res.ok) {
      message.success(res.message || '连接成功')
    } else {
      message.error(res.message || '连接失败')
    }
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || '连通测试失败')
  } finally {
    probing.value = false
  }
}

function confirmDelete(item: GraderMeta) {
  Modal.confirm({
    title: '删除评分模型？',
    content: `将删除「${item.name}」。已引用该模型的断言需重新选择。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await api.deleteGrader(item.id)
        message.success('已删除')
        await loadGraders()
      } catch (e: any) {
        message.error(e?.response?.data?.detail || e?.message || '删除失败')
      }
    },
  })
}

onMounted(async () => {
  await loadGraders()
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
          <h1 class="panel-title">模型评测配置</h1>
          <div class="filter-bar">
            <a-input
              v-model:value="draftKeyword"
              allow-clear
              placeholder="搜索名称 / Provider"
              class="filter-search"
              @pressEnter="applyFilters"
            />
            <a-space :size="8">
              <a-button type="primary" @click="applyFilters">查询</a-button>
              <a-button @click="resetFilters">重置</a-button>
            </a-space>
          </div>
        </div>
        <a-button type="primary" @click="openKindModal">新建评分模型</a-button>
      </div>

      <a-table
        class="grader-table"
        :columns="columns"
        :data-source="filteredGraders"
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
            <a class="name-link" href="#" @click.prevent="startEdit(record)">{{ record.name }}</a>
          </template>
          <template v-else-if="column.key === 'kind'">
            <span class="kind-badge" :class="record.kind === 'http' ? 'is-http' : 'is-openai'">
              {{ record.kind === 'http' ? 'HTTP' : 'OpenAI' }}
            </span>
          </template>
          <template v-else-if="column.key === 'provider_id'">
            <span class="mono provider-id">{{ record.provider_id || '—' }}</span>
          </template>
          <template v-else-if="column.key === 'updated_at'">
            <span class="mono time">{{ dayjs(record.updated_at).format('YYYY-MM-DD HH:mm') }}</span>
          </template>
          <template v-else-if="column.key === 'actions'">
            <div class="row-actions">
              <a href="#" @click.prevent="startEdit(record)">编辑</a>
              <a class="danger" href="#" @click.prevent="confirmDelete(record)">删除</a>
            </div>
          </template>
        </template>
      </a-table>
    </div>

    <a-modal
      v-model:open="kindModalOpen"
      title="新建评分模型"
      :width="520"
      destroy-on-close
      :footer="null"
    >
      <div class="kind-pick">
        <p class="kind-hint">选择接入方式后填写评分模型配置；断言「语义相似 / 模型评分」将从此处选择。</p>
        <div class="kind-grid">
          <button type="button" class="kind-card is-http" @click="startCreate('http')">
            <span class="kind-title">自定义 HTTP</span>
            <span class="kind-desc">任意 HTTP 评分接口</span>
          </button>
          <button type="button" class="kind-card is-openai" @click="startCreate('openai')">
            <span class="kind-title">OpenAI 兼容</span>
            <span class="kind-desc">openai:chat:模型名 + API Host</span>
          </button>
        </div>
      </div>
    </a-modal>

    <a-drawer
      v-model:open="drawerOpen"
      :title="editingId ? `${form.name || '评分模型'} 编辑` : '新建评分模型'"
      :width="520"
      destroy-on-close
      :body-style="{ paddingBottom: '80px' }"
    >
      <a-form layout="vertical" class="grader-form">
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="例如：问答评分模型" />
        </a-form-item>
        <a-form-item label="描述">
          <a-input v-model:value="form.description" placeholder="可选说明" />
        </a-form-item>

        <template v-if="form.kind === 'http'">
          <a-form-item label="请求方法" required>
            <a-select v-model:value="form.http_method" :options="httpMethodOptions" style="width: 100%" />
          </a-form-item>
          <a-form-item label="URL" required>
            <a-input v-model:value="form.provider_id" class="mono" placeholder="https://example.com/api/grade" />
          </a-form-item>
          <a-form-item label="超时（秒）">
            <a-input-number v-model:value="form.timeout_sec" :min="1" :max="600" style="width: 100%" />
          </a-form-item>
          <a-form-item label="Header">
            <div class="kv-list">
              <div v-for="(header, hIndex) in form.headers" :key="`hdr-${hIndex}`" class="kv-row">
                <a-input v-model:value="header.key" class="mono" placeholder="Key" />
                <a-input v-model:value="header.value" class="mono" placeholder="Value" />
                <a-button type="text" danger @click="removeHeader(hIndex)">删除</a-button>
              </div>
              <a-button type="dashed" size="small" @click="addHeader">添加 Header</a-button>
            </div>
          </a-form-item>
          <a-form-item label="transformResponse（可选）">
            <a-textarea
              v-model:value="form.transform_response"
              class="mono"
              :rows="4"
              placeholder="(json, text) => text"
            />
          </a-form-item>
        </template>

        <template v-else>
          <a-form-item label="Provider ID" required>
            <a-input
              v-model:value="form.provider_id"
              class="mono"
              placeholder="openai:chat:模型名 / deepseek"
            />
          </a-form-item>
          <a-form-item label="API Key">
            <a-input-password v-model:value="form.api_key" placeholder="或用环境变量" autocomplete="new-password" />
          </a-form-item>
          <a-form-item label="API Host">
            <a-input
              v-model:value="form.api_host"
              class="mono"
              placeholder="兼容接口填 https://host/v1；DeepSeek 可留空"
            />
          </a-form-item>
          <a-form-item label="Organization">
            <a-input v-model:value="form.organization" placeholder="可选" />
          </a-form-item>
          <a-form-item label="max_tokens">
            <a-input-number v-model:value="form.max_tokens" :min="1" :max="128000" style="width: 100%" />
          </a-form-item>
          <a-form-item label="是否开启 think">
            <a-switch v-model:checked="form.enable_thinking" />
          </a-form-item>
        </template>
      </a-form>

      <div class="drawer-footer">
        <a-button :loading="probing" @click="testConnectivity">
          <template #icon><ApiOutlined /></template>
          测试连通
        </a-button>
        <a-space>
          <a-button @click="drawerOpen = false">取消</a-button>
          <a-button type="primary" :loading="saving" @click="saveGrader">保存</a-button>
        </a-space>
      </div>
    </a-drawer>
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
  width: 240px;
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

.grader-table :deep(.ant-table-thead > tr > th) {
  height: 40px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 500;
}

.grader-table :deep(.ant-table-tbody > tr > td) {
  height: var(--row-h);
  padding: 0 12px;
  vertical-align: middle;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.idx,
.time {
  color: var(--ek-muted);
}

.name-link {
  color: var(--ek-accent-ink);
  font-weight: 500;
}

.provider-id {
  color: var(--ek-ink);
}

.kind-badge {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.kind-badge.is-openai {
  color: #0f766e;
  background: rgba(15, 118, 110, 0.1);
}

.kind-badge.is-http {
  color: #1d4ed8;
  background: rgba(37, 99, 235, 0.1);
}

.row-actions {
  display: inline-flex;
  gap: 12px;
}

.row-actions .danger {
  color: #b91c1c;
}

.kind-pick {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.kind-hint {
  margin: 0;
  color: var(--ek-muted);
  font-size: 13px;
}

.kind-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.kind-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
  text-align: left;
  padding: 16px;
  border-radius: 10px;
  border: 1px solid var(--ek-border);
  background: var(--ek-surface);
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.kind-card:hover {
  border-color: var(--ek-accent);
  box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.08);
}

.kind-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--ek-ink);
}

.kind-desc {
  font-size: 12px;
  color: var(--ek-muted);
  line-height: 1.4;
}

.grader-form :deep(.ant-form-item) {
  margin-bottom: 16px;
}

.kv-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.kv-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 8px;
  align-items: center;
}

.drawer-footer {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 24px;
  border-top: 1px solid var(--ek-border);
  background: var(--ek-surface);
}
</style>
