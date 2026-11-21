import { dump, load } from 'js-yaml'
import type { GraderMeta } from '@/types'
import {
  normalizeAssert,
  parseAssertYaml,
  serializeOneAssert,
  type VisualAssert,
  type VisualTest,
} from '@/utils/promptfooConfig'

const DESCRIPTION_KEYS = new Set([
  'description',
  'desc',
  'name',
  'title',
  '测试项',
  '用例',
  '名称',
])

const ASSERT_KEYS = new Set(['assert', 'asserts', '断言'])

export type ImportedTestDraft = {
  description: string
  vars: Record<string, string>
  asserts: VisualAssert[]
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asList(value: unknown): unknown[] {
  if (value == null) return []
  return Array.isArray(value) ? value : [value]
}

function stringifyVar(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function isDescriptionKey(key: string) {
  const trimmed = key.trim()
  return DESCRIPTION_KEYS.has(trimmed) || DESCRIPTION_KEYS.has(trimmed.toLowerCase())
}

function isAssertKey(key: string) {
  const trimmed = key.trim()
  return ASSERT_KEYS.has(trimmed) || ASSERT_KEYS.has(trimmed.toLowerCase())
}

function pickDescription(row: Record<string, unknown>): string {
  for (const key of Object.keys(row)) {
    if (!isDescriptionKey(key)) continue
    const value = row[key]
    if (value != null && String(value).trim()) return String(value).trim()
  }
  return ''
}

function pickVars(row: Record<string, unknown>): Record<string, string> {
  if (row.vars && typeof row.vars === 'object' && !Array.isArray(row.vars)) {
    const out: Record<string, string> = {}
    for (const [key, value] of Object.entries(row.vars as Record<string, unknown>)) {
      out[key] = stringifyVar(value)
    }
    return out
  }

  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(row)) {
    const trimmed = key.trim()
    if (!trimmed) continue
    if (isDescriptionKey(trimmed) || isAssertKey(trimmed)) continue
    if (trimmed === 'vars') continue
    out[trimmed] = stringifyVar(value)
  }
  return out
}

/**
 * Assertions must be YAML.
 * - string → parse as YAML
 * - structured value → only allowed when source is YAML file (not JSON)
 */
function pickAsserts(
  row: Record<string, unknown>,
  graders: GraderMeta[],
  source: 'csv' | 'yaml' | 'json',
  rowIndex: number,
): VisualAssert[] {
  for (const key of Object.keys(row)) {
    if (!isAssertKey(key)) continue
    const value = row[key]
    if (value == null || value === '') return []

    if (typeof value === 'string') {
      try {
        return parseAssertYaml(value, graders)
      } catch (error) {
        const reason = error instanceof Error ? error.message : '断言解析失败'
        throw new Error(`第 ${rowIndex} 条用例断言无效：${reason}`)
      }
    }

    if (source === 'json') {
      throw new Error(
        `第 ${rowIndex} 条用例断言无效：断言只能使用 YAML 格式（CSV 的 assert 列，或 .yaml 文件）`,
      )
    }

    // Native YAML structured assert / assert list
    return asList(value).map((item) => normalizeAssert(item, graders))
  }
  return []
}

function normalizeDraft(
  row: unknown,
  graders: GraderMeta[],
  source: 'csv' | 'yaml' | 'json',
  rowIndex: number,
): ImportedTestDraft | null {
  if (typeof row === 'string') {
    const text = row.trim()
    if (!text) return null
    return { description: '', vars: { input: text }, asserts: [] }
  }
  const record = asRecord(row)
  if (!record) return null
  const description = pickDescription(record)
  const vars = pickVars(record)
  const asserts = pickAsserts(record, graders, source, rowIndex)
  if (!description && !Object.values(vars).some((v) => v.trim()) && !asserts.length) return null
  return { description, vars, asserts }
}

/** Full-file CSV parser that preserves quoted multiline cells (for assert YAML). */
function parseCsvRows(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let current = ''
  let inQuotes = false
  const input = text.replace(/^\uFEFF/, '')

  const pushRow = () => {
    row.push(current)
    current = ''
    if (row.some((cell) => cell.trim().length > 0)) {
      rows.push(row.map((cell) => cell.trim()))
    }
    row = []
  }

  for (let i = 0; i < input.length; i += 1) {
    const ch = input[i]
    if (inQuotes) {
      if (ch === '"') {
        if (input[i + 1] === '"') {
          current += '"'
          i += 1
        } else {
          inQuotes = false
        }
      } else {
        current += ch
      }
      continue
    }
    if (ch === '"') {
      inQuotes = true
      continue
    }
    if (ch === ',') {
      row.push(current)
      current = ''
      continue
    }
    if (ch === '\n') {
      pushRow()
      continue
    }
    if (ch === '\r') {
      if (input[i + 1] === '\n') i += 1
      pushRow()
      continue
    }
    current += ch
  }
  if (current.length || row.length) pushRow()
  return rows
}

function parseCsv(text: string, graders: GraderMeta[]): ImportedTestDraft[] {
  const rows = parseCsvRows(text)
  if (rows.length < 2) return []

  const headers = rows[0].map((h) => h.trim())
  if (!headers.length || headers.every((h) => !h)) {
    throw new Error('CSV 缺少表头')
  }

  const drafts: ImportedTestDraft[] = []
  for (let i = 1; i < rows.length; i += 1) {
    const cells = rows[i]
    if (cells.every((cell) => !cell.trim())) continue
    const row: Record<string, unknown> = {}
    headers.forEach((header, index) => {
      if (!header) return
      row[header] = cells[index] ?? ''
    })
    const draft = normalizeDraft(row, graders, 'csv', drafts.length + 1)
    if (draft) drafts.push(draft)
  }
  return drafts
}

function parseJsonOrYaml(
  text: string,
  graders: GraderMeta[],
  source: 'yaml' | 'json',
): ImportedTestDraft[] {
  let data: unknown
  if (source === 'json') {
    data = JSON.parse(text)
  } else {
    data = load(text)
  }

  let rows: unknown[] = []
  if (Array.isArray(data)) {
    rows = data
  } else {
    const record = asRecord(data)
    if (!record) throw new Error('无法解析为用例列表')
    if (Array.isArray(record.tests)) rows = record.tests
    else if (Array.isArray(record.cases)) rows = record.cases
    else if (Array.isArray(record.data)) rows = record.data
    else throw new Error('JSON/YAML 需为数组，或包含 tests 字段')
  }

  const drafts: ImportedTestDraft[] = []
  rows.forEach((row, index) => {
    const draft = normalizeDraft(row, graders, source, index + 1)
    if (draft) drafts.push(draft)
  })
  return drafts
}

export function parseImportedTests(
  text: string,
  filename = '',
  graders: GraderMeta[] = [],
): ImportedTestDraft[] {
  const trimmed = text.trim()
  if (!trimmed) throw new Error('文件为空')

  const lower = filename.toLowerCase()
  let drafts: ImportedTestDraft[]

  if (lower.endsWith('.csv')) {
    drafts = parseCsv(trimmed, graders)
  } else if (lower.endsWith('.yaml') || lower.endsWith('.yml')) {
    drafts = parseJsonOrYaml(trimmed, graders, 'yaml')
  } else if (lower.endsWith('.json')) {
    drafts = parseJsonOrYaml(trimmed, graders, 'json')
  } else if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    drafts = parseJsonOrYaml(trimmed, graders, 'json')
  } else if (trimmed.startsWith('tests:') || trimmed.includes('\nassert:')) {
    drafts = parseJsonOrYaml(trimmed, graders, 'yaml')
  } else {
    drafts = parseCsv(trimmed, graders)
  }

  if (!drafts.length) throw new Error('未解析到有效用例')
  return drafts
}

