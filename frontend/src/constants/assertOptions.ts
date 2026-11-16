/** Assertion option used by flat selects / lookups. */
export type AssertOption = {
  value: string
  label: string
  /** Show value input. Default true. */
  hasValue?: boolean
  /** Value may be empty (e.g. is-json without schema). */
  valueOptional?: boolean
  /** Show threshold input. Default false. */
  hasThreshold?: boolean
  /** Prefill when switching to this type (and threshold empty). */
  defaultThreshold?: number
  /** Allow picking a configured provider as LLM/embedding grader. */
  needsGrader?: boolean
  /** Value placeholder. */
  valuePlaceholder?: string
  /** Threshold placeholder. */
  thresholdPlaceholder?: string
}

/** Grouped assertion catalog (matches README §6.3 categories). */
export const assertCategories: Array<{
  key: string
  label: string
  options: AssertOption[]
}> = [
  {
    key: 'model',
    label: '模型评分',
    options: [
      {
        value: 'similar',
        label: '语义相似',
        hasValue: true,
        hasThreshold: true,
        defaultThreshold: 0.8,
        needsGrader: true,
        valuePlaceholder: '期望语义文本',
        thresholdPlaceholder: '相似度阈值',
      },
      {
        value: 'llm-rubric',
        label: '模型评分标准',
        hasValue: true,
        hasThreshold: true,
        defaultThreshold: 0.7,
        needsGrader: true,
        valuePlaceholder: '评分标准',
        thresholdPlaceholder: '最低分数',
      },
    ],
  },
  {
    key: 'text',
    label: '文本匹配',
    options: [
      { value: 'contains', label: '包含', hasValue: true, valuePlaceholder: '期望子串' },
      { value: 'icontains', label: '包含忽略大小写', hasValue: true, valuePlaceholder: '期望子串' },
      { value: 'equals', label: '完全相等', hasValue: true, valuePlaceholder: '期望全文' },
      { value: 'starts-with', label: '以…开头', hasValue: true, valuePlaceholder: '期望前缀' },
      {
        value: 'contains-all',
        label: '包含全部',
        hasValue: true,
        valuePlaceholder: '多项用逗号分隔，或 JSON 数组',
      },
      {
        value: 'contains-any',
        label: '包含任一项',
        hasValue: true,
        valuePlaceholder: '多项用逗号分隔，或 JSON 数组',
      },
      {
        value: 'icontains-all',
        label: '包含全部忽略大小写',
        hasValue: true,
        valuePlaceholder: '多项用逗号分隔，或 JSON 数组',
      },
      {
        value: 'icontains-any',
        label: '包含任一项忽略大小写',
        hasValue: true,
        valuePlaceholder: '多项用逗号分隔，或 JSON 数组',
      },
      {
        value: 'word-count',
        label: '词数',
        hasValue: false,
        hasThreshold: true,
        defaultThreshold: 50,
        thresholdPlaceholder: '最大词数',
      },
    ],
  },
  {
    key: 'structure',
    label: '结构 / 格式',
    options: [
      {
        value: 'is-json',
        label: '是否为 JSON',
        hasValue: true,
        valueOptional: true,
        valuePlaceholder: '可选 Schema（JSON）',
      },
      {
        value: 'contains-json',
        label: '包含 JSON',
        hasValue: true,
        valueOptional: true,
        valuePlaceholder: '可选 Schema（JSON）',
      },
      {
        value: 'is-xml',
        label: '是否为 XML',
        hasValue: true,
        valueOptional: true,
        valuePlaceholder: '可选约束（JSON）',
      },
      {
        value: 'contains-xml',
        label: '包含 XML',
        hasValue: true,
        valueOptional: true,
        valuePlaceholder: '可选约束（JSON）',
      },
      { value: 'is-html', label: '是否为 HTML', hasValue: false },
      { value: 'contains-html', label: '包含 HTML', hasValue: false },
      {
        value: 'is-sql',
        label: '是否为 SQL',
        hasValue: true,
        valueOptional: true,
        valuePlaceholder: '可选约束（JSON）',
      },
      {
        value: 'contains-sql',
        label: '包含 SQL',
        hasValue: true,
        valueOptional: true,
        valuePlaceholder: '可选约束（JSON）',
      },
      { value: 'is-refusal', label: '是否拒答', hasValue: false },
      {
        value: 'finish-reason',
        label: '结束原因',
        hasValue: true,
        valuePlaceholder: '如 stop / length / tool_calls',
      },
    ],
  },
  {
    key: 'metric',
    label: '指标 / 成本',
    options: [
      {
        value: 'cost',
        label: '单次成本阈值',
        hasValue: false,
        hasThreshold: true,
        defaultThreshold: 0.001,
        thresholdPlaceholder: '最大费用（USD）',
      },
      {
        value: 'latency',
        label: '耗时阈值',
        hasValue: false,
        hasThreshold: true,
        defaultThreshold: 2000,
        thresholdPlaceholder: '最大耗时（ms）',
      },
    ],
  },
]

/** Flat list for lookups / legacy consumers. Negation uses 是/非, so `not-*` is omitted. */
export const assertOptions: AssertOption[] = assertCategories.flatMap((cat) => cat.options)

const assertMetaByType = Object.fromEntries(assertOptions.map((opt) => [opt.value, opt]))

export function getAssertMeta(type: string | undefined | null): AssertOption {
  const key = (type || '').trim() || 'contains'
  return (
    assertMetaByType[key] || {
      value: key,
      label: key,
      hasValue: true,
      hasThreshold: false,
      valuePlaceholder: '期望值',
    }
  )
}

export function assertShowsValue(type: string | undefined | null): boolean {
  return getAssertMeta(type).hasValue !== false
}

export function assertShowsThreshold(type: string | undefined | null): boolean {
  return Boolean(getAssertMeta(type).hasThreshold)
}

export function assertDefaultThreshold(type: string | undefined | null): number | undefined {
  return getAssertMeta(type).defaultThreshold
}

export function assertNeedsGrader(type: string | undefined | null): boolean {
  return Boolean(getAssertMeta(type).needsGrader)
}

/** TreeSelect data: category nodes are not selectable. */
export const assertTreeData = assertCategories.map((cat) => ({
  title: cat.label,
  value: `__cat_${cat.key}`,
  key: `__cat_${cat.key}`,
  selectable: false,
  children: cat.options.map((opt) => ({
    title: opt.label,
    value: opt.value,
    key: opt.value,
  })),
}))
