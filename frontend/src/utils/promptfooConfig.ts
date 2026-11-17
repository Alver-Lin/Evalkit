import { dump, load } from 'js-yaml'
import {
  assertDefaultThreshold,
  assertNeedsGrader,
  assertShowsRange,
  assertShowsThreshold,
  getAssertMeta,
} from '@/constants/assertOptions'

export interface VisualAssert {
  /** Base assertion type without `not-` prefix. */
  type: string
  value: string
  /** Optional numeric threshold for similarity / cost / latency etc. */
  threshold?: number | null
  /** Inclusive min for range assertions such as word-count. */
  min?: number | null
  /** Inclusive max for range assertions such as word-count. */
  max?: number | null
  /** Index into VisualConfig.providers used as grader (llm-rubric / similar). */
  graderProviderIndex?: number | null
  /** When true, serialize as `not-<type>` in YAML. */
  negated?: boolean
}

function finiteOrNull(value: unknown): number | null {
  if (value == null || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function createVisualAssert(type = 'contains', graderProviderIndex: number | null = null): VisualAssert {
  const meta = getAssertMeta(type)
  const baseType = meta.value || type
  return {
    type: baseType,
    value: '',
    threshold: meta.hasThreshold ? (meta.defaultThreshold ?? null) : null,
    min: meta.hasRange ? (meta.defaultMin ?? null) : null,
    max: meta.hasRange ? (meta.defaultMax ?? null) : null,
    graderProviderIndex: meta.needsGrader ? graderProviderIndex : null,
    negated: false,
  }
}

/** Parse assertion value for YAML: JSON / comma list / plain string. */
function serializeAssertValue(raw: string, type: string): unknown {
  const trimmed = raw.trim()
  if (!trimmed) return undefined
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      return JSON.parse(trimmed)
    } catch {
      // keep as string
    }
  }
  if (
    type === 'contains-all' ||
    type === 'contains-any' ||
    type === 'icontains-all' ||
    type === 'icontains-any'
  ) {
    if (trimmed.includes(',')) {
      return trimmed
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
    }
  }
  return trimmed
}

function isOpenAiCompatibleProvider(providerId: string): boolean {
  const id = providerId.trim().toLowerCase()
  return id.startsWith('openai:') || id === 'deepseek' || id.startsWith('deepseek:')
}

export function inferProviderKind(provider: Pick<VisualProvider, 'kind' | 'id'>): ProviderKind {
  if (provider.kind === 'http' || provider.kind === 'openai') return provider.kind
  const id = provider.id.trim().toLowerCase()
  if (id.startsWith('http://') || id.startsWith('https://')) return 'http'
  return 'openai'
}

function headersToRecord(headers: VisualHttpHeader[] | undefined): Record<string, string> | undefined {
  if (!headers?.length) return undefined
  const out: Record<string, string> = {}
  for (const row of headers) {
    const key = String(row?.key || '').trim()
    if (!key) continue
    out[key] = String(row?.value ?? '')
  }
  return Object.keys(out).length ? out : undefined
}

function toHttpProviderYaml(provider: VisualProvider): Record<string, unknown> | null {
  const url = provider.id.trim()
  if (!url) return null
  const config: Record<string, unknown> = {}
  const method = (provider.httpMethod || 'POST').trim().toUpperCase() || 'POST'
  config.method = method
  const timeout =
    provider.timeoutSec != null && Number.isFinite(Number(provider.timeoutSec))
      ? Number(provider.timeoutSec)
      : null
  if (timeout != null && timeout > 0) config.timeout = timeout
  const headers = headersToRecord(provider.headers)
  if (headers) config.headers = headers
  // Request body comes from the prompts step; provider only references {{prompt}}.
  config.body = '{{prompt}}'
  // Default SSE transformResponse is injected at run time, not written to YAML.

  const out: Record<string, unknown> = { id: url }
  if (provider.label.trim()) out.label = provider.label.trim()
  if (Object.keys(config).length) out.config = config
  return out
}

