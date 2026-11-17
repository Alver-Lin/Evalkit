<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Upload, message } from 'ant-design-vue'
import {
  ApiOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  PlusOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'
import type { UploadFile, UploadProps } from 'ant-design-vue'
import { api } from '@/api/client'
import {
  assertNeedsGrader,
  assertShowsRange,
  assertTreeData,
  getAssertMeta,
} from '@/constants/assertOptions'
import {
  createVisualAssert,
  emptyHttpProvider,
  emptyProvider,
  inferProviderKind,
  providerHasExtraFields,
  providerHasId,
  type ProviderKind,
  type VisualAssert,
  type VisualConfig,
  type VisualHttpHeader,
  type VisualProvider,
} from '@/utils/promptfooConfig'
import { draftsToVisualTests, parseImportedTests, sampleAssertYaml } from '@/utils/importTests'

const model = defineModel<VisualConfig>({ required: true })

const props = defineProps<{
  section: 'prompts' | 'providers' | 'tests'
}>()

const varSyntax = '{{variable}}'
const promptVarSyntax = '{{prompt}}'
const httpPromptPlaceholder = `{
  "message": "{{message}}",
  "scenario": null,
  "client_id": "",
  "session_id": "",
  "selected_kbs": ["public_kingbase"]
}`
const hasHttpProvider = computed(() =>
  model.value.providers.some((provider) => inferProviderKind(provider) === 'http'),
)
const polarityOptions = [
  { value: 'yes', label: '是' },
  { value: 'not', label: '非' },
]

function polarityOf(assert: VisualAssert) {
  return assert.negated ? 'not' : 'yes'
}

function setPolarity(assert: VisualAssert, value: string) {
  assert.negated = value === 'not'
}
const pageSize = 10
const promptPage = ref(1)
const providerPage = ref(1)
const testPage = ref(1)
const detailOpen = ref(false)
const detailIndex = ref(0)
/** Block browser password-manager autofill until the user focuses the field. */
const providerAutofillLock = ref(true)

function unlockProviderAutofill() {
  providerAutofillLock.value = false
}

watch(
  () => props.section,
  (section) => {
    if (section === 'providers') providerAutofillLock.value = true
  },
)

const detailTest = computed(() => model.value.tests[detailIndex.value] ?? null)

const promptVarNames = computed(() => {
  const names = new Set<string>()
  const re = /\{\{\s*([a-zA-Z_][\w]*)/g
  for (const prompt of model.value.prompts) {
    let match: RegExpExecArray | null
    re.lastIndex = 0
    while ((match = re.exec(prompt))) {
      names.add(match[1])
    }
  }
  return Array.from(names)
})

const defaultAssertCount = computed(() => model.value.defaultAsserts?.length ?? 0)

const promptTotal = computed(() => model.value.prompts.length)
const providerTotal = computed(() => model.value.providers.length)
const testTotal = computed(() => model.value.tests.length)

function pageIndexes(page: number, total: number) {
  const start = (page - 1) * pageSize
  const end = Math.min(start + pageSize, total)
  const indexes: number[] = []
  for (let i = start; i < end; i += 1) indexes.push(i)
  return indexes
}

const pagedPromptIndexes = computed(() => pageIndexes(promptPage.value, model.value.prompts.length))
const pagedProviderIndexes = computed(() => pageIndexes(providerPage.value, model.value.providers.length))
const pagedTestIndexes = computed(() => pageIndexes(testPage.value, model.value.tests.length))

function clampPage(page: { value: number }, total: number) {
  const maxPage = Math.max(1, Math.ceil(total / pageSize) || 1)
  if (page.value > maxPage) page.value = maxPage
}

function addPrompt() {
  model.value.prompts.push('')
  promptPage.value = Math.ceil(model.value.prompts.length / pageSize) || 1
}

function removePrompt(index: number) {
  if (model.value.prompts.length <= 1) return
  model.value.prompts.splice(index, 1)
  clampPage(promptPage, model.value.prompts.length)
}

watch(promptTotal, () => clampPage(promptPage, model.value.prompts.length))
watch(providerTotal, () => clampPage(providerPage, model.value.providers.length))
watch(testTotal, () => clampPage(testPage, model.value.tests.length))

const providerModalOpen = ref(false)

const httpMethodOptions = [
  { value: 'POST', label: 'POST' },
  { value: 'GET', label: 'GET' },
  { value: 'PUT', label: 'PUT' },
  { value: 'PATCH', label: 'PATCH' },
  { value: 'DELETE', label: 'DELETE' },
]

function openProviderModal() {
  providerModalOpen.value = true
}

function selectProviderKind(kind: ProviderKind) {
  model.value.providers.push(kind === 'http' ? emptyHttpProvider() : emptyProvider())
  providerModalOpen.value = false
  providerPage.value = Math.ceil(model.value.providers.length / pageSize) || 1
}

function ensureHttpHeaders(provider: VisualProvider) {
  if (!provider.headers) provider.headers = [{ key: 'Content-Type', value: 'application/json' }]
  if (!provider.headers.length) provider.headers.push({ key: '', value: '' })
}

function httpHeadersOf(provider: VisualProvider): VisualHttpHeader[] {
  ensureHttpHeaders(provider)
  return provider.headers!
}

function addHttpHeader(provider: VisualProvider) {
  ensureHttpHeaders(provider)
  provider.headers!.push({ key: '', value: '' })
}

function removeHttpHeader(provider: VisualProvider, headerIndex: number) {
  ensureHttpHeaders(provider)
  if ((provider.headers?.length || 0) <= 1) {
    provider.headers = [{ key: '', value: '' }]
    return
  }
  provider.headers!.splice(headerIndex, 1)
}

function reindexGraderProviders(removedIndex: number) {
  const fix = (asserts: VisualAssert[]) => {
    for (const assert of asserts) {
      if (assert.graderProviderIndex == null) continue
      if (assert.graderProviderIndex === removedIndex) {
        assert.graderProviderIndex = null
      } else if (assert.graderProviderIndex > removedIndex) {
        assert.graderProviderIndex -= 1
      }
    }
  }
  fix(model.value.defaultAsserts || [])
  for (const test of model.value.tests) fix(test.asserts)
}

function reindexProbeStates(removedIndex: number) {
  const next: Record<number, ProbeState> = {}
  for (const [key, state] of Object.entries(probeStates.value)) {
    const i = Number(key)
    if (i === removedIndex) continue
    next[i > removedIndex ? i - 1 : i] = state
  }
  probeStates.value = next
}

function removeProvider(index: number) {
  if (model.value.providers.length <= 1) return
  model.value.providers.splice(index, 1)
  reindexGraderProviders(index)
  reindexProbeStates(index)
  clampPage(providerPage, model.value.providers.length)
}

function providerMissingId(index: number): boolean {
  const provider = model.value.providers[index]
  if (!provider) return false
  return !providerHasId(provider) && providerHasExtraFields(provider)
}

type ProbeStatus = 'idle' | 'loading' | 'success' | 'error'

interface ProbeState {
  status: ProbeStatus
  message: string
}

const probeStates = ref<Record<number, ProbeState>>({})
const probingIndex = computed(() => {
  const entry = Object.entries(probeStates.value).find(([, state]) => state.status === 'loading')
  return entry ? Number(entry[0]) : null
})

function probeStateOf(index: number): ProbeState {
  return probeStates.value[index] || { status: 'idle', message: '' }
}

function setProbeState(index: number, status: ProbeStatus, msg = '') {
  probeStates.value = {
    ...probeStates.value,
    [index]: { status, message: msg },
  }
}

async function testProviderConnectivity(index: number) {
  const provider = model.value.providers[index]
  if (!provider) return
  if (!provider.id.trim()) {
    message.warning(
      inferProviderKind(provider) === 'http' ? '请先填写 URL' : '请先填写 Provider ID',
    )
    return
  }
  setProbeState(index, 'loading', '连接中')
  try {
    const kind = inferProviderKind(provider)
    const result = await api.probeProvider({
      id: provider.id.trim(),
      api_key: provider.apiKey.trim(),
      api_host: provider.apiHost.trim(),
      organization: provider.organization.trim(),
      method: kind === 'http' ? (provider.httpMethod || 'POST').toUpperCase() : undefined,
    })
    if (result.ok) {
      setProbeState(index, 'success', result.message || '连接成功')
    } else {
      setProbeState(index, 'error', result.message || '连接失败')
      message.error(result.message)
    }
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || '连通测试失败'
    setProbeState(index, 'error', detail)
    message.error(detail)
  }
}

const graderProviderOptions = computed(() =>
  model.value.providers.map((provider, index) => ({
    value: index,
    label: provider.label.trim() || provider.id.trim() || `provider${index + 1}`,
    disabled: !provider.id.trim(),
  })),
)

function firstGraderProviderIndex(): number | null {
  const index = model.value.providers.findIndex((provider) => provider.id.trim())
  return index >= 0 ? index : null
}

function parseVarsObject(text: string): Record<string, string> {
  try {
    const parsed = JSON.parse(text || '{}')
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const out: Record<string, string> = {}
      for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
        out[key] = value == null ? '' : String(value)
      }
      return out
    }
  } catch {
    // ignore
  }
  return {}
}

function buildVarsText(values: Record<string, string>) {
  const next: Record<string, string> = {}
  for (const name of promptVarNames.value) {
    next[name] = values[name] ?? ''
  }
  return JSON.stringify(next, null, 2)
}

function syncTestVarsToPromptNames(testIndex: number) {
  const test = model.value.tests[testIndex]
  if (!test) return
  const current = parseVarsObject(test.varsText)
  test.varsText = buildVarsText(current)
}

function getVarValue(testIndex: number, key: string) {
  return parseVarsObject(model.value.tests[testIndex]?.varsText || '')[key] ?? ''
}

function setVarValue(testIndex: number, key: string, value: string) {
  const current = parseVarsObject(model.value.tests[testIndex]?.varsText || '')
  current[key] = value
  model.value.tests[testIndex].varsText = buildVarsText(current)
}

function addTest() {
  model.value.tests.push({
    description: '',
    varsText: buildVarsText({}),
    asserts: [],
  })
  testPage.value = Math.ceil(model.value.tests.length / pageSize) || 1
  openTestDetail(model.value.tests.length - 1)
}

const testImportOpen = ref(false)
const testImportFileList = ref<UploadFile[]>([])
const testImportSubmitting = ref(false)

function isBlankTest(index: number) {
  const test = model.value.tests[index]
  if (!test) return true
  const vars = parseVarsObject(test.varsText)
  const hasVars = Object.values(vars).some((value) => value.trim())
  return !test.description.trim() && !hasVars && !(test.asserts?.length)
}

function openTestImport() {
  testImportFileList.value = []
  testImportOpen.value = true
}

function closeTestImport() {
  testImportOpen.value = false
  testImportFileList.value = []
}

function csvEscape(value: string) {
  if (/[",\n\r]/.test(value)) return `"${value.replace(/"/g, '""')}"`
  return value
}

function downloadTestTemplate() {
  const varNames = promptVarNames.value.length ? promptVarNames.value : ['question']
  const headers = ['description', ...varNames, 'assert']
  const sample = [
    csvEscape('示例用例'),
    ...varNames.map((name, index) => csvEscape(index === 0 ? 'Hello' : '')),
    csvEscape(sampleAssertYaml()),
  ]
  const content = `\uFEFF${headers.join(',')}\n${sample.join(',')}\n`
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'evalkit-tests-template.csv'
  link.click()
  URL.revokeObjectURL(url)
}

const beforeTestImportUpload: UploadProps['beforeUpload'] = (file) => {
  const name = file.name.toLowerCase()
  const ok =
    name.endsWith('.csv') ||
    name.endsWith('.json') ||
    name.endsWith('.yaml') ||
    name.endsWith('.yml')
  if (!ok) {
    message.error('仅支持 .csv / .json / .yaml')
    return Upload.LIST_IGNORE
  }
  testImportFileList.value = [
    {
      uid: `${file.name}-${file.size}-${Date.now()}`,
      name: file.name,
      status: 'done',
      originFileObj: file as UploadFile['originFileObj'],
    },
  ]
  return false
}

function onTestImportRemove() {
  testImportFileList.value = []
}

async function submitTestImport() {
  const file = testImportFileList.value[0]?.originFileObj as File | undefined
  if (!file) {
    message.warning('请先选择文件')
    return
  }

  testImportSubmitting.value = true
  try {
    const text = await file.text()
    const drafts = parseImportedTests(text, file.name, model.value.providers)
    const imported = draftsToVisualTests(drafts, promptVarNames.value)
    if (!imported.length) {
      message.warning('未解析到有效用例')
      return
    }

    if (model.value.tests.length === 1 && isBlankTest(0)) {
      model.value.tests = imported
    } else {
      model.value.tests.push(...imported)
    }
    testPage.value = Math.ceil(model.value.tests.length / pageSize) || 1
    const withAsserts = imported.filter((item) => item.asserts.length).length
    message.success(
      withAsserts
        ? `已导入 ${imported.length} 条测试用例（其中 ${withAsserts} 条含断言）`
        : `已导入 ${imported.length} 条测试用例`,
    )
    closeTestImport()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '导入失败')
  } finally {
    testImportSubmitting.value = false
  }
}

function removeTest(index: number) {
  if (model.value.tests.length <= 1) return
  model.value.tests.splice(index, 1)
  if (detailOpen.value) {
    if (detailIndex.value > index) {
      detailIndex.value -= 1
    } else if (detailIndex.value >= model.value.tests.length) {
      detailIndex.value = Math.max(0, model.value.tests.length - 1)
    }
  }
  clampPage(testPage, model.value.tests.length)
}

function openTestDetail(index: number) {
  detailIndex.value = index
  syncTestVarsToPromptNames(index)
  detailOpen.value = true
}

function testVarsPreview(varsText: string) {
  const obj = parseVarsObject(varsText)
  const keys = promptVarNames.value.length ? promptVarNames.value : Object.keys(obj)
  if (!keys.length) return '—'
  const text = keys.map((key) => `${key}: ${obj[key] || '—'}`).join(', ')
  return text.length > 48 ? `${text.slice(0, 48)}…` : text
}

watch(
  promptVarNames,
  () => {
    model.value.tests.forEach((_, index) => syncTestVarsToPromptNames(index))
  },
  { deep: true },
)

function assertTypeLabel(assert: VisualAssert) {
  const meta = getAssertMeta(assert.type)
  const base = meta.label || assert.type || 'assert'
  return assert.negated ? `非·${base}` : base
}

function testAssertPreview(asserts: VisualAssert[]) {
  if (!asserts?.length) return '—'
  return asserts.map((a) => assertTypeLabel(a)).join(', ')
}

function showsValue(assert: VisualAssert) {
  const meta = getAssertMeta(assert.type)
  if (meta.hasRange) return false
  return meta.hasValue !== false
}

function showsThreshold(assert: VisualAssert) {
  return Boolean(getAssertMeta(assert.type).hasThreshold)
}

function showsRange(assert: VisualAssert) {
  return assertShowsRange(assert.type)
}

function showsGrader(assert: VisualAssert) {
  return assertNeedsGrader(assert.type)
}

function valuePlaceholder(assert: VisualAssert) {
  return getAssertMeta(assert.type).valuePlaceholder || '期望值'
}

function thresholdPlaceholder(assert: VisualAssert) {
  return getAssertMeta(assert.type).thresholdPlaceholder || '阈值'
}

function onAssertTypeChange(assert: VisualAssert, type: string | undefined) {
  const next = (type || '').trim() || 'contains'
  assert.type = next
  const meta = getAssertMeta(next)
  if (meta.hasValue === false || meta.hasRange) {
    assert.value = ''
  }
  assert.threshold = meta.hasThreshold ? (meta.defaultThreshold ?? null) : null
  assert.min = meta.hasRange ? (meta.defaultMin ?? null) : null
  assert.max = meta.hasRange ? (meta.defaultMax ?? null) : null
  if (meta.needsGrader) {
    if (
      assert.graderProviderIndex == null ||
      !model.value.providers[assert.graderProviderIndex]?.id.trim()
    ) {
      assert.graderProviderIndex = firstGraderProviderIndex()
    }
  } else {
    assert.graderProviderIndex = null
  }
}

function assertRowClass(assert: VisualAssert) {
  const hasValue = showsValue(assert)
  const hasThreshold = showsThreshold(assert)
  const hasRange = showsRange(assert)
  const hasGrader = showsGrader(assert)
  if (hasRange) return 'assert-row assert-row-range'
  if (hasValue && hasThreshold && hasGrader) return 'assert-row assert-row-both-grader'
  if (hasValue && hasThreshold) return 'assert-row assert-row-both'
  if (hasThreshold) return 'assert-row assert-row-threshold'
  if (hasValue) return 'assert-row assert-row-value'
  return 'assert-row assert-row-none'
}

function addAssert(testIndex: number) {
  model.value.tests[testIndex].asserts.push(createVisualAssert('contains'))
}

function removeAssert(testIndex: number, assertIndex: number) {
  model.value.tests[testIndex].asserts.splice(assertIndex, 1)
}

function addDefaultAssert() {
  if (!model.value.defaultAsserts) model.value.defaultAsserts = []
  model.value.defaultAsserts.push(createVisualAssert('contains'))
}

function removeDefaultAssert(index: number) {
  model.value.defaultAsserts.splice(index, 1)
}
</script>

<template>
  <div class="visual">
    <section v-if="section === 'prompts'" class="panel-block">
      <header class="panel-head">
        <div class="head-text">
          <h3>提示词</h3>
          <p>
            自定义 HTTP 时，此处填写请求 Body（JSON）；新建 OpenAI 兼容时，此处填写提示词。用
            <code>{{ varSyntax }}</code> 作变量，供应商 Body 固定为
            <code>{{ promptVarSyntax }}</code>
          </p>
        </div>
        <div class="head-meta">
          <a-button type="dashed" class="add-btn" @click="addPrompt">
            <PlusOutlined /> 新建提示词
          </a-button>
        </div>
      </header>
      <div class="panel-body">
        <div class="field-list">
          <div
            v-for="index in pagedPromptIndexes"
            :key="`prompt-${index}`"
            class="field"
          >
            <div class="field-label-row">
              <label class="mono">prompt{{ index + 1 }}</label>
              <a-button
                type="text"
                danger
                class="icon-btn"
                :disabled="model.prompts.length <= 1"
                @click="removePrompt(index)"
              >
                <DeleteOutlined />
              </a-button>
            </div>
            <a-textarea
              v-model:value="model.prompts[index]"
              :rows="hasHttpProvider ? 10 : 5"
              class="prompt-editor mono"
              :placeholder="hasHttpProvider ? httpPromptPlaceholder : '例如：Answer: ' + varSyntax"
            />
          </div>
        </div>
        <div class="pager">
          <a-pagination
            v-model:current="promptPage"
            :total="promptTotal"
            :page-size="pageSize"
            size="small"
            show-less-items
            :show-total="(total: number) => `共 ${total} 条`"
          />
        </div>
      </div>
    </section>

    <section v-else-if="section === 'providers'" class="panel-block">
      <header class="panel-head">
        <div class="head-text">
          <h3>供应商</h3>
          <p>新建时可选择「自定义 HTTP」或「OpenAI 兼容」</p>
        </div>
        <div class="head-meta">
          <a-button type="dashed" class="add-btn" @click="openProviderModal">
            <PlusOutlined /> 新建供应商
          </a-button>
        </div>
      </header>
      <div class="panel-body">
        <div class="item-list">
          <div
            v-for="index in pagedProviderIndexes"
            :key="`provider-${index}`"
            class="item"
            :class="{ 'item-warn': providerMissingId(index) }"
          >
            <div class="item-head">
              <div class="item-title-row">
                <span class="badge mono">provider{{ index + 1 }}</span>
                <span
                  class="kind-badge"
                  :class="inferProviderKind(model.providers[index]) === 'http' ? 'is-http' : 'is-openai'"
                >
                  {{ inferProviderKind(model.providers[index]) === 'http' ? 'HTTP' : 'OpenAI' }}
                </span>
              </div>
              <div class="item-actions">
                <a-tooltip
                  v-if="probeStateOf(index).status !== 'idle'"
                  :title="probeStateOf(index).message"
                >
                  <span
                    class="probe-bubble"
                    :class="`is-${probeStateOf(index).status}`"
                  >
                    <span class="probe-dot" aria-hidden="true" />
                    {{
                      probeStateOf(index).status === 'loading'
                        ? '连接中'
                        : probeStateOf(index).status === 'success'
                          ? '连接成功'
                          : '连接失败'
                    }}
                  </span>
                </a-tooltip>
                <a-button
                  type="text"
                  size="small"
                  class="probe-btn"
                  :loading="probeStateOf(index).status === 'loading'"
                  :disabled="
                    !model.providers[index].id.trim() ||
                    (probingIndex !== null && probingIndex !== index)
                  "
                  @click="testProviderConnectivity(index)"
                >
                  <template #icon><ApiOutlined /></template>
                  测试连通
                </a-button>
                <a-button
                  type="text"
                  danger
                  class="icon-btn"
                  :disabled="model.providers.length <= 1"
                  @click="removeProvider(index)"
                >
                  <DeleteOutlined />
                </a-button>
              </div>
            </div>

            <!-- Custom HTTP card -->
            <div
              v-if="inferProviderKind(model.providers[index]) === 'http'"
              class="provider-grid provider-grid-http"
              autocomplete="off"
            >
              <div class="field span-main">
                <label>
                  名称
                  <span class="req" aria-hidden="true">*</span>
                </label>
                <a-input
                  v-model:value="model.providers[index].label"
                  name="evalkit-http-label"
                  autocomplete="off"
                  placeholder="Agent 显示名"
                />
              </div>
              <div class="field span-side">
                <label>
                  请求方法
                  <span class="req" aria-hidden="true">*</span>
                </label>
                <a-select
                  v-model:value="model.providers[index].httpMethod"
                  :options="httpMethodOptions"
                  style="width: 100%"
                />
              </div>
              <div class="field span-full">
                <label>描述</label>
                <a-input
                  v-model:value="model.providers[index].description"
                  name="evalkit-http-desc"
                  autocomplete="off"
                  placeholder="可选，仅保存在可视化配置中"
                />
              </div>
              <div class="field span-main">
                <label>
                  URL
                  <span class="req" aria-hidden="true">*</span>
                </label>
                <a-input
                  v-model:value="model.providers[index].id"
                  class="mono"
                  name="evalkit-http-url"
                  autocomplete="off"
                  :status="providerMissingId(index) ? 'error' : undefined"
                  placeholder="https://example.com/api/chat"
                />
                <p v-if="providerMissingId(index)" class="field-hint is-error">
                  已填写其它字段，但缺少 URL，保存会被拒绝
                </p>
              </div>
              <div class="field span-side">
                <label>
                  超时（秒）
                  <span class="req" aria-hidden="true">*</span>
                </label>
                <a-input-number
                  v-model:value="model.providers[index].timeoutSec"
                  class="max-tokens-input"
                  :min="1"
                  :max="600"
                  :step="5"
                  placeholder="60"
                />
              </div>
              <div class="field span-full">
                <label>Header</label>
                <div class="kv-list">
                  <div
                    v-for="(header, hIndex) in httpHeadersOf(model.providers[index])"
                    :key="`hdr-${index}-${hIndex}`"
                    class="kv-row"
                  >
                    <a-input
                      v-model:value="header.key"
                      class="mono"
                      placeholder="Key"
                    />
                    <a-input
                      v-model:value="header.value"
                      class="mono"
                      placeholder="Value，支持模板变量"
                    />
                    <a-button
                      type="text"
                      danger
                      class="icon-btn"
                      @click="removeHttpHeader(model.providers[index], hIndex)"
                    >
                      <DeleteOutlined />
                    </a-button>
                  </div>
                  <a-button type="dashed" size="small" class="kv-add" @click="addHttpHeader(model.providers[index])">
                    <PlusOutlined /> 添加 Header
                  </a-button>
                </div>
              </div>
            </div>

            <!-- OpenAI compatible card -->
            <div v-else class="provider-grid" autocomplete="off">
              <div class="field span-main">
                <label>
                  Provider ID
                  <span class="req" aria-hidden="true">*</span>
                </label>
                <a-input
                  v-model:value="model.providers[index].id"
                  class="mono"
                  name="evalkit-provider-id"
                  autocomplete="off"
                  :status="providerMissingId(index) ? 'error' : undefined"
                  placeholder="openai:chat:模型名 / deepseek"
                />
                <p v-if="providerMissingId(index)" class="field-hint is-error">
                  已填写密钥或 Host，但缺少 Provider ID，保存会被拒绝
                </p>
                <p v-else class="field-hint">
                  OpenAI 兼容：openai:chat:模型名；DeepSeek 可填 deepseek
                </p>
              </div>
              <div class="field span-side">
                <label>Label</label>
                <a-input
                  v-model:value="model.providers[index].label"
                  name="evalkit-provider-label"
                  autocomplete="off"
                  :readonly="providerAutofillLock"
                  placeholder="可选"
                  @focus="unlockProviderAutofill"
                />
              </div>
              <div class="field span-full">
                <label>API Key</label>
                <a-input-password
                  v-model:value="model.providers[index].apiKey"
                  name="evalkit-provider-api-key"
                  autocomplete="new-password"
                  :readonly="providerAutofillLock"
                  placeholder="或用环境变量"
                  @focus="unlockProviderAutofill"
                />
              </div>
              <div class="field span-full">
                <label>API Host</label>
                <a-input
                  v-model:value="model.providers[index].apiHost"
                  class="mono"
                  name="evalkit-provider-api-host"
                  autocomplete="off"
                  placeholder="兼容接口填 https://host/v1；DeepSeek 可留空"
                />
              </div>
              <div class="field span-full">
                <label>Organization</label>
                <a-input
                  v-model:value="model.providers[index].organization"
                  name="evalkit-provider-org"
                  autocomplete="off"
                  placeholder="可选"
                />
              </div>
              <div class="field span-full">
                <label>max_tokens</label>
                <a-input-number
                  v-model:value="model.providers[index].maxTokens"
                  class="max-tokens-input"
                  :min="1"
                  :max="128000"
                  :step="64"
                  placeholder="例如 1024"
                />
              </div>
              <div class="field span-full thinking-row">
                <label>是否开启 think</label>
                <div class="thinking-switch">
                  <a-switch
                    :checked="Boolean(model.providers[index].enableThinking)"
                    @update:checked="(v: boolean) => (model.providers[index].enableThinking = v)"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="pager">
          <a-pagination
            v-model:current="providerPage"
            :total="providerTotal"
            :page-size="pageSize"
            size="small"
            show-less-items
            :show-total="(total: number) => `共 ${total} 条`"
          />
        </div>
      </div>

      <a-modal
        v-model:open="providerModalOpen"
        title="新建供应商"
        :width="520"
        wrap-class-name="provider-create-modal-wrap"
        destroy-on-close
        :footer="null"
      >
        <div class="provider-kind-pick">
          <p class="provider-kind-hint">选择接入方式后，在列表中直接填写配置</p>
          <div class="provider-kind-grid">
            <button type="button" class="provider-kind-card is-http" @click="selectProviderKind('http')">
              <span class="provider-kind-title">自定义 HTTP</span>
              <span class="provider-kind-desc">任意 HTTP / SSE Agent 接口</span>
            </button>
            <button type="button" class="provider-kind-card is-openai" @click="selectProviderKind('openai')">
              <span class="provider-kind-title">OpenAI 兼容</span>
              <span class="provider-kind-desc">OpenAI / DeepSeek 等 Chat API</span>
            </button>
          </div>
        </div>
      </a-modal>
    </section>

    <template v-else-if="section === 'tests'">
      <section class="panel-block panel-block-compact">
        <header class="panel-head">
          <div class="head-text">
            <h3>全局断言</h3>
            <p>作用于全部测试用例</p>
          </div>
          <div class="head-meta">
            <a-button type="dashed" class="add-btn" @click="addDefaultAssert">
              <PlusOutlined /> 新建全局断言
            </a-button>
          </div>
        </header>
        <div class="panel-body">
          <div v-if="!defaultAssertCount" class="empty">暂无全局断言</div>
          <div v-else class="assert-list">
            <div
              v-for="(assertItem, assertIndex) in model.defaultAsserts"
              :key="`default-assert-${assertIndex}`"
              :class="assertRowClass(assertItem)"
            >
              <a-select
                :value="polarityOf(assertItem)"
                class="assert-polarity"
                :options="polarityOptions"
                :dropdown-match-select-width="false"
                @update:value="(value: string) => setPolarity(assertItem, value)"
              />
              <a-tree-select
                :value="assertItem.type"
                class="assert-type"
                :tree-data="assertTreeData"
                show-search
                tree-node-filter-prop="title"
                tree-default-expand-all
                :dropdown-style="{ maxHeight: '320px', overflow: 'auto' }"
                placeholder="选择断言类型"
                allow-clear
                @update:value="(value: string) => onAssertTypeChange(assertItem, value)"
              />
              <a-input
                v-if="showsValue(assertItem)"
                v-model:value="assertItem.value"
                class="assert-value"
                :placeholder="valuePlaceholder(assertItem)"
              />
              <template v-if="showsRange(assertItem)">
                <a-input-number
                  v-model:value="assertItem.min"
                  class="assert-range"
                  placeholder="最小"
                  :min="0"
                  :controls="false"
                />
                <a-input-number
                  v-model:value="assertItem.max"
                  class="assert-range"
                  placeholder="最大"
                  :min="0"
                  :controls="false"
                />
              </template>
              <a-input-number
                v-if="showsThreshold(assertItem)"
                v-model:value="assertItem.threshold"
                class="assert-threshold"
                :placeholder="thresholdPlaceholder(assertItem)"
                :controls="false"
              />
              <a-select
                v-if="showsGrader(assertItem)"
                v-model:value="assertItem.graderProviderIndex"
                class="assert-grader"
                :options="graderProviderOptions"
                :dropdown-match-select-width="false"
                allow-clear
                placeholder="评判供应商"
              />
              <a-button
                type="text"
                danger
                class="icon-btn"
                @click="removeDefaultAssert(assertIndex)"
              >
                <DeleteOutlined />
              </a-button>
            </div>
          </div>
        </div>
      </section>

      <section class="panel-block">
        <header class="panel-head">
          <div class="head-text">
            <h3>测试用例</h3>
            <p>变量与断言</p>
          </div>
          <div class="head-meta">
            <a-button class="add-btn" @click="openTestImport">
              <UploadOutlined /> 导入
            </a-button>
            <a-button type="dashed" class="add-btn" @click="addTest">
              <PlusOutlined /> 新建测试用例
            </a-button>
          </div>
        </header>
        <div class="panel-body panel-body-split">
          <div class="table-scroll">
            <a-table
              class="test-table"
              size="middle"
              row-key="index"
              :pagination="false"
              :data-source="pagedTestIndexes.map((index) => ({ index }))"
            >
              <a-table-column title="ID" :width="100">
                <template #default="{ record }">
                  <span class="mono">test{{ record.index + 1 }}</span>
                </template>
              </a-table-column>
              <a-table-column title="测试项" ellipsis>
                <template #default="{ record }">
                  {{ model.tests[record.index].description || '—' }}
                </template>
              </a-table-column>
              <a-table-column title="变量" ellipsis>
                <template #default="{ record }">
                  <span class="mono tiny">{{ testVarsPreview(model.tests[record.index].varsText) }}</span>
                </template>
              </a-table-column>
              <a-table-column title="断言" :width="160" ellipsis>
                <template #default="{ record }">
                  {{ testAssertPreview(model.tests[record.index].asserts) }}
                </template>
              </a-table-column>
              <a-table-column title="操作" :width="120">
                <template #default="{ record }">
                  <div class="row-actions">
                    <a @click="openTestDetail(record.index)">编辑</a>
                    <a
                      class="danger"
                      :class="{ disabled: model.tests.length <= 1 }"
                      @click.prevent="model.tests.length > 1 && removeTest(record.index)"
                    >删除</a>
                  </div>
                </template>
              </a-table-column>
            </a-table>
          </div>
          <div class="pager">
            <a-pagination
              v-model:current="testPage"
              :total="testTotal"
              :page-size="pageSize"
              size="small"
              show-less-items
              :show-total="(total: number) => `共 ${total} 条`"
            />
          </div>
        </div>
      </section>

      <a-drawer
        v-model:open="detailOpen"
        :title="detailTest ? `test${detailIndex + 1} 编辑` : '编辑测试用例'"
        placement="right"
        :width="860"
        destroy-on-close
      >
        <div v-if="detailTest" class="detail-form">
          <div class="field">
            <label>测试项</label>
            <a-input v-model:value="detailTest.description" placeholder="可选" />
          </div>
          <div class="field">
            <label>变量</label>
            <div v-if="!promptVarNames.length" class="empty">提示词中尚未定义变量，请先在提示词中使用 {{ varSyntax }}</div>
            <div v-else class="var-fields">
              <div v-for="name in promptVarNames" :key="name" class="var-row">
                <label class="mono var-key">{{ name }}</label>
                <a-input
                  :value="getVarValue(detailIndex, name)"
                  :placeholder="`输入 ${name}`"
                  @update:value="(value: string) => setVarValue(detailIndex, name, value)"
                />
              </div>
            </div>
          </div>
          <div class="field">
            <div class="assert-label-row">
              <label>断言</label>
              <a-button type="dashed" size="small" @click="addAssert(detailIndex)">
                <PlusOutlined /> 添加断言
              </a-button>
            </div>
            <div v-if="!detailTest.asserts.length" class="empty">暂无断言</div>
            <div v-else class="assert-list">
              <div
                v-for="(assertItem, assertIndex) in detailTest.asserts"
                :key="`detail-assert-${assertIndex}`"
                :class="assertRowClass(assertItem)"
              >
                <a-select
                  :value="polarityOf(assertItem)"
                  class="assert-polarity"
                  :options="polarityOptions"
                  :dropdown-match-select-width="false"
                  @update:value="(value: string) => setPolarity(assertItem, value)"
                />
                <a-tree-select
                  :value="assertItem.type"
                  class="assert-type"
                  :tree-data="assertTreeData"
                  show-search
                  tree-node-filter-prop="title"
                  tree-default-expand-all
                  :dropdown-style="{ maxHeight: '320px', overflow: 'auto' }"
                  placeholder="选择断言类型"
                  allow-clear
                  @update:value="(value: string) => onAssertTypeChange(assertItem, value)"
                />
                <a-input
                  v-if="showsValue(assertItem)"
                  v-model:value="assertItem.value"
                  class="assert-value"
                  :placeholder="valuePlaceholder(assertItem)"
                />
                <template v-if="showsRange(assertItem)">
                  <a-input-number
                    v-model:value="assertItem.min"
                    class="assert-range"
                    placeholder="最小"
                    :min="0"
                    :controls="false"
                  />
                  <a-input-number
                    v-model:value="assertItem.max"
                    class="assert-range"
                    placeholder="最大"
                    :min="0"
                    :controls="false"
                  />
                </template>
                <a-input-number
                  v-if="showsThreshold(assertItem)"
                  v-model:value="assertItem.threshold"
                  class="assert-threshold"
                  :placeholder="thresholdPlaceholder(assertItem)"
                  :controls="false"
                />
                <a-select
                  v-if="showsGrader(assertItem)"
                  v-model:value="assertItem.graderProviderIndex"
                  class="assert-grader"
                  :options="graderProviderOptions"
                  :dropdown-match-select-width="false"
                  allow-clear
                  placeholder="评判供应商"
                />
                <a-button
                  type="text"
                  danger
                  class="icon-btn"
                  @click="removeAssert(detailIndex, assertIndex)"
                >
                  <DeleteOutlined />
                </a-button>
              </div>
            </div>
          </div>
        </div>
      </a-drawer>

      <a-modal
        v-model:open="testImportOpen"
        title="导入测试用例"
        :width="520"
        centered
        destroy-on-close
        :mask-closable="false"
        wrap-class-name="test-import-modal-wrap"
        @cancel="closeTestImport"
      >
        <div class="import-tips">
          <ul>
            <li>
              可先
              <a href="#" @click.prevent="downloadTestTemplate">下载模版</a>
              填写后上传。断言列仅支持 YAML（如 <code>- type: llm-rubric</code>）；任一条失败则整批不导入。
            </li>
            <li>
              校验通过后合并进当前测试用例（不清空已有数据）；若当前仅有一条空白用例则直接替换。
            </li>
          </ul>
        </div>

        <a-upload-dragger
          v-model:file-list="testImportFileList"
          class="import-dragger"
          name="tests"
          :multiple="false"
          :max-count="1"
          accept=".csv,.json,.yaml,.yml"
          :before-upload="beforeTestImportUpload"
          @remove="onTestImportRemove"
        >
          <p class="ant-upload-drag-icon">
            <CloudUploadOutlined />
          </p>
          <p class="ant-upload-text">点击选择或拖拽文件到此处</p>
          <p class="ant-upload-hint">支持 .csv / .json / .yaml</p>
        </a-upload-dragger>

        <template #footer>
          <a-button @click="closeTestImport">取消</a-button>
          <a-button
            type="primary"
            :disabled="!testImportFileList.length"
            :loading="testImportSubmitting"
            @click="submitTestImport"
          >
            开始导入
          </a-button>
        </template>
      </a-modal>
    </template>
  </div>
</template>

<style scoped>
.visual {
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: 100%;
  min-height: 100%;
}

.panel-block {
  border: 1px solid var(--ek-border);
  border-radius: 16px;
  background: var(--ek-surface);
  overflow: hidden;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.panel-block-compact {
  flex: 0 0 auto;
  min-height: auto;
  height: auto;
}

.panel-block-compact .panel-body {
  flex: 0 0 auto;
  padding-bottom: 16px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  background: var(--ek-raised);
  border-bottom: 1px solid var(--ek-border);
  flex-shrink: 0;
}

.head-text h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 500;
  color: var(--ek-ink);
  line-height: 24px;
}

.head-text .en,
.en {
  margin-left: 6px;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 12px;
  font-weight: 400;
  color: var(--ek-muted);
}

.en.quiet {
  margin-left: 8px;
}

.head-text p {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 18px;
  color: var(--ek-muted);
}

.head-text code {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(17, 24, 39, 0.06);
  color: var(--ek-secondary);
}

.head-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  min-height: 28px;
}

.add-btn {
  height: 32px;
  padding: 0 12px;
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}


.panel-body {
  padding: 16px 20px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.panel-body-split {
  gap: 0;
}

.item-list,
.field-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  overflow: auto;
}

.field-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 28px;
}

.field-label-row label {
  margin: 0;
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
  padding-top: 12px;
  margin-top: 8px;
  border-top: 1px solid var(--ek-border);
  background: var(--ek-surface);
}

.test-table :deep(.ant-table) {
  background: transparent;
}

.tiny {
  font-size: 12px;
  color: var(--ek-secondary);
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  white-space: nowrap;
}

.row-actions a.danger {
  color: var(--ek-danger) !important;
}

.row-actions a.danger:hover {
  color: #b91c1c !important;
}

.row-actions a.danger.disabled {
  color: var(--ek-muted) !important;
  cursor: not-allowed;
  pointer-events: none;
}

.detail-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.var-fields {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.var-row {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
}

.var-key {
  font-size: 12px;
  color: var(--ek-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assert-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}

.assert-label-row label {
  margin: 0;
}

.item {
  border: 1px solid var(--ek-border);
  border-radius: 12px;
  background: #fafbfc;
  padding: 12px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 28px;
}

.item-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.probe-bubble {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1;
  white-space: nowrap;
  border: 1px solid transparent;
}

.probe-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.probe-bubble.is-loading {
  color: #9a6700;
  background: #fff8c5;
  border-color: rgba(154, 103, 0, 0.18);
}

.probe-bubble.is-loading .probe-dot {
  background: #9a6700;
  box-shadow: 0 0 0 0 rgba(154, 103, 0, 0.45);
  animation: probe-pulse 1.2s ease-out infinite;
}

.probe-bubble.is-success {
  color: #1a7f37;
  background: #dafbe1;
  border-color: rgba(26, 127, 55, 0.18);
}

.probe-bubble.is-success .probe-dot {
  background: #1a7f37;
}

.probe-bubble.is-error {
  color: #cf222e;
  background: #ffebe9;
  border-color: rgba(207, 34, 46, 0.18);
}

.probe-bubble.is-error .probe-dot {
  background: #cf222e;
}

@keyframes probe-pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(154, 103, 0, 0.45);
  }
  70% {
    box-shadow: 0 0 0 6px rgba(154, 103, 0, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(154, 103, 0, 0);
  }
}

.probe-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  width: auto !important;
  min-width: auto;
  padding: 0 10px !important;
  color: var(--ek-muted);
  font-size: 12px;
  line-height: 1;
  white-space: nowrap;
}

.probe-btn:hover {
  color: var(--ek-ink);
  background: rgba(17, 24, 39, 0.04) !important;
}

.badge {
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--ek-muted);
  background: rgba(17, 24, 39, 0.05);
  border: 1px solid var(--ek-border);
  border-radius: 4px;
  padding: 2px 6px;
  line-height: 16px;
}

.item-title-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.kind-badge {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  border-radius: 4px;
  padding: 2px 7px;
  line-height: 16px;
  border: 1px solid transparent;
}

.kind-badge.is-http {
  color: #0b5f59;
  background: rgba(15, 118, 110, 0.1);
  border-color: rgba(15, 118, 110, 0.22);
}

.kind-badge.is-openai {
  color: #1d4ed8;
  background: rgba(37, 99, 235, 0.08);
  border-color: rgba(37, 99, 235, 0.2);
}

.provider-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 148px;
  gap: 10px 12px;
}

.provider-grid-http {
  grid-template-columns: minmax(0, 1fr) 140px;
}

.kv-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.kv-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) 28px;
  gap: 8px;
  align-items: center;
}

.kv-add {
  align-self: flex-start;
}

.body-textarea {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.5;
}


.span-main {
  grid-column: 1;
}

.span-side {
  grid-column: 2;
}

.span-full {
  grid-column: 1 / -1;
}

.stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.field label {
  font-size: 12px;
  line-height: 16px;
  color: var(--ek-muted);
}

.field .req {
  margin-left: 2px;
  color: #b42318;
}

.field-hint {
  margin: 0;
  font-size: 11px;
  line-height: 16px;
  color: var(--ek-muted);
}

.field-hint.is-error {
  color: #b42318;
}

.thinking-row .thinking-switch {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 32px;
}

.thinking-row .field-hint {
  margin: 0;
}

.max-tokens-input {
  width: 100%;
  max-width: 220px;
}

.item-warn {
  border-color: rgba(180, 35, 24, 0.35);
  background: rgba(180, 35, 24, 0.03);
}

.prompt-editor,
.code-surface {
  background: #f3f5f8 !important;
  border-color: rgba(17, 24, 39, 0.1) !important;
}

.prompt-editor:focus,
.code-surface:focus {
  background: #fff !important;
}

.empty {
  color: var(--ek-muted);
  font-size: 13px;
  padding: 4px 0;
}

.assert-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.assert-row {
  /* polarity | type | flexible fields... | delete — first two cols stay aligned */
  --assert-polarity-w: 64px;
  --assert-type-w: 160px;
  display: grid;
  gap: 8px;
  align-items: center;
}

.assert-row-value {
  grid-template-columns: var(--assert-polarity-w) var(--assert-type-w) minmax(0, 1fr) 28px;
}

.assert-row-range {
  grid-template-columns:
    var(--assert-polarity-w) var(--assert-type-w) minmax(88px, 120px) minmax(88px, 120px) 28px;
}

.assert-row-threshold {
  grid-template-columns: var(--assert-polarity-w) var(--assert-type-w) minmax(120px, 160px) 28px;
}

.assert-row-both {
  grid-template-columns:
    var(--assert-polarity-w) var(--assert-type-w) minmax(0, 1fr) minmax(88px, 112px) 28px;
}

.assert-row-both-grader {
  grid-template-columns:
    var(--assert-polarity-w) var(--assert-type-w) minmax(0, 1fr) minmax(80px, 100px)
    minmax(120px, 150px) 28px;
}

.assert-row-none {
  grid-template-columns: var(--assert-polarity-w) var(--assert-type-w) minmax(0, 1fr) 28px;
}

.assert-polarity {
  width: 100%;
  min-width: 0;
}

.assert-type {
  width: 100%;
  min-width: 0;
}

.assert-value,
.assert-threshold,
.assert-range,
.assert-grader {
  min-width: 0;
  width: 100%;
}

.assert-threshold :deep(.ant-input-number-input) {
  text-align: left;
}

.icon-btn {
  width: 28px;
  height: 28px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--ek-muted);
  background: transparent;
  border: none;
  box-shadow: none;
}

.icon-btn:hover {
  color: var(--ek-ink);
  background: transparent !important;
}

.mono {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 720px) {
  .panel-head,
  .panel-body {
    padding-left: 14px;
    padding-right: 14px;
  }

  .provider-grid {
    grid-template-columns: 1fr;
  }

  .span-main,
  .span-side,
  .span-full {
    grid-column: 1;
  }

  .assert-row-value,
  .assert-row-range,
  .assert-row-threshold,
  .assert-row-both,
  .assert-row-both-grader,
  .assert-row-none {
    grid-template-columns: 64px minmax(0, 1fr) 28px;
  }

  .assert-row .assert-polarity {
    grid-column: 1;
    grid-row: 1;
  }

  .assert-row .assert-type {
    grid-column: 2;
    grid-row: 1;
  }

  .assert-row .assert-value,
  .assert-row .assert-threshold,
  .assert-row .assert-range,
  .assert-row .assert-grader {
    grid-column: 1 / 3;
  }

  .assert-row .assert-value {
    grid-row: 2;
  }

  .assert-row-range .assert-range:nth-of-type(1) {
    grid-row: 2;
  }

  .assert-row-range .assert-range:nth-of-type(2) {
    grid-row: 3;
  }

  .assert-row-both .assert-threshold,
  .assert-row-both-grader .assert-threshold,
  .assert-row-threshold .assert-threshold {
    grid-row: 3;
  }

  .assert-row-both-grader .assert-grader {
    grid-row: 4;
  }

  .assert-row-value .assert-threshold {
    grid-row: 2;
  }

  .assert-row .icon-btn {
    grid-column: 3;
    grid-row: 1;
  }
}
</style>

<style>
.provider-create-modal-wrap .ant-modal-content {
  border-radius: 16px;
  overflow: hidden;
}

.provider-create-modal-wrap .provider-kind-pick {
  padding: 8px 0 12px;
}

.provider-create-modal-wrap .provider-kind-hint {
  margin: 0 0 16px;
  text-align: center;
  font-size: 13px;
  color: #6b7487;
}

.provider-create-modal-wrap .provider-kind-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.provider-create-modal-wrap .provider-kind-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  min-height: 112px;
  padding: 20px 18px;
  border-radius: 14px;
  border: 1px solid var(--ek-border, #e5e7eb);
  background: #fafbfc;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.15s ease;
}

.provider-create-modal-wrap .provider-kind-card:hover {
  transform: translateY(-1px);
}

.provider-create-modal-wrap .provider-kind-card.is-http:hover {
  border-color: rgba(15, 118, 110, 0.45);
  background: rgba(15, 118, 110, 0.06);
}

.provider-create-modal-wrap .provider-kind-card.is-openai:hover {
  border-color: rgba(37, 99, 235, 0.4);
  background: rgba(37, 99, 235, 0.05);
}

.provider-create-modal-wrap .provider-kind-title {
  font-size: 16px;
  font-weight: 650;
  color: #111827;
  line-height: 1.3;
}

.provider-create-modal-wrap .provider-kind-desc {
  font-size: 12px;
  color: #6b7487;
  line-height: 1.45;
}

.provider-create-modal-wrap .provider-modal-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 4px;
}

.provider-create-modal-wrap .provider-modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--ek-border, #e5e7eb);
}

.provider-create-modal-wrap .provider-modal-footer-right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.provider-create-modal-wrap .modal-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.provider-create-modal-wrap .field label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  color: #374151;
}

.provider-create-modal-wrap .field-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: #6b7487;
  line-height: 1.4;
}

.provider-create-modal-wrap .kv-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.provider-create-modal-wrap .kv-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) 28px;
  gap: 8px;
  align-items: center;
}

.provider-create-modal-wrap .body-textarea textarea,
.provider-create-modal-wrap .body-textarea {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 12px;
}

.test-import-modal-wrap .ant-modal-content {
  border-radius: 16px;
  overflow: hidden;
}

.test-import-modal-wrap .ant-modal-header {
  margin-bottom: 0;
  padding-bottom: 12px;
}

.test-import-modal-wrap .import-tips {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 10px;
  background: #f3f5f8;
  color: #4b5565;
  font-size: 13px;
  line-height: 1.6;
}

.test-import-modal-wrap .import-tips ul {
  margin: 0;
  padding-left: 18px;
}

.test-import-modal-wrap .import-tips li + li {
  margin-top: 6px;
}

.test-import-modal-wrap .import-tips a {
  color: var(--ek-accent-ink, #0b5f59);
  font-weight: 500;
}

.test-import-modal-wrap .import-tips a:hover {
  color: var(--ek-accent, #0f766e);
}

.test-import-modal-wrap .import-tips code {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 12px;
  padding: 0 4px;
  border-radius: 4px;
  background: rgba(15, 118, 110, 0.08);
  color: var(--ek-accent-ink, #0b5f59);
}

.test-import-modal-wrap .import-dragger .ant-upload-drag {
  border-radius: 12px;
  border-color: rgba(15, 118, 110, 0.35);
  background: rgba(15, 118, 110, 0.04);
  padding: 28px 16px;
}

.test-import-modal-wrap .import-dragger .ant-upload-drag:hover,
.test-import-modal-wrap .import-dragger .ant-upload-drag-hover {
  border-color: var(--ek-accent, #0f766e);
}

.test-import-modal-wrap .import-dragger .ant-upload-drag-icon {
  margin-bottom: 8px;
}

.test-import-modal-wrap .import-dragger .ant-upload-drag-icon .anticon {
  font-size: 40px;
  color: var(--ek-accent, #0f766e);
}

.test-import-modal-wrap .import-dragger .ant-upload-text {
  margin: 0 0 4px;
  font-size: 14px;
  color: #111827;
}

.test-import-modal-wrap .import-dragger .ant-upload-hint {
  margin: 0;
  font-size: 12px;
  color: #6b7487;
}
</style>
