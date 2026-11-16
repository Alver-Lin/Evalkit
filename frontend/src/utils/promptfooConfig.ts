import { dump, load } from 'js-yaml'
import {
  assertDefaultThreshold,
  assertNeedsGrader,
  assertShowsThreshold,
  getAssertMeta,
} from '@/constants/assertOptions'

export interface VisualAssert {
  /** Base assertion type without `not-` prefix. */
  type: string
  value: string
  /** Optional numeric threshold for similarity / cost / latency etc. */
  threshold?: number | null
  /** Index into VisualConfig.providers used as grader (llm-rubric / similar). */
  graderProviderIndex?: number | null
  /** When true, serialize as `not-<type>` in YAML. */
  negated?: boolean
}

export function createVisualAssert(type = 'contains', graderProviderIndex: number | null = null): VisualAssert {
  const meta = getAssertMeta(type)
  return {
    type: meta.value || type,
    value: '',
    threshold: meta.hasThreshold ? (meta.defaultThreshold ?? null) : null,
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

function toProviderYaml(provider: VisualProvider): Record<string, unknown> | null {
  if (!provider.id.trim()) return null
  const resolved = resolveProviderTarget(provider.id, provider.apiHost)
  const config: Record<string, string> = {}
  if (provider.apiKey.trim()) config.apiKey = provider.apiKey.trim()
  if (resolved.apiHost) config.apiBaseUrl = resolved.apiHost
  if (provider.organization.trim()) config.organization = provider.organization.trim()

  const out: Record<string, unknown> = { id: resolved.id }
  if (provider.label.trim()) out.label = provider.label.trim()
  else if (/^deepseek/i.test(provider.id.trim())) out.label = provider.id.trim()
  if (Object.keys(config).length) out.config = config
  return out
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
  const value = showsValue ? serializeAssertValue(String(assert.value ?? ''), type) : undefined
  const threshold =
    showsThreshold && assert.threshold != null && Number.isFinite(Number(assert.threshold))
      ? Number(assert.threshold)
      : undefined

  // Threshold-only: require threshold
  if (showsThreshold && !showsValue && threshold == null) return null
  // Value required (with or without threshold)
  if (showsValue && !meta.valueOptional && value === undefined) return null

  const out: Record<string, unknown> = {
    type: (() => {
      const base = type
      const stripped = base.toLowerCase().startsWith('not-') ? base.slice(4) || 'contains' : base
      return assert.negated ? `not-${stripped}` : stripped
    })(),
  }
  if (value !== undefined) out.value = value
  if (threshold !== undefined) out.threshold = threshold

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

export interface VisualProvider {
  id: string
  label: string
  apiKey: string
  apiHost: string
  organization: string
}

function emptyProvider(): VisualProvider {
  return { id: '', label: '', apiKey: '', apiHost: '', organization: '' }
}

/** Map common aliases to IDs that promptfoo 0.125.x can resolve. */
export function resolveProviderTarget(id: string, apiHost = ''): { id: string; apiHost: string } {
  const raw = id.trim()
  const host = apiHost.trim()
  if (!raw) return { id: '', apiHost: host }

  const lower = raw.toLowerCase()
  // Bare "deepseek" or "deepseek:<model>" — use OpenAI-compatible endpoint.
  if (lower === 'deepseek' || lower.startsWith('deepseek:')) {
    const model =
      lower === 'deepseek' ? 'deepseek-chat' : raw.slice(raw.indexOf(':') + 1).trim() || 'deepseek-chat'
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

function normalizeProvider(item: unknown): VisualProvider {
  if (typeof item === 'string') {
    return { ...emptyProvider(), id: item }
  }
  if (item && typeof item === 'object') {
    const obj = item as Record<string, unknown>
    const config =
      obj.config && typeof obj.config === 'object' && !Array.isArray(obj.config)
        ? (obj.config as Record<string, unknown>)
        : {}
    return {
      id: String(obj.id || obj.provider || ''),
      label: String(obj.label || ''),
      apiKey: String(config.apiKey || config.api_key || ''),
      apiHost: String(config.apiBaseUrl || config.apiHost || config.baseUrl || ''),
      organization: String(config.organization || config.organizationId || ''),
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
    const { type, negated } = splitAssertType(String(obj.type || 'contains'))
    let threshold: number | null = null
    if (obj.threshold != null && obj.threshold !== '') {
      const n = Number(obj.threshold)
      if (Number.isFinite(n)) threshold = n
    } else if (assertShowsThreshold(type)) {
      threshold = assertDefaultThreshold(type) ?? null
    }
    return {
      type,
      value:
        value == null || value === ''
          ? ''
          : typeof value === 'string'
            ? value
            : JSON.stringify(value),
      threshold: assertShowsThreshold(type) ? threshold : null,
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

  return {
    description: String(parsed.description || fallbackDescription || ''),
    prompts: prompts.length ? prompts : [''],
    providers,
    defaultAsserts: asList(defaultTest.assert).map((item) => normalizeAssert(item, providers)),
    tests: asList(parsed.tests).map((item) => normalizeTest(item, providers)),
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

  if (defaultAsserts.length) {
    const existingDefault =
      base.defaultTest && typeof base.defaultTest === 'object' && !Array.isArray(base.defaultTest)
        ? { ...(base.defaultTest as Record<string, unknown>) }
        : {}
    base.defaultTest = {
      ...existingDefault,
      assert: defaultAsserts,
    }
  } else if (base.defaultTest && typeof base.defaultTest === 'object' && !Array.isArray(base.defaultTest)) {
    const existingDefault = { ...(base.defaultTest as Record<string, unknown>) }
    delete existingDefault.assert
    if (Object.keys(existingDefault).length) {
      base.defaultTest = existingDefault
    } else {
      delete base.defaultTest
    }
  } else {
    delete base.defaultTest
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
