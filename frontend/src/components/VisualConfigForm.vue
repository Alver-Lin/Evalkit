<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Upload, message } from 'ant-design-vue'
import {
  ApiOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  DownOutlined,
  DownloadOutlined,
  PlusOutlined,
  UpOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'
import type { UploadFile, UploadProps } from 'ant-design-vue'
import { api } from '@/api/client'
import JsonCheckTree from '@/components/JsonCheckTree.vue'
import type { GraderMeta } from '@/types'
import {
  assertNeedsGrader,
  assertShowsRange,
  assertTreeData,
  getAssertMeta,
} from '@/constants/assertOptions'
import {
  applyResponseExtract,
  buildHttpProbeBody,
  createVisualAssert,
  DEFAULT_AI_EXTRACT_HINT,
  defaultResponseExtract,
  discoverResponseFields,
  emptyHttpProvider,
  emptyProvider,
  ensureProviderExtract,
  guessExtractSource,
  headersToProbeRecord,
  inferProviderKind,
  parseResponseExtractFromTransform,
  persistProviderProbes,
  previewExtractOutput,
  providerHasExtraFields,
  providerHasId,
  providerHasSavedExtract,
  providerProbeFingerprint,
  providerProbeView,
  RESPONSE_EXTRACT_CLEAN_OPTIONS,
  type ProviderKind,
  type ProviderProbeStatus,
  type ResponseExtractCleanOp,
  type ResponseExtractConfig,
  type ResponseExtractSource,
  type ResponseExtractStrategy,
  type VisualAssert,
  type VisualConfig,
  type VisualHttpHeader,
  type VisualProvider,
} from '@/utils/promptfooConfig'
import {
  buildJsonPathTree,
  getValueByJsonPath,
  parseSampleJsonRoot,
  suggestAiPaths,
  type JsonPathNode,
} from '@/utils/jsonPathSelect'
import {
  buildExportedTestsCsv,
  draftsToVisualTests,
  parseImportedTests,
  sampleAssertYaml,
} from '@/utils/importTests'

const model = defineModel<VisualConfig>({ required: true })

const props = defineProps<{
  section: 'prompts' | 'providers' | 'tests'
  /** Used to persist probe capsules across reload / remount. */
  configId?: string
}>()

const varSyntax = '{{variable}}'
const promptVarSyntax = '{{prompt}}'
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

function removeProvider(index: number) {
  if (model.value.providers.length <= 1) return
  model.value.providers.splice(index, 1)
  if (probingIndex.value === index) probingIndex.value = null
  else if (probingIndex.value != null && probingIndex.value > index) probingIndex.value -= 1
  persistProbes()
  clampPage(providerPage, model.value.providers.length)
}

function providerMissingId(index: number): boolean {
  const provider = model.value.providers[index]
  if (!provider) return false
  return !providerHasId(provider) && providerHasExtraFields(provider)
}

type ProbeUiStatus = 'idle' | 'loading' | ProviderProbeStatus

const probingIndex = ref<number | null>(null)

function persistProbes() {
  if (!props.configId) return
  persistProviderProbes(props.configId, model.value.providers)
}

function probeStateOf(index: number): { status: ProbeUiStatus; message: string } {
  if (probingIndex.value === index) return { status: 'loading', message: '连接中' }
  const provider = model.value.providers[index]
  if (!provider) return { status: 'idle', message: '' }
  const view = providerProbeView(provider)
  if (!view) return { status: 'idle', message: '' }
  return view
}

function setProviderProbe(index: number, status: ProviderProbeStatus, msg: string) {
  const provider = model.value.providers[index]
  if (!provider) return
  provider.probe = {
    status,
    message: msg,
    fingerprint: providerProbeFingerprint(provider),
  }
  persistProbes()
}

function extractOf(provider: VisualProvider) {
  return ensureProviderExtract(provider)
}

function probeSampleOf(provider: VisualProvider) {
  const sample = provider.probeSample
  if (!sample?.text) return null
  if (sample.fingerprint !== providerProbeFingerprint(provider)) return null
  return sample
}

function discoveredFieldsOf(provider: VisualProvider): string[] {
  const sample = probeSampleOf(provider)
  if (!sample) return []
  return discoverResponseFields(sample.text, extractOf(provider).source)
}

function outputPreviewOf(provider: VisualProvider): string {
  const sample = probeSampleOf(provider)
  if (!sample) return ''
  return previewExtractOutput(sample.text, extractOf(provider))
}

function setExtractMode(provider: VisualProvider, mode: 'visual' | 'code') {
  if (mode === 'code') {
    provider.responseExtract = { ...ensureProviderExtract(provider), mode: 'code' }
    return
  }
  const parsed = parseResponseExtractFromTransform(provider.transformResponse)
  applyResponseExtract(
    provider,
    parsed.mode === 'visual' ? { ...parsed, mode: 'visual' } : { ...defaultResponseExtract(), mode: 'visual' },
  )
}

function setExtractSource(provider: VisualProvider, source: ResponseExtractSource) {
  applyResponseExtract(provider, { source, pick: 'all' })
}

function setExtractStrategy(provider: VisualProvider, strategy: ResponseExtractStrategy) {
  const patch: Partial<ResponseExtractConfig> = { strategy, pick: 'all' }
  const sample = probeSampleOf(provider)
  const root = sample ? parseSampleJsonRoot(sample.text, extractOf(provider).source) : null
  if (strategy === 'fields' && !extractOf(provider).fields.length) {
    // Prefer top-level keys for field-join; fall back to common leaf paths.
    const topLevel = discoveredFieldsOf(provider)
    patch.fields = topLevel.length
      ? topLevel.slice(0, 3)
      : root != null
        ? suggestAiPaths(root, 8)
        : ['answer', 'content', 'sql']
  }
  if (strategy === 'ai') {
    patch.aiScript = ''
    // Drop cleaners that smash nested JSON into "typetexttext…" noise.
    const clean = extractOf(provider).clean.filter((op) => op === 'trim' || op === 'newlines')
    patch.clean = clean
    if (!extractOf(provider).aiHint.trim()) {
      patch.aiHint = DEFAULT_AI_EXTRACT_HINT
    }
    if (!extractOf(provider).aiPaths.length) {
      patch.aiPaths = root != null ? suggestAiPaths(root, 12) : []
    }
  }
  applyResponseExtract(provider, patch)
}

function extractJsonTreeOf(provider: VisualProvider): JsonPathNode[] {
  const sample = probeSampleOf(provider)
  if (!sample) return []
  const root = parseSampleJsonRoot(sample.text, extractOf(provider).source)
  if (root == null) return []
  return buildJsonPathTree(root)
}

function usesResponseTree(provider: VisualProvider): boolean {
  const strategy = extractOf(provider).strategy
  return strategy === 'fields' || strategy === 'ai'
}

function selectedTreePathsOf(provider: VisualProvider): string[] {
  const cfg = extractOf(provider)
  return cfg.strategy === 'ai' ? cfg.aiPaths : cfg.fields
}

function toggleTreePaths(provider: VisualProvider, paths: string[], checked: boolean) {
  if (!paths.length) return
  const cfg = extractOf(provider)
  const pathSet = new Set(paths)
  if (cfg.strategy === 'ai') {
    const current = cfg.aiPaths
    const next = checked
      ? [...current, ...paths.filter((p) => !current.includes(p))]
      : current.filter((item) => !pathSet.has(item))
    applyResponseExtract(provider, {
      strategy: 'ai',
      aiPaths: next,
      // Re-selecting paths invalidates previous AI script until regenerated.
      aiScript: '',
    })
    return
  }
  const current = cfg.fields
  const next = checked
    ? [...current, ...paths.filter((p) => !current.includes(p))]
    : current.filter((item) => !pathSet.has(item))
  setExtractFields(provider, next)
}

function setAiHint(provider: VisualProvider, hint: string) {
  applyResponseExtract(provider, { strategy: 'ai', aiHint: hint })
}

const aiExtractingIndex = ref<number | null>(null)
const aiGraderByProvider = ref<Record<number, string>>({})

function aiGraderIdOf(index: number): string | undefined {
  return aiGraderByProvider.value[index] || firstGraderId() || undefined
}

function setAiGraderId(index: number, graderId: string | undefined) {
  if (!graderId) {
    delete aiGraderByProvider.value[index]
    return
  }
  aiGraderByProvider.value[index] = graderId
}

async function runAiExtract(index: number) {
  const provider = model.value.providers[index]
  if (!provider) return
  const sample = probeSampleOf(provider)
  if (!sample) {
    message.warning('请先「测试连通」获取测试响应')
    return
  }
  const cfg = extractOf(provider)
  if (!cfg.aiPaths.length) {
    message.warning('请先勾选测试响应中想保留的内容')
    return
  }
  const graderId = aiGraderIdOf(index)
  if (!graderId) {
    message.warning('请先在「模型评测配置」中添加评分模型，用于 AI 帮写')
    return
  }
  const root = parseSampleJsonRoot(sample.text, cfg.source)
  const selectedValues = cfg.aiPaths.map((path) => {
    const value = root != null ? getValueByJsonPath(root, path) : ''
    return {
      path,
      value: value == null ? '' : typeof value === 'string' ? value : JSON.stringify(value),
    }
  })
  aiExtractingIndex.value = index
  try {
    const result = await api.aiExtract({
      sample_text: sample.text,
      source: cfg.source,
      selected_values: selectedValues,
      hint: cfg.aiHint.trim() || DEFAULT_AI_EXTRACT_HINT,
      grader_id: graderId,
    })
    if (!result.ok || !result.ai_script) {
      message.error(result.message || 'AI 帮写失败')
      return
    }
    applyResponseExtract(provider, {
      strategy: 'ai',
      aiScript: result.ai_script,
    })
    message.success(result.message || '已生成提取规则')
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || 'AI 帮写失败'
    message.error(detail)
  } finally {
    if (aiExtractingIndex.value === index) aiExtractingIndex.value = null
  }
}

function toggleExtractClean(provider: VisualProvider, op: ResponseExtractCleanOp) {
  const current = extractOf(provider).clean
  const next = current.includes(op) ? current.filter((item) => item !== op) : [...current, op]
  applyResponseExtract(provider, { clean: next, pick: 'all' })
}

function setExtractFields(provider: VisualProvider, fields: string[]) {
  applyResponseExtract(provider, {
    strategy: 'fields',
    fields,
  })
}

function toggleExtractField(provider: VisualProvider, field: string, checked: boolean) {
  const current = extractOf(provider).fields
  const next = checked
    ? current.includes(field)
      ? current
      : [...current, field]
    : current.filter((item) => item !== field)
  setExtractFields(provider, next)
}

function extractRuleSummary(provider: VisualProvider): string {
  const cfg = extractOf(provider)
  if (cfg.mode === 'code') return '使用自定义 transformResponse 代码'
  const cleanLabel = cfg.clean.length
    ? cfg.clean
        .map((op) => RESPONSE_EXTRACT_CLEAN_OPTIONS.find((item) => item.value === op)?.label || op)
        .join('、')
    : '无'
  if (cfg.strategy === 'raw') {
    return cfg.source === 'sse'
      ? `SSE：原始 data 内容（数据清洗：${cleanLabel}）`
      : `JSON：完整响应（数据清洗：${cleanLabel}）`
  }
  if (cfg.strategy === 'ai') {
    const source = cfg.source === 'sse' ? 'SSE' : 'JSON'
    const pathLabel = cfg.aiPaths.length
      ? `已勾选 ${cfg.aiPaths.length} 项`
      : '（请勾选想保留的内容）'
    const scriptLabel = cfg.aiScript.trim() ? '，AI 规则已生成' : ''
    return `${source} → AI 取值 ${pathLabel}${scriptLabel}（数据清洗：${cleanLabel}）`
  }
  const fields = cfg.fields.length
    ? cfg.fields.length <= 3
      ? cfg.fields.join(' + ')
      : `已勾选 ${cfg.fields.length} 项`
    : '（请在上方勾选字段）'
  const source = cfg.source === 'sse' ? 'SSE' : 'JSON'
  return `${source} → 字段 ${fields}（数据清洗：${cleanLabel}）`
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
  if (!model.value.tests.length) {
    message.warning('请录入测试用例')
    return
  }
  probingIndex.value = index
  try {
    const kind = inferProviderKind(provider)
    const result = await api.probeProvider({
      id: provider.id.trim(),
      api_key: provider.apiKey.trim(),
      api_host: provider.apiHost.trim(),
      organization: provider.organization.trim(),
      method: kind === 'http' ? (provider.httpMethod || 'POST').toUpperCase() : undefined,
      headers: kind === 'http' ? headersToProbeRecord(provider.headers) : undefined,
      body: kind === 'http' ? buildHttpProbeBody(model.value) : undefined,
      timeout_sec:
        kind === 'http' && provider.timeoutSec != null ? Number(provider.timeoutSec) : undefined,
    })
    const fingerprint = providerProbeFingerprint(provider)
    if (result.sample_text) {
      provider.probeSample = {
        text: result.sample_text,
        statusCode: result.status_code,
        latencyMs: result.latency_ms,
        contentType: result.content_type,
        fingerprint,
      }
      // Only auto-suggest extract when nothing meaningful was saved yet.
      if (!providerHasSavedExtract(provider)) {
        const source = guessExtractSource(result.sample_text)
        const fields = discoverResponseFields(result.sample_text, source)
        applyResponseExtract(provider, {
          mode: 'visual',
          source,
          strategy: fields.length ? 'fields' : 'raw',
          fields: fields.length ? fields.slice(0, Math.min(3, fields.length)) : [],
        })
      }
      extractExpandedByIndex.value[index] = true
    } else if (provider.probeSample?.fingerprint === fingerprint) {
      // keep previous sample
    } else {
      provider.probeSample = null
    }
    if (result.ok) {
      setProviderProbe(index, 'success', result.message || '连接成功')
    } else {
      setProviderProbe(index, 'error', result.message || '连接失败')
      message.error(result.message)
    }
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || '连通测试失败'
    setProviderProbe(index, 'error', detail)
    message.error(detail)
  } finally {
    if (probingIndex.value === index) probingIndex.value = null
  }
}

const graders = ref<GraderMeta[]>([])
/** Visual extract panel expanded by provider index; default collapsed. */
const extractExpandedByIndex = ref<Record<number, boolean>>({})

function isExtractExpanded(index: number) {
  return extractExpandedByIndex.value[index] === true
}

function toggleExtractExpanded(index: number) {
  extractExpandedByIndex.value[index] = !isExtractExpanded(index)
}

const graderProviderOptions = computed(() =>
  graders.value.map((grader) => ({
    value: grader.id,
    label: grader.name.trim() || grader.provider_id.trim() || grader.id,
    disabled: !grader.provider_id.trim(),
  })),
)

function firstGraderId(): string | null {
  const found = graders.value.find((grader) => grader.provider_id.trim())
  return found?.id ?? null
}

async function loadGraders() {
  try {
    graders.value = await api.listGraders()
  } catch {
    graders.value = []
  }
}

onMounted(loadGraders)

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
const testImportModeOpen = ref(false)
const testImportFileList = ref<UploadFile[]>([])
const testImportSubmitting = ref(false)
/** 追加 = append；覆盖 = replace all existing tests. */
const testImportMode = ref<'append' | 'replace'>('append')

function isBlankTest(index: number) {
  const test = model.value.tests[index]
  if (!test) return true
  const vars = parseVarsObject(test.varsText)
  const hasVars = Object.values(vars).some((value) => value.trim())
  return !test.description.trim() && !hasVars && !(test.asserts?.length)
}

function openTestImport() {
  testImportFileList.value = []
  testImportMode.value = 'append'
  testImportModeOpen.value = false
  testImportOpen.value = true
}

function exportTests() {
  if (!model.value.tests.length) {
    message.warning('暂无测试用例可导出')
    return
  }
  const content = buildExportedTestsCsv(model.value.tests, promptVarNames.value, graders.value)
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
  link.href = url
  link.download = `evalkit-tests-${stamp}.csv`
  link.click()
  URL.revokeObjectURL(url)
  message.success(`已导出 ${model.value.tests.length} 条测试用例`)
}

function closeTestImport() {
  testImportOpen.value = false
  testImportModeOpen.value = false
  testImportFileList.value = []
  testImportMode.value = 'append'
}

function closeTestImportMode() {
  testImportModeOpen.value = false
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

function submitTestImport() {
  const file = testImportFileList.value[0]?.originFileObj as File | undefined
  if (!file) {
    message.warning('请先选择文件')
    return
  }
  testImportMode.value = 'append'
  testImportModeOpen.value = true
}

async function confirmTestImport() {
  const file = testImportFileList.value[0]?.originFileObj as File | undefined
  if (!file) {
    message.warning('请先选择文件')
    testImportModeOpen.value = false
    return
  }

  testImportSubmitting.value = true
  try {
    const text = await file.text()
    const drafts = parseImportedTests(text, file.name, graders.value)
    const imported = draftsToVisualTests(drafts, promptVarNames.value)
    if (!imported.length) {
      message.warning('未解析到有效用例')
      return
    }

    if (testImportMode.value === 'replace') {
      model.value.tests = imported
    } else if (
      !model.value.tests.length ||
      (model.value.tests.length === 1 && isBlankTest(0))
    ) {
      // Append mode: empty / single blank placeholder → replace for convenience.
      model.value.tests = imported
    } else {
      model.value.tests.push(...imported)
    }
    testPage.value = Math.ceil(model.value.tests.length / pageSize) || 1
    const withAsserts = imported.filter((item) => item.asserts.length).length
    const modeLabel = testImportMode.value === 'replace' ? '覆盖' : '追加'
    message.success(
      withAsserts
        ? `已${modeLabel}导入 ${imported.length} 条测试用例（其中 ${withAsserts} 条含断言）`
        : `已${modeLabel}导入 ${imported.length} 条测试用例`,
    )
    closeTestImport()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '导入失败')
  } finally {
    testImportSubmitting.value = false
  }
}

function removeTest(index: number) {
  if (index < 0 || index >= model.value.tests.length) return
  model.value.tests.splice(index, 1)
  if (!model.value.tests.length) {
    detailOpen.value = false
    detailIndex.value = 0
  } else if (detailOpen.value) {
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

function truncateText(text: string, maxLen = 10) {
  if (!text || text === '—') return text
  return text.length > maxLen ? `${text.slice(0, maxLen)}...` : text
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

function assertValueTooltip(assert: VisualAssert) {
  const text = String(assert.value ?? '').trim()
  return text || undefined
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
    const stillValid =
      assert.graderId != null && graders.value.some((g) => g.id === assert.graderId && g.provider_id.trim())
    if (!stillValid) {
      assert.graderId = firstGraderId()
    }
  } else {
    assert.graderId = null
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
              placeholder="请录入提示词或者请求体"
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
              <div class="field span-full extract-section">
                <div class="extract-head">
                  <div class="extract-title-wrap">
                    <label>响应提取</label>
                  </div>
                  <div class="extract-head-actions">
                    <a-radio-group
                      size="small"
                      :value="extractOf(model.providers[index]).mode"
                      @update:value="(v: string) => setExtractMode(model.providers[index], v as 'visual' | 'code')"
                    >
                      <a-radio-button value="visual">可视化</a-radio-button>
                      <a-radio-button value="code">高级代码</a-radio-button>
                    </a-radio-group>
                    <a-button
                      v-if="
                        extractOf(model.providers[index]).mode === 'visual' &&
                        (probeSampleOf(model.providers[index]) ||
                          providerHasSavedExtract(model.providers[index]))
                      "
                      type="text"
                      size="small"
                      class="extract-toggle-btn"
                      @click="toggleExtractExpanded(index)"
                    >
                      {{ isExtractExpanded(index) ? '收起' : '展开' }}
                      <UpOutlined v-if="isExtractExpanded(index)" />
                      <DownOutlined v-else />
                    </a-button>
                  </div>
                </div>

                <div
                  v-if="extractOf(model.providers[index]).mode === 'code'"
                  class="extract-code"
                >
                  <a-textarea
                    v-model:value="model.providers[index].transformResponse"
                    class="mono body-textarea"
                    :rows="8"
                    placeholder="(json, text) => text"
                  />
                  <p class="field-hint">
                    手写 transformResponse；切回可视化会按当前代码识别（无法识别则保留代码模式）
                  </p>
                </div>

                <template v-else>
                  <div
                    v-if="
                      !probeSampleOf(model.providers[index]) &&
                      !providerHasSavedExtract(model.providers[index])
                    "
                    class="extract-empty"
                  >
                    <p>尚未获取测试响应。请先「测试连通」，成功后将在此展示原始结果，并支持勾选字段预览 output。</p>
                  </div>

                  <template v-else>
                    <button
                      v-if="!isExtractExpanded(index)"
                      type="button"
                      class="extract-collapsed mono"
                      @click="toggleExtractExpanded(index)"
                    >
                      <span class="extract-collapsed-text">{{ extractRuleSummary(model.providers[index]) }}</span>
                      <DownOutlined class="extract-collapsed-icon" />
                    </button>

                    <template v-else>
                      <div v-if="probeSampleOf(model.providers[index])" class="sample-block">
                        <div class="sample-meta">
                          <span class="sample-label">
                            测试响应
                            <span
                              v-if="usesResponseTree(model.providers[index])"
                              class="sample-hint"
                            >
                              · 勾选要输出的字段
                            </span>
                          </span>
                          <span class="mono muted">
                            <template v-if="probeSampleOf(model.providers[index])!.statusCode != null">
                              HTTP {{ probeSampleOf(model.providers[index])!.statusCode }}
                            </template>
                            <template v-if="probeSampleOf(model.providers[index])!.latencyMs != null">
                              · {{ probeSampleOf(model.providers[index])!.latencyMs }}ms
                            </template>
                          </span>
                        </div>
                        <div
                          v-if="usesResponseTree(model.providers[index])"
                          class="sample-body sample-tree"
                        >
                          <JsonCheckTree
                            v-if="extractJsonTreeOf(model.providers[index]).length"
                            :nodes="extractJsonTreeOf(model.providers[index])"
                            :selected="selectedTreePathsOf(model.providers[index])"
                            @toggle="(paths, checked) => toggleTreePaths(model.providers[index], paths, checked)"
                          />
                          <p v-else class="field-hint">
                            无法解析为 JSON 树，请确认响应格式，或改用「原始内容」
                          </p>
                        </div>
                        <pre v-else class="sample-body mono">{{ probeSampleOf(model.providers[index])!.text }}</pre>
                      </div>
                      <div v-else class="extract-empty">
                        <p>已恢复保存的提取配置。重新「测试连通」可再次预览原始响应与 output。</p>
                      </div>

                      <div class="extract-panel">
                        <div class="extract-options">
                          <div class="extract-row">
                            <span class="extract-label">响应格式</span>
                            <a-radio-group
                              class="extract-seg"
                              size="small"
                              :value="extractOf(model.providers[index]).source"
                              @update:value="(v: string) => setExtractSource(model.providers[index], v as ResponseExtractSource)"
                            >
                              <a-radio-button value="sse">SSE 流</a-radio-button>
                              <a-radio-button value="json">整段 JSON</a-radio-button>
                            </a-radio-group>
                          </div>

                          <div class="extract-row">
                            <span class="extract-label">取值方式</span>
                            <a-radio-group
                              class="extract-seg"
                              size="small"
                              :value="extractOf(model.providers[index]).strategy"
                              @update:value="(v: string) => setExtractStrategy(model.providers[index], v as ResponseExtractStrategy)"
                            >
                              <a-radio-button value="raw">原始内容</a-radio-button>
                              <a-radio-button value="fields">选择字段拼接</a-radio-button>
                              <a-radio-button value="ai">AI 取值</a-radio-button>
                            </a-radio-group>
                          </div>

                          <div
                            v-if="extractOf(model.providers[index]).strategy === 'ai'"
                            class="extract-ai"
                          >
                            <div class="extract-ai-row">
                              <span class="extract-label">提取说明</span>
                              <a-input
                                :value="extractOf(model.providers[index]).aiHint || DEFAULT_AI_EXTRACT_HINT"
                                size="small"
                                placeholder="只要正文，去除结构冗余"
                                @update:value="(v: string) => setAiHint(model.providers[index], v)"
                              />
                            </div>
                            <div class="extract-ai-row">
                              <span class="extract-label">帮写模型</span>
                              <div class="extract-ai-actions">
                                <a-select
                                  class="extract-ai-grader"
                                  size="small"
                                  :value="aiGraderIdOf(index)"
                                  :options="graderProviderOptions"
                                  placeholder="选择模型评测配置"
                                  allow-clear
                                  @update:value="(v: string) => setAiGraderId(index, v)"
                                />
                                <a-button
                                  type="primary"
                                  size="small"
                                  :loading="aiExtractingIndex === index"
                                  :disabled="!probeSampleOf(model.providers[index])"
                                  @click="runAiExtract(index)"
                                >
                                  AI 帮写规则
                                </a-button>
                              </div>
                            </div>
                          </div>

                          <div class="extract-row">
                            <span class="extract-label">数据清洗</span>
                            <div class="extract-clean-list">
                              <button
                                v-for="opt in RESPONSE_EXTRACT_CLEAN_OPTIONS"
                                :key="opt.value"
                                type="button"
                                class="extract-clean-btn"
                                :class="{
                                  'is-active': extractOf(model.providers[index]).clean.includes(opt.value),
                                }"
                                @click="toggleExtractClean(model.providers[index], opt.value)"
                              >
                                {{ opt.label }}
                              </button>
                            </div>
                          </div>
                        </div>

                        <p class="extract-rule mono">{{ extractRuleSummary(model.providers[index]) }}</p>

                        <div class="output-preview">
                          <div class="sample-meta">
                            <span class="sample-label">最终 output 预览</span>
                          </div>
                          <pre class="output-body mono">{{ outputPreviewOf(model.providers[index]) || '—' }}</pre>
                        </div>
                      </div>
                    </template>
                  </template>
                </template>
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
              <a-tooltip
                v-if="showsValue(assertItem)"
                class="assert-value assert-value-tip"
                :title="assertValueTooltip(assertItem)"
                placement="topLeft"
                overlay-class-name="assert-value-tooltip"
              >
                <a-input
                  v-model:value="assertItem.value"
                  :placeholder="valuePlaceholder(assertItem)"
                />
              </a-tooltip>
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
                v-model:value="assertItem.graderId"
                class="assert-grader"
                :options="graderProviderOptions"
                :dropdown-match-select-width="false"
                allow-clear
                placeholder="评分模型"
                :not-found-content="graders.length ? undefined : '请先在「模型评测配置」中添加'"
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
            <a-button class="add-btn" @click="exportTests">
              <UploadOutlined /> 导出
            </a-button>
            <a-button class="add-btn" @click="openTestImport">
              <DownloadOutlined /> 导入
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
              :locale="{ emptyText: '暂无测试用例' }"
              :data-source="pagedTestIndexes.map((index) => ({ index }))"
            >
              <a-table-column title="ID" :width="100">
                <template #default="{ record }">
                  <span class="mono">test{{ record.index + 1 }}</span>
                </template>
              </a-table-column>
              <a-table-column title="测试项" ellipsis>
                <template #default="{ record }">
                  <a-tooltip
                    placement="topLeft"
                    :title="model.tests[record.index].description || undefined"
                  >
                    <span class="cell-ellipsis">
                      {{ model.tests[record.index].description || '—' }}
                    </span>
                  </a-tooltip>
                </template>
              </a-table-column>
              <a-table-column title="变量" ellipsis>
                <template #default="{ record }">
                  <a-tooltip
                    placement="topLeft"
                    :title="
                      testVarsPreview(model.tests[record.index].varsText) === '—'
                        ? undefined
                        : testVarsPreview(model.tests[record.index].varsText)
                    "
                  >
                    <span class="mono tiny cell-ellipsis">
                      {{ testVarsPreview(model.tests[record.index].varsText) }}
                    </span>
                  </a-tooltip>
                </template>
              </a-table-column>
              <a-table-column title="断言" :width="120" ellipsis>
                <template #default="{ record }">
                  <a-tooltip
                    placement="topLeft"
                    :title="
                      testAssertPreview(model.tests[record.index].asserts) === '—'
                        ? undefined
                        : testAssertPreview(model.tests[record.index].asserts)
                    "
                  >
                    <span class="cell-ellipsis">
                      {{ truncateText(testAssertPreview(model.tests[record.index].asserts), 10) }}
                    </span>
                  </a-tooltip>
                </template>
              </a-table-column>
              <a-table-column title="操作" :width="120">
                <template #default="{ record }">
                  <div class="row-actions">
                    <a @click="openTestDetail(record.index)">编辑</a>
                    <a class="danger" @click.prevent="removeTest(record.index)">删除</a>
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
        :title="detailTest ? `编辑 test${detailIndex + 1}` : '编辑测试用例'"
        placement="right"
        :width="720"
        destroy-on-close
        root-class-name="test-detail-drawer"
      >
        <div v-if="detailTest" class="detail-form">
          <section class="detail-block">
            <label class="detail-label" for="detail-description">测试项</label>
            <a-textarea
              id="detail-description"
              v-model:value="detailTest.description"
              class="detail-textarea"
              :auto-size="{ minRows: 2, maxRows: 4 }"
              placeholder="例如：辖区内已婚人员数量"
              allow-clear
            />
          </section>

          <section class="detail-block">
            <div class="detail-label">变量</div>
            <div v-if="!promptVarNames.length" class="detail-empty">
              提示词中尚未定义变量，请先使用 {{ varSyntax }}
            </div>
            <div v-else class="detail-var-list">
              <div v-for="name in promptVarNames" :key="name" class="detail-var-row">
                <code class="detail-var-key" :title="name">{{ name }}</code>
                <a-input
                  :value="getVarValue(detailIndex, name)"
                  :placeholder="`输入 ${name}`"
                  allow-clear
                  @update:value="(value: string) => setVarValue(detailIndex, name, value)"
                />
              </div>
            </div>
          </section>

          <section class="detail-block">
            <div class="detail-label-row">
              <div class="detail-label">断言</div>
              <a-button
                v-if="detailTest.asserts.length"
                type="link"
                size="small"
                class="detail-add-link"
                @click="addAssert(detailIndex)"
              >
                <PlusOutlined /> 添加
              </a-button>
            </div>
            <div v-if="!detailTest.asserts.length" class="detail-empty is-action">
              <span>暂无断言</span>
              <a-button type="link" size="small" class="detail-add-link" @click="addAssert(detailIndex)">
                <PlusOutlined /> 添加断言
              </a-button>
            </div>
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
                <a-tooltip
                  v-if="showsValue(assertItem)"
                  class="assert-value assert-value-tip"
                  :title="assertValueTooltip(assertItem)"
                  placement="topLeft"
                  overlay-class-name="assert-value-tooltip"
                >
                  <a-input
                    v-model:value="assertItem.value"
                    :placeholder="valuePlaceholder(assertItem)"
                  />
                </a-tooltip>
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
                  v-model:value="assertItem.graderId"
                  class="assert-grader"
                  :options="graderProviderOptions"
                  :dropdown-match-select-width="false"
                  allow-clear
                  placeholder="评分模型"
                  :not-found-content="graders.length ? undefined : '请先在「模型评测配置」中添加'"
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
          </section>
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
              选择文件后点击「开始导入」，可在二次确认中选择<strong>追加导入</strong>或<strong>覆盖导入</strong>。
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
            @click="submitTestImport"
          >
            开始导入
          </a-button>
        </template>
      </a-modal>

      <a-modal
        v-model:open="testImportModeOpen"
        title="选择导入方式"
        :width="420"
        centered
        :mask-closable="false"
        wrap-class-name="test-import-mode-modal-wrap"
        @cancel="closeTestImportMode"
      >
        <p class="import-mode-desc">请选择如何处理当前已有的测试用例：</p>
        <a-radio-group v-model:value="testImportMode" class="import-mode-radios">
          <a-radio value="append" class="import-mode-option">
            <span class="import-mode-title">追加导入</span>
            <span class="import-mode-hint">拼接到现有用例后；若当前仅有一条空白用例则直接替换</span>
          </a-radio>
          <a-radio value="replace" class="import-mode-option">
            <span class="import-mode-title">覆盖导入</span>
            <span class="import-mode-hint">用本次导入内容替换全部现有用例</span>
          </a-radio>
        </a-radio-group>

        <template #footer>
          <a-button @click="closeTestImportMode">取消</a-button>
          <a-button type="primary" :loading="testImportSubmitting" @click="confirmTestImport">
            确认导入
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

.test-table :deep(.ant-table-cell-ellipsis) {
  overflow: hidden;
}

.cell-ellipsis {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  gap: 0;
}

.detail-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-block: 20px;
}

.detail-block:first-child {
  padding-block-start: 4px;
}

.detail-block:last-child {
  padding-block-end: 0;
}

.detail-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 24px;
}

.detail-label {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--ek-ink);
}

.detail-textarea :deep(textarea) {
  resize: none;
  line-height: 1.55;
}

.detail-var-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-var-row {
  display: grid;
  grid-template-columns: 7rem minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}

.detail-var-key {
  display: block;
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  font-family: var(--font-code, var(--ek-mono, ui-monospace, monospace));
  font-size: 12px;
  line-height: 1.4;
  color: var(--ek-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-empty {
  display: flex;
  align-items: center;
  min-height: 40px;
  color: var(--ek-muted);
  font-size: 13px;
  line-height: 1.4;
}

.detail-empty.is-action {
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border: 1px dashed var(--ui-border-strong, var(--ek-border));
  border-radius: 8px;
  background: color-mix(in srgb, var(--ek-raised) 55%, transparent);
}

.detail-add-link {
  padding-inline: 0 !important;
  height: auto !important;
  color: var(--ek-accent-ink) !important;
}

.detail-add-link:hover {
  color: var(--ek-accent) !important;
}

.assert-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ui-gap-tight, 8px);
  margin-block-end: var(--space-1, 4px);
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

.extract-section {
  gap: 10px;
}

.extract-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.extract-head-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.extract-head :deep(.ant-radio-group) {
  display: inline-flex;
  flex: 0 0 auto;
}

.extract-head :deep(.ant-radio-button-wrapper) {
  height: 28px;
  line-height: 26px;
  padding: 0 12px;
  font-size: 12px;
}

.extract-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 8px;
  color: var(--ek-secondary);
  font-size: 12px;
}

.extract-toggle-btn:hover {
  color: var(--ek-accent-ink);
}

.extract-collapsed {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--ek-border);
  border-radius: 8px;
  background: var(--ek-surface);
  color: var(--ek-muted);
  font-size: 12px;
  line-height: 1.5;
  text-align: left;
  cursor: pointer;
}