function toProviderYaml(provider: VisualProvider): Record<string, unknown> | null {
  if (inferProviderKind(provider) === 'http') {
    return toHttpProviderYaml(provider)
  }

  if (!provider.id.trim()) return null
  const resolved = resolveProviderTarget(provider.id, provider.apiHost)
  const config: Record<string, unknown> = {}
  if (provider.apiKey.trim()) config.apiKey = provider.apiKey.trim()
  if (resolved.apiHost) config.apiBaseUrl = resolved.apiHost
  if (provider.organization.trim()) config.organization = provider.organization.trim()

  const maxTokens =
    provider.maxTokens != null && Number.isFinite(Number(provider.maxTokens))
      ? Number(provider.maxTokens)
      : null
  if (maxTokens != null && maxTokens > 0) config.max_tokens = maxTokens

  // Thinking models often return content=null (Qwen/vLLM) or very long streams
  // (DeepSeek) that get terminated; keep off unless user explicitly enables.
  if (isOpenAiCompatibleProvider(resolved.id)) {
    if (provider.enableThinking) {
      // Keep Thinking in provider output for report display; assertions strip it
      // via transform so word-count / rubrics only see the final answer.
      config.showThinking = true
      config.passthrough = {
        chat_template_kwargs: { enable_thinking: true },
      }
    } else {
      config.showThinking = false
      config.passthrough = {
        thinking: { type: 'disabled' },
        chat_template_kwargs: { enable_thinking: false },
      }
    }
  }

  const out: Record<string, unknown> = { id: resolved.id }
  if (provider.label.trim()) out.label = provider.label.trim()
  else if (/^deepseek/i.test(provider.id.trim())) out.label = provider.id.trim()
  if (Object.keys(config).length) out.config = config
  return out
}

/**
 * Strip promptfoo's `Thinking: ...` prefix before assertions run.
 * Must be a single-line expression (promptfoo wraps it as `return <expr>`).
 */
const STRIP_THINKING_TRANSFORM =
  '(() => { const t = String(output ?? ""); if (!/^\\s*Thinking\\s*:/i.test(t)) return t; const parts = t.trim().split(/\\n\\s*\\n\\s*\\n+/).map((s) => s.trim()).filter(Boolean); if (parts.length >= 2) return parts[parts.length - 1]; const paras = t.trim().split(/\\n\\s*\\n+/).map((s) => s.trim()).filter(Boolean); return paras.length >= 2 ? paras[paras.length - 1] : t; })()'

const CHAR_COUNT_MARKER = '/* evalkit:char-count */'

/**
 * EvalKit injects Chinese rubricPrompt only at run time (backend), not into
 * user-facing YAML. This marker detects our default so we can strip old copies.
 */
const EVALKIT_RUBRIC_MARKER = '你是评分助手，根据用户给定的评分标准（rubric）评判模型输出。'

function isEvalkitChineseRubricPrompt(raw: unknown): boolean {
  if (raw == null || raw === '') return false
  if (typeof raw === 'string') return raw.includes(EVALKIT_RUBRIC_MARKER)
  if (!Array.isArray(raw)) return false
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const content = (item as Record<string, unknown>).content
    if (typeof content === 'string' && content.includes(EVALKIT_RUBRIC_MARKER)) return true
  }
  return false
}

/** Remove EvalKit-injected rubricPrompt from defaultTest so YAML stays clean. */
function stripEvalkitRubricPrompt(
  defaultTest: Record<string, unknown>,
): Record<string, unknown> | null {
  const next = { ...defaultTest }
  const options =
    next.options && typeof next.options === 'object' && !Array.isArray(next.options)
      ? { ...(next.options as Record<string, unknown>) }
      : null

  if (options && isEvalkitChineseRubricPrompt(options.rubricPrompt)) {
    delete options.rubricPrompt
  }

  if (options && Object.keys(options).length) {
    next.options = options
  } else {
    delete next.options
  }

  if (!Object.keys(next).length) return null
  return next
}

/** Build JS assertion: CN/EN/digits/punctuation each count as 1; whitespace ignored. */
function buildCharCountScript(min: number | null, max: number | null, negated: boolean): string {
  const minLit = min == null ? 'null' : String(min)
  const maxLit = max == null ? 'null' : String(max)
  const passExpr = negated ? '!inRange' : 'inRange'
  return [
    CHAR_COUNT_MARKER,
    "const text = String(output ?? '').replace(/\\s/g, '');",
    'const n = [...text].length;',
    `const min = ${minLit};`,
    `const max = ${maxLit};`,
    'const inRange = (min == null || n >= min) && (max == null || n <= max);',
    `const pass = ${passExpr};`,
    'if (pass) return true;',
    "const rangeLabel = min != null && max != null ? (min + '-' + max) : min != null ? ('>=' + min) : ('<=' + max);",
    "return { pass: false, score: 0, reason: '字符数 ' + n + ' 不在范围 ' + rangeLabel };",
  ].join('\n')
}

