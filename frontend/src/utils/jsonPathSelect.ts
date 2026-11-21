/** JSON path helpers for AI extract: select leaf values from probe samples. */

export type JsonPathNodeKind = 'object' | 'array' | 'value'

export interface JsonPathNode {
  path: string
  key: string
  kind: JsonPathNodeKind
  preview: string
  selectable: boolean
  children: JsonPathNode[]
}

const MAX_TREE_NODES = 400

function previewValue(value: unknown): string {
  if (value == null) return String(value)
  if (typeof value === 'string') {
    // Show full string (including nested JSON text); tree panel scrolls if long.
    return JSON.stringify(value)
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return `Array(${value.length})`
  if (typeof value === 'object') return '{…}'
  return String(value)
}

function joinPath(parent: string, key: string | number): string {
  if (typeof key === 'number') {
    return parent ? `${parent}[${key}]` : `[${key}]`
  }
  if (!parent) return key
  if (/^[A-Za-z_][\w]*$/.test(key)) return `${parent}.${key}`
  return `${parent}[${JSON.stringify(key)}]`
}

/** Build a shallow-friendly checkable tree from JSON. */
export function buildJsonPathTree(root: unknown, limit = MAX_TREE_NODES): JsonPathNode[] {
  let remaining = limit

  function walk(value: unknown, path: string, key: string): JsonPathNode | null {
    if (remaining <= 0) return null
    remaining -= 1

    if (value != null && typeof value === 'object') {
      if (Array.isArray(value)) {
        const children: JsonPathNode[] = []
        for (let i = 0; i < value.length; i += 1) {
          const child = walk(value[i], joinPath(path, i), String(i))
          if (child) children.push(child)
          if (remaining <= 0) break
        }
        return {
          path,
          key,
          kind: 'array',
          preview: `Array(${value.length})`,
          // Allow selecting whole arrays/objects for「选择字段拼接」.
          selectable: Boolean(path),
          children,
        }
      }
      const obj = value as Record<string, unknown>
      const children: JsonPathNode[] = []
      for (const childKey of Object.keys(obj)) {
        const child = walk(obj[childKey], joinPath(path, childKey), childKey)
        if (child) children.push(child)
        if (remaining <= 0) break
      }
      return {
        path,
        key,
        kind: 'object',
        preview: '{…}',
        selectable: Boolean(path),
        children,
      }
    }

    return {
      path,
      key,
      kind: 'value',
      preview: previewValue(value),
      selectable: typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean',
      children: [],
    }
  }

  if (root != null && typeof root === 'object' && !Array.isArray(root)) {
    const nodes: JsonPathNode[] = []
    for (const key of Object.keys(root as Record<string, unknown>)) {
      const child = walk((root as Record<string, unknown>)[key], key, key)
      if (child) nodes.push(child)
      if (remaining <= 0) break
    }
    return nodes
  }

  const single = walk(root, '$', '$')
  return single ? [single] : []
}

/** Parse path like `data.content[0].text` into segments. */
export function parseJsonPath(path: string): Array<string | number> {
  const text = String(path || '').trim()
  if (!text || text === '$') return []
  const segments: Array<string | number> = []
  const re = /([A-Za-z_][\w]*)|\[(\d+)\]|\["((?:\\.|[^"\\])*)"\]|\['((?:\\.|[^'\\])*)'\]/g
  let match: RegExpExecArray | null
  let cursor = 0
  if (text.startsWith('$.')) cursor = 2
  else if (text.startsWith('$')) cursor = 1
  while (cursor < text.length) {
    if (text[cursor] === '.') {
      cursor += 1
      continue
    }
    re.lastIndex = cursor
    match = re.exec(text)
    if (!match || match.index !== cursor) {
      // fallback: treat remainder as a single key
      const rest = text.slice(cursor)
      if (rest) segments.push(rest)
      break
    }
    if (match[1] != null) segments.push(match[1])
    else if (match[2] != null) segments.push(Number(match[2]))
    else if (match[3] != null) segments.push(JSON.parse(`"${match[3]}"`))
    else if (match[4] != null) segments.push(JSON.parse(`"${match[4]}"`))
    cursor = re.lastIndex
  }
  return segments
}

export function getValueByJsonPath(root: unknown, path: string): unknown {
  const segments = parseJsonPath(path)
  let cur: unknown = root
  for (const seg of segments) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string | number, unknown>)[seg as never]
  }
  return cur
}

/** True if `parent` is a JSON-path prefix of `child` (e.g. data ⊃ data.document). */
export function isJsonPathPrefix(parent: string, child: string): boolean {
  if (!parent || parent === child) return false
  if (child.startsWith(parent + '.')) return true
  if (child.startsWith(parent + '[')) return true
  return false
}

/**
 * When both a parent path and its descendants are selected, keep the more specific
 * descendants so output is not duplicated (whole object + each field).
 */
export function pruneAncestorJsonPaths(paths: string[]): string[] {
  const list = paths.map((p) => String(p || '').trim()).filter(Boolean)
  return list.filter(
    (path) => !list.some((other) => other !== path && isJsonPathPrefix(path, other)),
  )
}

export function valuesByJsonPaths(root: unknown, paths: string[]): string[] {
  const out: string[] = []
  for (const path of pruneAncestorJsonPaths(paths)) {
    const value = getValueByJsonPath(root, path)
    if (value == null || value === '') continue
    out.push(typeof value === 'string' ? value : JSON.stringify(value))
  }
  return out
}

/** Parse probe sample into a JSON root for tree selection. */
export function parseSampleJsonRoot(sampleText: string, source: 'sse' | 'json'): unknown | null {
  const text = String(sampleText || '')
  if (!text.trim()) return null

  if (source === 'json') {
    try {
      return JSON.parse(text)
    } catch {
      return null
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
      // skip non-json chunks
    }
  }
  if (events.length === 1) return events[0]
  if (events.length > 1) return events
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

/** Collect selectable string leaf paths (prefer `text` / `content` / `answer`). */
export function suggestAiPaths(root: unknown, limit = 40): string[] {
  const preferredKeys = new Set(['text', 'content', 'answer', 'message', 'output', 'sql'])
  const skipKeys = new Set([
    'type',
    'status',
    'id',
    'uuid',
    'requestId',
    'request_id',
    'traceId',
    'trace_id',
    'code',
    'role',
  ])
  const preferred: string[] = []
  const rest: string[] = []

  function walk(value: unknown, path: string) {
    if (preferred.length + rest.length >= limit) return
    if (value == null || typeof value !== 'object') {
      if (typeof value === 'string' && value.trim() && path) {
        const key = path.split('.').pop()?.replace(/\[\d+\]/g, '') || ''
        if (skipKeys.has(key)) return
        // Skip tiny structural tokens like "text" / "paragraph" stored under non-preferred keys.
        if (!preferredKeys.has(key) && value.trim().length <= 24 && !/\s/.test(value)) return
        if (preferredKeys.has(key)) preferred.push(path)
        else rest.push(path)
      }
      return
    }
    if (Array.isArray(value)) {
      value.forEach((item, i) => walk(item, joinPath(path, i)))
      return
    }
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      walk(child, joinPath(path, key))
    }
  }

  walk(root, '')
  return [...preferred, ...rest].slice(0, limit)
}
