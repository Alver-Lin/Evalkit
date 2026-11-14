import { dump, load } from 'js-yaml'

export interface VisualAssert {
  type: string
  value: string
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

function normalizeAssert(item: unknown): VisualAssert {
  if (item && typeof item === 'object') {
    const obj = item as Record<string, unknown>
    const value = obj.value
    return {
      type: String(obj.type || 'contains'),
      value: typeof value === 'string' ? value : JSON.stringify(value ?? ''),
    }
  }
  return { type: 'contains', value: '' }
}

function normalizeTest(item: unknown): VisualTest {
  if (!item || typeof item !== 'object') {
    return { description: '', varsText: '{\n  \n}', asserts: [] }
  }
  const obj = item as Record<string, unknown>
  return {
    description: String(obj.description || ''),
    varsText: stringifyVars((obj.vars as Record<string, unknown>) || {}),
    asserts: asList(obj.assert).map(normalizeAssert),
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

  return {
    description: String(parsed.description || fallbackDescription || ''),
    prompts: prompts.length ? prompts : [''],
    providers: asList(parsed.providers || parsed.targets).map(normalizeProvider),
    defaultAsserts: asList(defaultTest.assert).map(normalizeAssert),
    tests: asList(parsed.tests).map(normalizeTest),
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
    .filter((p) => p.id.trim())
    .map((p) => {
      const resolved = resolveProviderTarget(p.id, p.apiHost)
      const config: Record<string, string> = {}
      if (p.apiKey.trim()) config.apiKey = p.apiKey.trim()
      if (resolved.apiHost) config.apiBaseUrl = resolved.apiHost
      if (p.organization.trim()) config.organization = p.organization.trim()

      const provider: Record<string, unknown> = { id: resolved.id }
      if (p.label.trim()) provider.label = p.label.trim()
      else if (/^deepseek/i.test(p.id.trim())) provider.label = p.id.trim()
      if (Object.keys(config).length) provider.config = config
      return provider
    })

  const defaultAsserts = visual.defaultAsserts
    .filter((a) => a.type.trim() && String(a.value ?? '').trim() !== '')
    .map((a) => ({
      type: a.type.trim(),
      value: a.value,
    }))

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
      .filter((a) => a.type.trim())
      .map((a) => ({
        type: a.type.trim(),
        value: a.value,
      }))
    if (asserts.length) test.assert = asserts
    return test
  })

  return dump(base, {
    lineWidth: 120,
    noRefs: true,
  })
}