function parseCharCountScript(script: string): { min: number | null; max: number | null } | null {
  if (!script.includes('evalkit:char-count')) return null
  const minMatch = script.match(/\bconst min = (null|\d+)\s*;/)
  const maxMatch = script.match(/\bconst max = (null|\d+)\s*;/)
  if (!minMatch || !maxMatch) return null
  return {
    min: minMatch[1] === 'null' ? null : Number(minMatch[1]),
    max: maxMatch[1] === 'null' ? null : Number(maxMatch[1]),
  }
}

function serializeOneAssert(
  assert: VisualAssert,
  providers: VisualProvider[],
): Record<string, unknown> | null {
  const type = assert.type.trim()
  if (!type) return null
  const meta = getAssertMeta(type)
  const showsValue = meta.hasValue !== false
  const showsThreshold = Boolean(meta.hasThreshold)
  const showsRange = Boolean(meta.hasRange)
  const value = showsValue ? serializeAssertValue(String(assert.value ?? ''), type) : undefined
  const threshold =
    showsThreshold && assert.threshold != null && Number.isFinite(Number(assert.threshold))
      ? Number(assert.threshold)
      : undefined
  const min = showsRange ? finiteOrNull(assert.min) : null
  const max = showsRange ? finiteOrNull(assert.max) : null

  if (showsRange) {
    if (min == null && max == null) return null
    if (min != null && max != null && min > max) return null
  }
  // Threshold-only: require threshold
  if (showsThreshold && !showsValue && threshold == null) return null
  // Value required (with or without threshold)
  if (showsValue && !meta.valueOptional && value === undefined) return null

  // Replace promptfoo word-count with JS char-count (supports Chinese).
  if (type === 'word-count') {
    return {
      type: 'javascript',
      value: buildCharCountScript(min, max, Boolean(assert.negated)),
      transform: STRIP_THINKING_TRANSFORM,
    }
  }

  const out: Record<string, unknown> = {
    type: (() => {
      const base = type
      const stripped = base.toLowerCase().startsWith('not-') ? base.slice(4) || 'contains' : base
      return assert.negated ? `not-${stripped}` : stripped
    })(),
  }
  if (value !== undefined) out.value = value
  if (threshold !== undefined) out.threshold = threshold
  // Grade final answer only; report UI still shows Thinking separately from raw output.
  out.transform = STRIP_THINKING_TRANSFORM

  if (meta.needsGrader && assert.graderProviderIndex != null) {
    const provider = providers[assert.graderProviderIndex]
    const yamlProvider = provider ? toProviderYaml(provider) : null
    if (yamlProvider) out.provider = yamlProvider
  }
  return out
}

export interface VisualTest {
  description: string
  varsText: string
  asserts: VisualAssert[]
}

export type ProviderKind = 'openai' | 'http'

export interface VisualHttpHeader {
  key: string
  value: string
}

export interface VisualProvider {
  kind?: ProviderKind
  id: string
  label: string
  apiKey: string
  apiHost: string
  organization: string
  /** When true, enable model thinking; default off for stable eval output. */
  enableThinking?: boolean
  /** Optional max_tokens for OpenAI-compatible chat calls. */
  maxTokens?: number | null
  /** UI-only description for custom HTTP providers. */
  description?: string
  httpMethod?: string
  timeoutSec?: number | null
  headers?: VisualHttpHeader[]
  bodyText?: string
  transformResponse?: string
}

export function emptyProvider(): VisualProvider {
  return {
    kind: 'openai',
    id: '',
    label: '',
    apiKey: '',
    apiHost: '',
    organization: '',
    enableThinking: false,
    maxTokens: 1024,
  }
}

export function emptyHttpProvider(): VisualProvider {
  return {
    kind: 'http',
    id: '',
    label: '',
    apiKey: '',
    apiHost: '',
    organization: '',
    description: '',
    httpMethod: 'POST',
    timeoutSec: 60,
    headers: [{ key: 'Content-Type', value: 'application/json' }],
    bodyText: '{{prompt}}',
    transformResponse: '',
  }
}

export function providerHasId(provider: VisualProvider): boolean {
  return Boolean(provider.id.trim())
}

