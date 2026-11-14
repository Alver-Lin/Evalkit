<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { assertOptions } from '@/constants/assertOptions'
import type { VisualConfig } from '@/utils/promptfooConfig'

const model = defineModel<VisualConfig>({ required: true })

defineProps<{
  section: 'prompts' | 'providers' | 'tests'
}>()

const varSyntax = '{{variable}}'
const pageSize = 10
const promptPage = ref(1)
const providerPage = ref(1)
const testPage = ref(1)
const detailOpen = ref(false)
const detailIndex = ref(0)

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

function addProvider() {
  model.value.providers.push({
    id: '',
    label: '',
    apiKey: '',
    apiHost: '',
    organization: '',
  })
  providerPage.value = Math.ceil(model.value.providers.length / pageSize) || 1
}

function removeProvider(index: number) {
  if (model.value.providers.length <= 1) return
  model.value.providers.splice(index, 1)
  clampPage(providerPage, model.value.providers.length)
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

function testAssertPreview(asserts: { type: string; value: string }[]) {
  if (!asserts?.length) return '—'
  return asserts.map((a) => a.type || 'assert').join(', ')
}

function addAssert(testIndex: number) {
  model.value.tests[testIndex].asserts.push({ type: 'contains', value: '' })
}

function removeAssert(testIndex: number, assertIndex: number) {
  model.value.tests[testIndex].asserts.splice(assertIndex, 1)
}

function addDefaultAssert() {
  if (!model.value.defaultAsserts) model.value.defaultAsserts = []
  model.value.defaultAsserts.push({ type: 'not-contains', value: '' })
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
          <p>模板支持 <code>{{ varSyntax }}</code> 格式可作为变量补充</p>
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
              :rows="5"
              class="prompt-editor mono"
              :placeholder="'例如：Answer: ' + varSyntax"
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
          <p>模型 ID、密钥与 Host</p>
        </div>
        <div class="head-meta">
          <a-button type="dashed" class="add-btn" @click="addProvider">
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
          >
            <div class="item-head">
              <span class="badge mono">provider{{ index + 1 }}</span>
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
            <div class="provider-grid">
              <div class="field span-main">
                <label>Provider ID</label>
                <a-input
                  v-model:value="model.providers[index].id"
                  class="mono"
                  placeholder="openai:gpt-4o-mini / deepseek / python:mock_provider.py"
                />
              </div>
              <div class="field span-side">
                <label>Label</label>
                <a-input v-model:value="model.providers[index].label" placeholder="可选" />
              </div>
              <div class="field span-full">
                <label>API Key</label>
                <a-input-password
                  v-model:value="model.providers[index].apiKey"
                  placeholder="或用环境变量"
                />
              </div>
              <div class="field span-full">
                <label>API Host</label>
                <a-input
                  v-model:value="model.providers[index].apiHost"
                  class="mono"
                  placeholder="DeepSeek 可留空，默认 https://api.deepseek.com/v1"
                />
              </div>
              <div class="field span-full">
                <label>Organization</label>
                <a-input v-model:value="model.providers[index].organization" placeholder="可选" />
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
              class="assert-row"
            >
              <a-select
                v-model:value="assertItem.type"
                class="assert-type"
                :options="assertOptions"
                show-search
                option-filter-prop="label"
                placeholder="类型"
              />
              <a-input
                v-model:value="assertItem.value"
                class="assert-value"
                placeholder="期望值"
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
                  <a-space :size="8">
                    <a @click="openTestDetail(record.index)">详情</a>
                    <a
                      class="danger-link"
                      :class="{ disabled: model.tests.length <= 1 }"
                      @click.prevent="model.tests.length > 1 && removeTest(record.index)"
                    >删除</a>
                  </a-space>
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
        :title="detailTest ? `test${detailIndex + 1} 详情` : '测试用例详情'"
        placement="right"
        :width="520"
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
                class="assert-row"
              >
                <a-select
                  v-model:value="assertItem.type"
                  class="assert-type"
                  :options="assertOptions"
                  show-search
                  option-filter-prop="label"
                  placeholder="类型"
                />
                <a-input
                  v-model:value="assertItem.value"
                  class="assert-value"
                  placeholder="期望值"
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
  gap: 4px;
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

.danger-link {
  color: var(--ek-danger);
}

.danger-link.disabled {
  color: var(--ek-muted);
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

.row-actions {
  display: flex;
  align-items: center;
}

.provider-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 148px;
  gap: 10px 12px;
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
  display: grid;
  grid-template-columns: minmax(160px, 240px) minmax(0, 1fr) 28px;
  gap: 8px;
  align-items: center;
}

.assert-type {
  width: 100%;
}

.assert-value {
  min-width: 0;
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

  .assert-row {
    grid-template-columns: 1fr 28px;
  }

  .assert-row .assert-type,
  .assert-row .assert-value {
    grid-column: 1;
  }

  .assert-row .icon-btn {
    grid-column: 2;
    grid-row: 1;
  }
}
</style>