.extract-collapsed:hover {
  border-color: rgba(15, 118, 110, 0.35);
  color: var(--ek-secondary);
}

.extract-collapsed-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.extract-collapsed-icon {
  flex: 0 0 auto;
  font-size: 10px;
  color: var(--ek-muted);
}

.extract-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.extract-head label {
  margin: 0;
}

.extract-empty {
  padding: 14px 16px;
  border-radius: 8px;
  border: 1px dashed var(--ek-border);
  background: rgba(17, 24, 39, 0.02);
}

.extract-empty p {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--ek-muted);
}

.sample-block,
.output-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.sample-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.sample-label {
  font-size: 12px;
  color: var(--ek-secondary);
  font-weight: 500;
}

.sample-hint {
  color: var(--ek-muted);
  font-weight: 400;
}

.sample-body,
.output-body {
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--ek-border);
  background: #0f172a0a;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  max-height: 220px;
  overflow: auto;
}

.sample-body.sample-tree {
  white-space: normal;
  max-height: 420px;
  background: rgba(15, 118, 110, 0.03);
  border-color: rgba(15, 118, 110, 0.18);
}

.output-body {
  background: rgba(15, 118, 110, 0.06);
  border-color: rgba(15, 118, 110, 0.16);
  color: var(--ek-ink);
  max-height: 180px;
}