export function providerHasExtraFields(provider: VisualProvider): boolean {
  if (inferProviderKind(provider) === 'http') {
    return Boolean(
      provider.label.trim() ||
        (provider.description || '').trim() ||
        (provider.headers || []).some((h) => h.key.trim() || h.value.trim()),
    )
  }
  return Boolean(
    provider.label.trim() ||
      provider.apiKey.trim() ||
      provider.apiHost.trim() ||
      provider.organization.trim(),
  )
}

export interface VisualProviderValidation {
  ok: boolean
  message?: string
  /** 0-based index of the first problematic provider row. */
  index?: number
}

function isValidHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

/** Block silent drop of Key/Host when Provider ID is missing. */
export function validateVisualProviders(providers: VisualProvider[]): VisualProviderValidation {
  for (let i = 0; i < providers.length; i += 1) {
    const provider = providers[i]
    const kind = inferProviderKind(provider)

    if (kind === 'http') {
      if (!providerHasId(provider) && providerHasExtraFields(provider)) {
        return {
          ok: false,
          index: i,
          message: `供应商 provider${i + 1} 缺少 URL（必填）`,
        }
      }
      if (providerHasId(provider) && !isValidHttpUrl(provider.id.trim())) {
        return {
          ok: false,
          index: i,
          message: `供应商 provider${i + 1} 的 URL 无效，请填写完整 http(s):// 地址`,
        }
      }
      if (providerHasId(provider) && !(provider.httpMethod || '').trim()) {
        return {
          ok: false,
          index: i,
          message: `供应商 provider${i + 1} 缺少请求方法`,
        }
      }
      continue
    }

    if (!providerHasId(provider) && providerHasExtraFields(provider)) {
      return {
        ok: false,
        index: i,
        message: `供应商 provider${i + 1} 缺少 Provider ID（必填）。可填 openai:chat:模型名、deepseek，或新建自定义 HTTP`,
      }
    }
  }

  if (!providers.some(providerHasId)) {
    return {
      ok: false,
      index: 0,
      message: '请至少填写一个供应商（OpenAI 兼容 Provider ID，或自定义 HTTP 的 URL）',
    }
  }

  return { ok: true }
}

/** Map common aliases to IDs that promptfoo 0.125.x can resolve. */
export function resolveProviderTarget(id: string, apiHost = ''): { id: string; apiHost: string } {
  const raw = id.trim()
  const host = apiHost.trim()
  if (!raw) return { id: '', apiHost: host }

  const lower = raw.toLowerCase()
  // Bare "deepseek" or "deepseek:<model>" — use OpenAI-compatible endpoint.
  // deepseek-chat was retired; current defaults are deepseek-flash / deepseek-v4-pro.
  if (lower === 'deepseek' || lower.startsWith('deepseek:')) {
    const model =
      lower === 'deepseek' ? 'deepseek-flash' : raw.slice(raw.indexOf(':') + 1).trim() || 'deepseek-flash'
    return {
      id: model.startsWith('openai:') ? model : `openai:chat:${model}`,
      apiHost: host || 'https://api.deepseek.com/v1',
    }
  }

  return { id: raw, apiHost: host }
}

export interface VisualConfig {
  description: string
  prompts: string[]
  providers: VisualProvider[]
  defaultAsserts: VisualAssert[]
  tests: VisualTest[]
}

function asList(value: unknown): unknown[] {
  if (value == null) return []
  return Array.isArray(value) ? value : [value]
}

function stringifyVars(vars: Record<string, unknown> | undefined): string {
  if (!vars || typeof vars !== 'object') return ''
  try {
    return JSON.stringify(vars, null, 2)
  } catch {
    return ''
  }
}

function parseVars(text: string): Record<string, unknown> {
  const trimmed = text.trim()
  if (!trimmed) return {}
  try {
    const parsed = JSON.parse(trimmed)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>
    }
  } catch {
    // fall through to key=value lines
  }
  const result: Record<string, unknown> = {}
  for (const line of trimmed.split('\n')) {
    const idx = line.indexOf(':')
    if (idx === -1) continue
    const key = line.slice(0, idx).trim()
    const value = line.slice(idx + 1).trim()
    if (key) result[key] = value
  }
  return result
}

