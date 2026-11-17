import { dump, load } from 'js-yaml'
import {
  assertDefaultThreshold,
  assertNeedsGrader,
  assertShowsRange,
  assertShowsThreshold,
  getAssertMeta,
} from '@/constants/assertOptions'
import type { GraderMeta } from '@/types'

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
  /** Id of a grader from 模型评测配置 (llm-rubric / similar). */
  graderId?: string | null
  /** When true, serialize as `not-<type>` in YAML. */
  negated?: boolean
}

function finiteOrNull(value: unknown): number | null {
  if (value == null || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function createVisualAssert(type = 'contains', graderId: string | null = null): VisualAssert {
  const meta = getAssertMeta(type)
  const baseType = meta.value || type
  return {
    type: baseType,
    value: '',
    threshold: meta.hasThreshold ? (meta.defaultThreshold ?? null) : null,
    min: meta.hasRange ? (meta.defaultMin ?? null) : null,
    max: meta.hasRange ? (meta.defaultMax ?? null) : null,
    graderId: meta.needsGrader ? graderId : null,
    negated: false,
  }
}

/** Convert a grader meta record into VisualProvider for YAML serialization. */
export function graderMetaToVisualProvider(grader: GraderMeta): VisualProvider {
  const kind = grader.kind === 'http' ? 'http' : 'openai'
  return {
    kind,
    id: grader.provider_id || '',
    label: grader.name || '',
    apiKey: grader.api_key || '',
    apiHost: grader.api_host || '',
    organization: grader.organization || '',
    enableThinking: Boolean(grader.enable_thinking),
    maxTokens: grader.max_tokens ?? 1024,
    description: grader.description || '',
    httpMethod: (grader.http_method || 'POST').toUpperCase() || 'POST',
    timeoutSec: grader.timeout_sec ?? 60,
    headers: (grader.headers || []).map((h) => ({ key: h.key || '', value: h.value || '' })),
    transformResponse: grader.transform_response || '',
  }
}

function findGraderById(graders: GraderMeta[], graderId: string | null | undefined): GraderMeta | null {
  if (!graderId) return null
  return graders.find((g) => g.id === graderId) || null
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
  const transform = (provider.transformResponse || '').trim()
  if (transform) config.transformResponse = transform

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
  graders: GraderMeta[] = [],
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

  if (meta.needsGrader && assert.graderId) {
    const grader = findGraderById(graders, assert.graderId)
    const yamlProvider = grader ? toProviderYaml(graderMetaToVisualProvider(grader)) : null
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

export type ProviderProbeStatus = 'success' | 'error'

/** UI-only connectivity result; never written to YAML. */
export interface ProviderProbe {
  status: ProviderProbeStatus
  message: string
  /** Hash of connection-relevant fields; stale when config changes. */
  fingerprint: string
}

/** UI-only sample from connectivity probe for extract preview. */
export interface ProviderProbeSample {
  text: string
  statusCode?: number | null
  latencyMs?: number | null
  contentType?: string | null
  fingerprint: string
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
  /** UI-only response extract settings; compiled into transformResponse. */
  responseExtract?: ResponseExtractConfig
  /** UI-only probe result; stripped from YAML serialization. */
  probe?: ProviderProbe | null
  /** UI-only latest probe response body for visual extract. */
  probeSample?: ProviderProbeSample | null
}

/** Fingerprint of fields that affect connectivity testing. */
export function providerProbeFingerprint(provider: VisualProvider): string {
  const kind = inferProviderKind(provider)
  const headers = (provider.headers || [])
    .map((h) => `${h.key.trim()}=${h.value}`)
    .filter((pair) => !pair.startsWith('='))
    .sort()
    .join('&')
  return [
    kind,
    provider.id.trim(),
    (provider.httpMethod || 'POST').trim().toUpperCase(),
    provider.apiKey.trim(),
    provider.apiHost.trim(),
    provider.organization.trim(),
    headers,
  ].join('|')
}

export function providerProbeView(
  provider: VisualProvider,
): { status: ProviderProbeStatus; message: string } | null {
  const probe = provider.probe
  if (!probe) return null
  if (probe.fingerprint !== providerProbeFingerprint(provider)) return null
  return { status: probe.status, message: probe.message }
}

function probeStorageKey(configId: string) {
  return `evalkit.providerProbe.${configId}`
}

export function persistProviderProbes(configId: string, providers: VisualProvider[]) {
  if (!configId || typeof localStorage === 'undefined') return
  const map: Record<string, ProviderProbe> = {}
  for (const provider of providers) {
    const view = providerProbeView(provider)
    if (!view || !provider.probe) continue
    map[provider.probe.fingerprint] = {
      status: view.status,
      message: view.message,
      fingerprint: provider.probe.fingerprint,
    }
  }
  try {
    if (Object.keys(map).length) localStorage.setItem(probeStorageKey(configId), JSON.stringify(map))
    else localStorage.removeItem(probeStorageKey(configId))
  } catch {
    // ignore quota / private mode
  }
}

export function restoreProviderProbes(configId: string, providers: VisualProvider[]) {
  if (!configId || typeof localStorage === 'undefined') return
  let map: Record<string, ProviderProbe> = {}
  try {
    const raw = localStorage.getItem(probeStorageKey(configId))
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return
    map = parsed as Record<string, ProviderProbe>
  } catch {
    return
  }
  for (const provider of providers) {
    const fp = providerProbeFingerprint(provider)
    const saved = map[fp]
    if (!saved || (saved.status !== 'success' && saved.status !== 'error')) continue
    provider.probe = {
      status: saved.status,
      message: String(saved.message || (saved.status === 'success' ? '连接成功' : '连接失败')),
      fingerprint: fp,
    }
  }
}

/** Default SSE-friendly transform for custom HTTP providers. */
export const DEFAULT_SSE_TRANSFORM_RESPONSE = `(json, text) => {
  const chunks = [];
  for (const line of String(text || '').split('\\n')) {
    const t = line.trim();
    if (!t.startsWith('data:')) continue;
    const raw = t.replace(/^data:\\s?/, '');
    if (!raw || raw === '[DONE]') continue;
    chunks.push(raw);
  }
  return chunks.join('\\n') || text;
}`

export type ResponseExtractSource = 'sse' | 'json'
export type ResponseExtractStrategy = 'raw' | 'fields'
export type ResponseExtractPick = 'all' | 'last'
export type ResponseExtractJoin = '\n' | ' ' | ''
export type ResponseExtractMode = 'visual' | 'code'

/** UI-friendly response extraction; compiled into transformResponse. */
export interface ResponseExtractConfig {
  mode: ResponseExtractMode
  source: ResponseExtractSource
  strategy: ResponseExtractStrategy
  fields: string[]
  joinWith: ResponseExtractJoin
  pick: ResponseExtractPick
}

export const RESPONSE_EXTRACT_FIELD_PRESETS = [
  'answer',
  'content',
  'text',
  'message',
  'sql',
  'data',
  'result',
  'output',
] as const

export function defaultResponseExtract(): ResponseExtractConfig {
  return {
    mode: 'visual',
    source: 'sse',
    strategy: 'raw',
    fields: [],
    joinWith: '\n',
    pick: 'all',
  }
}

const EXTRACT_MARKER_RE = /\/\*\s*evalkit-extract:(\{[\s\S]*?\})\s*\*\//

function normalizeExtractFields(fields: unknown): string[] {
  if (!Array.isArray(fields)) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of fields) {
    const name = String(item || '')
      .trim()
      .replace(/^\.+/, '')
    if (!name || seen.has(name)) continue
    seen.add(name)
    out.push(name)
  }
  return out
}

export function normalizeResponseExtract(raw: unknown): ResponseExtractConfig {
  const base = defaultResponseExtract()
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return base
  const obj = raw as Record<string, unknown>
  const mode = obj.mode === 'code' ? 'code' : 'visual'
  const source = obj.source === 'json' ? 'json' : 'sse'
  const strategy = obj.strategy === 'fields' ? 'fields' : 'raw'
  const pick = obj.pick === 'last' ? 'last' : 'all'
  const joinWith =
    obj.joinWith === ' ' || obj.joinWith === '' || obj.joinWith === '\n' ? obj.joinWith : '\n'
  return {
    mode,
    source,
    strategy,
    fields: normalizeExtractFields(obj.fields),
    joinWith,
    pick,
  }
}

function extractMarkerPayload(config: ResponseExtractConfig): string {
  return JSON.stringify({
    source: config.source,
    strategy: config.strategy,
    fields: config.fields,
    joinWith: config.joinWith,
    pick: config.pick,
  })
}

/** Build promptfoo transformResponse from visual extract settings. */
export function buildTransformResponse(config: ResponseExtractConfig): string {
  const normalized = normalizeResponseExtract({ ...config, mode: 'visual' })
  if (
    normalized.source === 'sse' &&
    normalized.strategy === 'raw' &&
    normalized.pick === 'all' &&
    normalized.joinWith === '\n'
  ) {
    return DEFAULT_SSE_TRANSFORM_RESPONSE
  }

  const marker = `/* evalkit-extract:${extractMarkerPayload(normalized)} */`
  const fieldsLit = JSON.stringify(normalized.fields)
  const joinLit = JSON.stringify(normalized.joinWith)
  const pickLast = normalized.pick === 'last' ? 'true' : 'false'
  const useFields = normalized.strategy === 'fields' ? 'true' : 'false'

  if (normalized.source === 'json') {
    return `(json, text) => {
  ${marker}
  const fields = ${fieldsLit};
  const joinWith = ${joinLit};
  const useFields = ${useFields};
  let obj = json;
  if (obj == null || typeof obj !== 'object') {
    try { obj = JSON.parse(String(text || '')); } catch { obj = null; }
  }
  if (!useFields) {
    return obj != null ? JSON.stringify(obj) : String(text || '');
  }
  if (!obj || typeof obj !== 'object') return String(text || '');
  const parts = fields.map((f) => {
    const v = obj[f];
    if (v == null || v === '') return '';
    return typeof v === 'string' ? v : JSON.stringify(v);
  }).filter(Boolean);
  return parts.join(joinWith) || String(text || '');
}`
  }

  return `(json, text) => {
  ${marker}
  const fields = ${fieldsLit};
  const joinWith = ${joinLit};
  const pickLast = ${pickLast};
  const useFields = ${useFields};
  const values = [];
  for (const line of String(text || '').split('\\n')) {
    const t = line.trim();
    if (!t.startsWith('data:')) continue;
    const raw = t.replace(/^data:\\s?/, '');
    if (!raw || raw === '[DONE]') continue;
    let piece = '';
    if (useFields) {
      let obj = null;
      try { obj = JSON.parse(raw); } catch {}
      if (!obj || typeof obj !== 'object') continue;
      const parts = fields.map((f) => {
        const v = obj[f];
        if (v == null || v === '') return '';
        return typeof v === 'string' ? v : JSON.stringify(v);
      }).filter(Boolean);
      if (!parts.length) continue;
      piece = parts.join(joinWith);
    } else {
      piece = raw;
    }
    if (pickLast) values.length = 0;
    values.push(piece);
  }
  return values.join(joinWith) || text;
}`
}

export function parseResponseExtractFromTransform(transform: string | null | undefined): ResponseExtractConfig {
  const text = String(transform || '').trim()
  if (!text || text === DEFAULT_SSE_TRANSFORM_RESPONSE.trim()) {
    return defaultResponseExtract()
  }
  const match = text.match(EXTRACT_MARKER_RE)
  if (match?.[1]) {
    try {
      return normalizeResponseExtract({ ...JSON.parse(match[1]), mode: 'visual' })
    } catch {
      // fall through to code mode
    }
  }
  return {
    ...defaultResponseExtract(),
    mode: 'code',
  }
}

export function ensureProviderExtract(provider: VisualProvider): ResponseExtractConfig {
  if (!provider.responseExtract) {
    provider.responseExtract = parseResponseExtractFromTransform(provider.transformResponse)
  }
  return provider.responseExtract
}

export function applyResponseExtract(provider: VisualProvider, patch: Partial<ResponseExtractConfig>) {
  const current = ensureProviderExtract(provider)
  const next = normalizeResponseExtract({ ...current, ...patch })
  provider.responseExtract = next
  if (next.mode === 'visual') {
    provider.transformResponse = buildTransformResponse(next)
  }
}

function collectObjectFields(value: unknown, out: Set<string>) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return
  for (const key of Object.keys(value as Record<string, unknown>)) {
    if (key) out.add(key)
  }
}

/** Parse SSE data: payloads or whole JSON body into event objects. */
export function parseProbeEvents(sampleText: string, source: ResponseExtractSource = 'sse'): unknown[] {
  const text = String(sampleText || '')
  if (!text.trim()) return []

  if (source === 'json') {
    try {
      return [JSON.parse(text)]
    } catch {
      return [text]
    }
  }

  const events: unknown[] = []
  for (const line of text.split('\n')) {
    const t = line.trim()
    if (!t.startsWith('data:')) continue
    const raw = t.replace(/^data:\s?/, '')
    if (!raw || raw === '[DONE]') continue
    try {
      events.push(JSON.parse(raw))
    } catch {
      events.push(raw)
    }
  }
  if (!events.length) {
    try {
      events.push(JSON.parse(text))
    } catch {
      // keep empty — not SSE/JSON
    }
  }
  return events
}

export function discoverResponseFields(
  sampleText: string,
  source: ResponseExtractSource = 'sse',
): string[] {
  const fields = new Set<string>()
  for (const event of parseProbeEvents(sampleText, source)) {
    collectObjectFields(event, fields)
  }
  const preferred = RESPONSE_EXTRACT_FIELD_PRESETS.filter((name) => fields.has(name))
  const rest = Array.from(fields)
    .filter((name) => !preferred.includes(name as (typeof RESPONSE_EXTRACT_FIELD_PRESETS)[number]))
    .sort((a, b) => a.localeCompare(b))
  return [...preferred, ...rest]
}

function fieldValueText(value: unknown): string {
  if (value == null || value === '') return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/** Client-side mirror of visual transformResponse for live preview. */
export function previewExtractOutput(
  sampleText: string,
  config: ResponseExtractConfig,
): string {
  const cfg = normalizeResponseExtract(config)
  const text = String(sampleText || '')
  if (!text) return ''

  if (cfg.source === 'json') {
    let obj: unknown = null
    try {
      obj = JSON.parse(text)
    } catch {
      obj = null
    }
    if (cfg.strategy !== 'fields') {
      return obj != null ? fieldValueText(obj) : text
    }
    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return text
    const parts = cfg.fields
      .map((f) => fieldValueText((obj as Record<string, unknown>)[f]))
      .filter(Boolean)
    return parts.join(cfg.joinWith) || text
  }

  const values: string[] = []
  for (const line of text.split('\n')) {
    const t = line.trim()
    if (!t.startsWith('data:')) continue
    const raw = t.replace(/^data:\s?/, '')
    if (!raw || raw === '[DONE]') continue
    let piece = ''
    if (cfg.strategy === 'fields') {
      let obj: Record<string, unknown> | null = null
      try {
        const parsed = JSON.parse(raw)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          obj = parsed as Record<string, unknown>
        }
      } catch {
        obj = null
      }
      if (!obj) continue
      const parts = cfg.fields.map((f) => fieldValueText(obj![f])).filter(Boolean)
      if (!parts.length) continue
      piece = parts.join(cfg.joinWith)
    } else {
      piece = raw
    }
    if (cfg.pick === 'last') values.length = 0
    values.push(piece)
  }
  return values.join(cfg.joinWith) || text
}

export function guessExtractSource(sampleText: string): ResponseExtractSource {
  const text = String(sampleText || '')
  if (/^\s*data:/m.test(text)) return 'sse'
  const trimmed = text.trim()
  if (
    (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
    (trimmed.startsWith('[') && trimmed.endsWith(']'))
  ) {
    return 'json'
  }
  return 'sse'
}

/** Replace `{{var}}` placeholders using test vars (for HTTP probe body). */
export function renderTemplateVars(
  template: string,
  vars: Record<string, unknown>,
): string {
  return String(template || '').replace(/\{\{\s*([a-zA-Z_][\w]*)\s*\}\}/g, (_, key: string) => {
    if (!(key in vars)) return ''
    const value = vars[key]
    if (value == null) return ''
    if (typeof value === 'string') return value
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  })
}

export function buildHttpProbeBody(visual: VisualConfig): string {
  const prompt = visual.prompts.find((item) => item.trim()) || '{}'
  const vars = parseVars(visual.tests[0]?.varsText || '{}')
  return renderTemplateVars(prompt, vars)
}

export function headersToProbeRecord(
  headers: VisualHttpHeader[] | undefined,
): Record<string, string> {
  const out: Record<string, string> = {}
  for (const item of headers || []) {
    const key = item.key.trim()
    if (!key) continue
    out[key] = item.value
  }
  return out
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
  const responseExtract = defaultResponseExtract()
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
    transformResponse: buildTransformResponse(responseExtract),
    responseExtract,
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
        (provider.transformResponse || '').trim() ||
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
      const transformResponse =
        config.transformResponse != null && String(config.transformResponse).trim()
          ? String(config.transformResponse)
          : DEFAULT_SSE_TRANSFORM_RESPONSE
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
        transformResponse,
        responseExtract: parseResponseExtractFromTransform(transformResponse),
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

function matchGraderId(raw: unknown, graders: GraderMeta[]): string | null {
  if (raw == null || !graders.length) return null
  let id = ''
  let apiHost = ''
  let label = ''
  if (typeof raw === 'string') {
    id = raw.trim()
  } else if (typeof raw === 'object') {
    const obj = raw as Record<string, unknown>
    id = String(obj.id || '').trim()
    label = String(obj.label || '').trim()
    const config =
      obj.config && typeof obj.config === 'object' && !Array.isArray(obj.config)
        ? (obj.config as Record<string, unknown>)
        : {}
    apiHost = String(config.apiBaseUrl || config.apiHost || config.baseUrl || '').trim()
  }
  if (!id && !label) return null

  for (const grader of graders) {
    const provider = graderMetaToVisualProvider(grader)
    if (!provider.id.trim()) continue
    if (label && grader.name.trim() === label) return grader.id
    if (provider.id === id) return grader.id
    const resolved = resolveProviderTarget(provider.id, provider.apiHost)
    if (resolved.id === id) {
      if (!apiHost || !resolved.apiHost || resolved.apiHost === apiHost) return grader.id
    }
  }
  return null
}

export function normalizeAssert(item: unknown, graders: GraderMeta[] = []): VisualAssert {
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
          graderId: null,
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
      graderId: assertNeedsGrader(type) ? matchGraderId(obj.provider, graders) : null,
      negated,
    }
  }
  return createVisualAssert('contains')
}

/** Parse assert YAML text (list or `{ assert: [...] }`). JSON-only payloads are rejected. */
export function parseAssertYaml(text: string, graders: GraderMeta[] = []): VisualAssert[] {
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
  return asList(data).map((item) => normalizeAssert(item, graders))
}

function normalizeTest(item: unknown, graders: GraderMeta[] = []): VisualTest {
  if (!item || typeof item !== 'object') {
    return { description: '', varsText: '{\n  \n}', asserts: [] }
  }
  const obj = item as Record<string, unknown>
  return {
    description: String(obj.description || ''),
    varsText: stringifyVars((obj.vars as Record<string, unknown>) || {}),
    asserts: asList(obj.assert).map((assertItem) => normalizeAssert(assertItem, graders)),
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

export function yamlToVisual(
  yamlContent: string,
  fallbackDescription = '',
  graders: GraderMeta[] = [],
): VisualConfig {
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
    defaultAsserts: asList(defaultTest.assert).map((item) => normalizeAssert(item, graders)),
    tests: asList(parsed.tests).map((item) => normalizeTest(item, graders)),
  }
}

export function visualToYaml(
  visual: VisualConfig,
  existingYaml = '',
  graders: GraderMeta[] = [],
): string {
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
    .map((a) => serializeOneAssert(a, graders))
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
      .map((a) => serializeOneAssert(a, graders))
      .filter((a): a is Record<string, unknown> => a != null)
    if (asserts.length) test.assert = asserts
    return test
  })

  return dump(base, {
    lineWidth: 120,
    noRefs: true,
  })
}