.extract-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  border-radius: 10px;
  border: 1px solid var(--ek-border);
  background: var(--ek-surface);
  box-shadow: inset 0 0 0 1px rgba(17, 24, 39, 0.02);
}

.extract-options {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.extract-row,
.extract-fields {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  align-items: center;
  column-gap: 16px;
  row-gap: 8px;
}

.extract-fields {
  align-items: start;
}

.extract-label {
  font-size: 12px;
  line-height: 28px;
  color: var(--ek-secondary);
  font-weight: 500;
  white-space: nowrap;
}

.extract-fields-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.extract-clean-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.extract-clean-btn {
  height: 30px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--ek-border);
  background: #fff;
  color: var(--ek-secondary);
  font-size: 12px;
  line-height: 28px;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}

.extract-clean-btn:hover {
  color: var(--ek-accent-ink);
  border-color: rgba(15, 118, 110, 0.35);
}

.extract-clean-btn.is-active {
  color: var(--ek-accent-ink);
  background: rgba(15, 118, 110, 0.1);
  border-color: rgba(15, 118, 110, 0.45);
  font-weight: 500;
}

.extract-seg {
  display: inline-flex !important;
  flex-wrap: wrap;
  gap: 8px;
}

.extract-seg :deep(.ant-radio-button-wrapper) {
  height: 30px;
  line-height: 28px;
  padding: 0 12px;
  margin: 0 !important;
  font-size: 12px;
  color: var(--ek-secondary);
  background: #fff;
  border: 1px solid var(--ek-border) !important;
  border-radius: 8px !important;
  box-shadow: none !important;
}