function detectEnableThinking(config: Record<string, unknown>): boolean {
  const passthrough =
    config.passthrough && typeof config.passthrough === 'object' && !Array.isArray(config.passthrough)
      ? (config.passthrough as Record<string, unknown>)
      : {}
  const thinking =
    (passthrough.thinking && typeof passthrough.thinking === 'object'
      ? (passthrough.thinking as Record<string, unknown>)
      : null) ||
    (config.thinking && typeof config.thinking === 'object'
      ? (config.thinking as Record<string, unknown>)
      : null)
  const kwargs =
    passthrough.chat_template_kwargs && typeof passthrough.chat_template_kwargs === 'object'
      ? (passthrough.chat_template_kwargs as Record<string, unknown>)
      : null
  if (thinking && String(thinking.type || '').toLowerCase() === 'enabled') return true
  if (kwargs && kwargs.enable_thinking === true) return true
  if (thinking && String(thinking.type || '').toLowerCase() === 'disabled') return false
  if (kwargs && kwargs.enable_thinking === false) return false
  // Default off for stable eval output.
  return false
}

function normalizeMaxTokens(config: Record<string, unknown>): number | null {
  const raw = config.max_tokens ?? config.maxTokens
  if (raw == null || raw === '') return 1024
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : 1024
}

function normalizeHeaders(raw: unknown): VisualHttpHeader[] {
  if (!raw) return []
  if (Array.isArray(raw)) {
    return raw.map((row) => {
      if (row && typeof row === 'object' && !Array.isArray(row)) {
        const obj = row as Record<string, unknown>
        return { key: String(obj.key || ''), value: String(obj.value ?? '') }
      }
      return { key: '', value: '' }
    })
  }
  if (typeof raw === 'object') {
    return Object.entries(raw as Record<string, unknown>).map(([key, value]) => ({
      key,
      value: value == null ? '' : String(value),
    }))
  }
  return []
}

function normalizeBodyText(raw: unknown): string {
  if (raw == null) return ''
  if (typeof raw === 'string') return raw
  try {
    return JSON.stringify(raw, null, 2)
  } catch {
    return String(raw)
  }
}

function normalizeTimeoutSec(config: Record<string, unknown>): number | null {
  const raw = config.timeout ?? config.timeoutSec ?? config.timeout_seconds
  if (raw == null || raw === '') return 60
  const n = Number(raw)
  // promptfoo may use ms in some versions; treat values > 1000 as ms.
  if (!Number.isFinite(n) || n <= 0) return 60
  if (n > 1000) return Math.round(n / 1000)
  return n
}

function normalizeProvider(item: unknown): VisualProvider {
  if (typeof item === 'string') {
    const base = emptyProvider()
    const id = item
    const kind = inferProviderKind({ id, kind: undefined })
    if (kind === 'http') {
      return { ...emptyHttpProvider(), id, kind: 'http' }
    }
    return { ...base, id, kind: 'openai' }
  }
  if (item && typeof item === 'object') {
    const obj = item as Record<string, unknown>
    const config =
      obj.config && typeof obj.config === 'object' && !Array.isArray(obj.config)
        ? (obj.config as Record<string, unknown>)
        : {}
    const id = String(obj.id || obj.provider || '')
    const kind = inferProviderKind({ id, kind: obj.kind as ProviderKind | undefined })

    if (kind === 'http') {
      const method = String(config.method || obj.method || 'POST').toUpperCase() || 'POST'
      const headers = normalizeHeaders(config.headers)
      return {
        ...emptyHttpProvider(),
        kind: 'http',
        id,
        label: String(obj.label || ''),
        description: String(obj.description || ''),
        httpMethod: method,
        timeoutSec: normalizeTimeoutSec(config),
        headers: headers.length ? headers : [{ key: 'Content-Type', value: 'application/json' }],
        bodyText: normalizeBodyText(config.body),
        // Default SSE transform lives at run time only; keep visual YAML clean.
        transformResponse: '',
      }
    }

    return {
      kind: 'openai',
      id,
      label: String(obj.label || ''),
      apiKey: String(config.apiKey || config.api_key || ''),
      apiHost: String(config.apiBaseUrl || config.apiHost || config.baseUrl || ''),
      organization: String(config.organization || config.organizationId || ''),
      enableThinking: detectEnableThinking(config),
      maxTokens: normalizeMaxTokens(config),
    }
  }
  return emptyProvider()
}