export function draftsToVisualTests(
  drafts: ImportedTestDraft[],
  preferredVarNames: string[] = [],
): VisualTest[] {
  return drafts.map((draft) => {
    const vars: Record<string, string> = {}
    const names = preferredVarNames.length ? preferredVarNames : Object.keys(draft.vars)
    if (names.length) {
      for (const name of names) vars[name] = draft.vars[name] ?? ''
      for (const [key, value] of Object.entries(draft.vars)) {
        if (!(key in vars)) vars[key] = value
      }
    } else {
      Object.assign(vars, draft.vars)
    }

    return {
      description: draft.description,
      varsText: JSON.stringify(vars, null, 2),
      asserts: draft.asserts,
    }
  })
}

/** Sample assert YAML for the downloadable CSV template. */
export function sampleAssertYaml(): string {
  return dump(
    [
      {
        type: 'llm-rubric',
        value: '言之有理即可',
        threshold: 0.7,
      },
    ],
    { lineWidth: 120, noRefs: true },
  ).trim()
}

/** Serialize visual asserts to YAML text for CSV `assert` column. */
export function assertsToYaml(asserts: VisualAssert[], graders: GraderMeta[] = []): string {
  const list = (asserts || [])
    .map((item) => serializeOneAssert(item, graders))
    .filter((item): item is Record<string, unknown> => Boolean(item))
  if (!list.length) return ''
  return dump(list, { lineWidth: 120, noRefs: true }).trim()
}

function parseVarsText(varsText: string): Record<string, string> {
  try {
    const parsed = JSON.parse(varsText || '{}')
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

function csvEscapeCell(value: string) {
  if (/[",\n\r]/.test(value)) return `"${value.replace(/"/g, '""')}"`
  return value
}

/**
 * Build import-compatible CSV for current visual tests.
 * Columns: description + var names + assert (YAML).
 */
export function buildExportedTestsCsv(
  tests: VisualTest[],
  preferredVarNames: string[] = [],
  graders: GraderMeta[] = [],
): string {
  const varNames = new Set<string>(preferredVarNames)
  for (const test of tests) {
    for (const key of Object.keys(parseVarsText(test.varsText))) {
      if (key) varNames.add(key)
    }
  }
  const vars = preferredVarNames.length
    ? [
        ...preferredVarNames,
        ...Array.from(varNames).filter((name) => !preferredVarNames.includes(name)),
      ]
    : Array.from(varNames)

  const headers = ['description', ...vars, 'assert']
  const lines = [headers.map(csvEscapeCell).join(',')]
  for (const test of tests) {
    const rowVars = parseVarsText(test.varsText)
    const cells = [
      csvEscapeCell(test.description || ''),
      ...vars.map((name) => csvEscapeCell(rowVars[name] ?? '')),
      csvEscapeCell(assertsToYaml(test.asserts || [], graders)),
    ]
    lines.push(cells.join(','))
  }
  return `\uFEFF${lines.join('\n')}\n`
}