.extract-seg :deep(.ant-radio-button-wrapper:not(:first-child)::before) {
  display: none;
}

.extract-seg :deep(.ant-radio-button-wrapper:first-child),
.extract-seg :deep(.ant-radio-button-wrapper:last-child) {
  border-radius: 8px !important;
}

.extract-seg :deep(.ant-radio-button-wrapper:hover) {
  color: var(--ek-accent-ink);
  border-color: rgba(15, 118, 110, 0.35) !important;
}

.extract-seg :deep(.ant-radio-button-wrapper-checked:not(.ant-radio-button-wrapper-disabled)) {
  color: var(--ek-accent-ink) !important;
  background: rgba(15, 118, 110, 0.1) !important;
  border-color: rgba(15, 118, 110, 0.45) !important;
  font-weight: 500;
}

.extract-seg :deep(.ant-radio-button-wrapper-checked:not(.ant-radio-button-wrapper-disabled):hover) {
  color: var(--ek-accent-ink) !important;
  background: rgba(15, 118, 110, 0.14) !important;
  border-color: rgba(15, 118, 110, 0.55) !important;
}

.extract-seg :deep(.ant-radio-button-wrapper-checked:not(.ant-radio-button-wrapper-disabled)::before) {
  display: none;
}

.field-check-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  min-width: 0;
}