function splitAssertType(raw: string): { type: string; negated: boolean } {
  const type = raw.trim() || 'contains'
  if (type.toLowerCase().startsWith('not-')) {
    return { type: type.slice(4) || 'contains', negated: true }
  }
  return { type, negated: false }
}

function serializeAssertType(assert: VisualAssert): string {
  const base = assert.type.trim() || 'contains'
  const stripped = base.toLowerCase().startsWith('not-') ? base.slice(4) || 'contains' : base
  return assert.negated ? `not-${stripped}` : stripped
}

function matchGraderProviderIndex(raw: unknown, providers: VisualProvider[]): number | null {
  if (raw == null || !providers.length) return null
  let id = ''
  let apiHost = ''
  if (typeof raw === 'string') {
    id = raw.trim()
  } else if (typeof raw === 'object') {
    const obj = raw as Record<string, unknown>
    id = String(obj.id || '').trim()
    const config =
      obj.config && typeof obj.config === 'object' && !Array.isArray(obj.config)
        ? (obj.config as Record<string, unknown>)
        : {}
    apiHost = String(config.apiBaseUrl || config.apiHost || config.baseUrl || '').trim()
  }
  if (!id) return null

  for (let i = 0; i < providers.length; i += 1) {
    const provider = providers[i]
    if (!provider.id.trim()) continue
    if (provider.id === id) return i
    const resolved = resolveProviderTarget(provider.id, provider.apiHost)
    if (resolved.id === id) {
      if (!apiHost || !resolved.apiHost || resolved.apiHost === apiHost) return i
    }
  }
  return null
}

export function normalizeAssert(item: unknown, providers: VisualProvider[] = []): VisualAssert {
  if (item && typeof item === 'object') {
    const obj = item as Record<string, unknown>
    const value = obj.value
    let { type, negated } = splitAssertType(String(obj.type || 'contains'))
    let threshold: number | null = null
    if (obj.threshold != null && obj.threshold !== '') {
      const n = Number(obj.threshold)
      if (Number.isFinite(n)) threshold = n
    } else if (assertShowsThreshold(type)) {
      threshold = assertDefaultThreshold(type) ?? null
    }
    let normalizedValue =
      value == null || value === ''
        ? ''
        : typeof value === 'string'
          ? value
          : JSON.stringify(value)

    // Map our JS char-count assertion back to the visual "word-count" (字符数) control.
    if (type === 'javascript' && typeof value === 'string') {
      const parsed = parseCharCountScript(value)
      if (parsed) {
        return {
          type: 'word-count',
          value: '',
          threshold: null,
          min: parsed.min,
          max: parsed.max,
          graderProviderIndex: null,
          negated: /const pass = !inRange/.test(value) ? true : negated,
        }
      }
    }

    let min = assertShowsRange(type) ? finiteOrNull(obj.min) : null
    let max = assertShowsRange(type) ? finiteOrNull(obj.max) : null
    // Legacy promptfoo word-count: value number or value: { min, max }
    if (type === 'word-count') {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        const range = value as Record<string, unknown>
        min = finiteOrNull(range.min)
        max = finiteOrNull(range.max)
        normalizedValue = ''
      } else {
        const legacy = finiteOrNull(normalizedValue) ?? threshold
        if (legacy != null) {
          min = legacy
          max = legacy
          normalizedValue = ''
          threshold = null
        }
      }
    }

    return {
      type,
      value: assertShowsRange(type) ? '' : normalizedValue,
      threshold: assertShowsThreshold(type) ? threshold : null,
      min: assertShowsRange(type) ? min : null,
      max: assertShowsRange(type) ? max : null,
      graderProviderIndex: assertNeedsGrader(type)
        ? matchGraderProviderIndex(obj.provider, providers)
        : null,
      negated,
    }
  }
  return createVisualAssert('contains')
}

/** Parse assert YAML text (list or `{ assert: [...] }`). JSON-only payloads are rejected. */
export function parseAssertYaml(text: string, providers: VisualProvider[] = []): VisualAssert[] {
  const trimmed = text.trim()
  if (!trimmed) return []
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    throw new Error('断言请使用 YAML 格式（例如以 `- type:` 开头的列表）')
  }
  let data: unknown
  try {
    data = load(trimmed)
  } catch {
    throw new Error('断言 YAML 解析失败')
  }
  if (data == null) return []
  if (typeof data === 'object' && !Array.isArray(data)) {
    const record = data as Record<string, unknown>
    if ('assert' in record) data = record.assert
    else if ('asserts' in record) data = record.asserts
    else if ('type' in record) data = [record]
    else throw new Error('断言 YAML 格式无效')
  }
  return asList(data).map((item) => normalizeAssert(item, providers))
}

function normalizeTest(item: unknown, providers: VisualProvider[] = []): VisualTest {
  if (!item || typeof item !== 'object') {
    return { description: '', varsText: '{\n  \n}', asserts: [] }
  }
  const obj = item as Record<string, unknown>
  return {
    description: String(obj.description || ''),
    varsText: stringifyVars((obj.vars as Record<string, unknown>) || {}),
    asserts: asList(obj.assert).map((assertItem) => normalizeAssert(assertItem, providers)),
  }
}

export function createEmptyVisualConfig(description = ''): VisualConfig {
  return {
    description,
    prompts: [''],
    providers: [emptyProvider()],
    defaultAsserts: [],
    tests: [
      {
        description: '',
        varsText: '{\n  "question": ""\n}',
        asserts: [],
      },
    ],
  }
}

export function yamlToVisual(yamlContent: string, fallbackDescription = ''): VisualConfig {
  let parsed: Record<string, unknown> = {}
  try {
    const data = load(yamlContent || '')
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      parsed = data as Record<string, unknown>
    }
  } catch {
    return createEmptyVisualConfig(fallbackDescription)
  }

  const prompts = asList(parsed.prompts).map((p) => {
    if (typeof p === 'string') return p
    if (p && typeof p === 'object') {
      const obj = p as Record<string, unknown>
      return String(obj.raw || obj.id || obj.label || '')
    }
    return ''
  })

  const defaultTest =
    parsed.defaultTest && typeof parsed.defaultTest === 'object' && !Array.isArray(parsed.defaultTest)
      ? (parsed.defaultTest as Record<string, unknown>)
      : {}

  const providers = asList(parsed.providers || parsed.targets).map(normalizeProvider)

  const normalizedProviders = providers.length ? providers : [emptyProvider()]

  return {
    description: String(parsed.description || fallbackDescription || ''),
    prompts: prompts.length ? prompts : [''],
    providers: normalizedProviders,
    defaultAsserts: asList(defaultTest.assert).map((item) =>
      normalizeAssert(item, normalizedProviders),
    ),
    tests: asList(parsed.tests).map((item) => normalizeTest(item, normalizedProviders)),
  }
}

export function visualToYaml(visual: VisualConfig, existingYaml = ''): string {
  let base: Record<string, unknown> = {}
  try {
    const parsed = load(existingYaml || '')
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      base = { ...(parsed as Record<string, unknown>) }
    }
  } catch {
    base = {}
  }

  base.description = visual.description || ''
  base.prompts = visual.prompts.map((p) => p.trim()).filter(Boolean)

  base.providers = visual.providers
    .map((p) => toProviderYaml(p))
    .filter((p): p is Record<string, unknown> => p != null)

  const defaultAsserts = visual.defaultAsserts
    .map((a) => serializeOneAssert(a, visual.providers))
    .filter((a): a is Record<string, unknown> => a != null)

  const existingDefault =
    base.defaultTest && typeof base.defaultTest === 'object' && !Array.isArray(base.defaultTest)
      ? { ...(base.defaultTest as Record<string, unknown>) }
      : {}

  if (defaultAsserts.length) {
    const cleaned = stripEvalkitRubricPrompt({
      ...existingDefault,
      assert: defaultAsserts,
    })
    if (cleaned) base.defaultTest = cleaned
    else delete base.defaultTest
  } else {
    delete existingDefault.assert
    const cleaned = stripEvalkitRubricPrompt(existingDefault)
    if (cleaned) base.defaultTest = cleaned
    else delete base.defaultTest
  }

  base.tests = visual.tests.map((t) => {
    const test: Record<string, unknown> = {
      vars: parseVars(t.varsText),
    }
    if (t.description.trim()) test.description = t.description.trim()
    const asserts = t.asserts
      .map((a) => serializeOneAssert(a, visual.providers))
      .filter((a): a is Record<string, unknown> => a != null)
    if (asserts.length) test.assert = asserts
    return test
  })

  return dump(base, {
    lineWidth: 120,
    noRefs: true,
  })
}