.field-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 8px;
  border-radius: 6px;
  background: var(--ek-bg);
  border: 1px solid var(--ek-border);
  font-size: 12px;
  color: var(--ek-ink);
  cursor: pointer;
  user-select: none;
}

.extract-select {
  width: 100%;
  min-width: 0;
}

.extract-fields .field-hint {
  margin: 0;
}

.extract-ai {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 2px;
}

.extract-ai-row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.extract-ai-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.extract-ai-grader {
  flex: 1 1 180px;
  min-width: 140px;
  max-width: 280px;
}

.extract-rule {
  margin: 0;
  padding: 0;
  color: var(--ek-muted);
  font-size: 11px;
  line-height: 1.5;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.extract-code {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.muted {
  color: var(--ek-muted);
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

.assert-value-tip {
  display: block;
  min-width: 0;
  width: 100%;
}

.assert-value-tip :deep(.ant-input) {
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

.test-import-mode-modal-wrap .ant-modal-content {
  border-radius: 16px;
  overflow: hidden;
}

.test-import-mode-modal-wrap .import-mode-desc {
  margin: 0 0 14px;
  font-size: 13px;
  color: #4b5565;
  line-height: 1.5;
}

.test-import-mode-modal-wrap .import-mode-radios {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

.test-import-mode-modal-wrap .import-mode-option {
  display: flex;
  align-items: flex-start;
  width: 100%;
  margin-inline-end: 0;
  padding: 12px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fafbfc;
}

.test-import-mode-modal-wrap .import-mode-option.ant-radio-wrapper-checked {
  border-color: rgba(15, 118, 110, 0.45);
  background: rgba(15, 118, 110, 0.06);
}

.test-import-mode-modal-wrap .import-mode-title {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: #111827;
  line-height: 22px;
}

.test-import-mode-modal-wrap .import-mode-hint {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: #6b7280;
  line-height: 18px;
  white-space: normal;
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

<style>
.test-detail-drawer .ant-drawer-body {
  padding-block: var(--space-3, 12px) var(--space-6, 24px);
  padding-inline: var(--space-6, 24px);
  background: var(--surface-raised, var(--ek-surface, #fff));
}

.test-detail-drawer .ant-drawer-header {
  border-block-end: 1px solid var(--ui-border, var(--ek-border));
}

.test-detail-drawer .ant-drawer-title {
  font-size: 15px;
  font-weight: 600;
}

.assert-value-tooltip {
  max-width: min(520px, 80vw);
}

.assert-value-tooltip .ant-tooltip-inner {
  max-width: min(520px, 80vw);
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
  text-align: left;
  line-height: 1.5;
}
</style>
