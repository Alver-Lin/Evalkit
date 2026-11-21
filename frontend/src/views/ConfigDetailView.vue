<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { ArrowLeftOutlined } from '@ant-design/icons-vue'
import { api } from '@/api/client'
import type { ConfigMeta, GraderMeta } from '@/types'
import VisualConfigForm from '@/components/VisualConfigForm.vue'
import {
  createEmptyVisualConfig,
  persistProviderProbes,
  providerHasId,
  restoreProviderProbes,
  validateVisualProviders,
  visualToYaml,
  yamlToVisual,
  type VisualConfig,
} from '@/utils/promptfooConfig'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const running = ref(false)
const config = ref<ConfigMeta | null>(null)
const graders = ref<GraderMeta[]>([])
const activeTab = ref('visual')
const visualStep = ref(1)
const visual = ref<VisualConfig>(createEmptyVisualConfig())
const form = reactive({
  name: '',
  description: '',
  yaml_content: '',
  max_concurrency: 2,
  cache: false,
})

const steps = [
  { step: 1, key: 'basic' as const, label: '基本信息' },
  { step: 2, key: 'prompts' as const, label: '提示词' },
  { step: 3, key: 'providers' as const, label: '供应商' },
  { step: 4, key: 'tests' as const, label: '测试用例' },
]

const matrixHint = computed(() => {
  const p = visual.value.prompts.filter((prompt) => prompt.trim()).length
  const r = visual.value.providers.filter(providerHasId).length
  const t = visual.value.tests.length || 0
  return `${p} × ${r} × ${t}`
})

function syncDescriptionToVisual() {
  visual.value.description = form.description
}

function syncVisualToYaml() {
  visual.value.description = form.description
  form.yaml_content = visualToYaml(visual.value, form.yaml_content, graders.value)
}

function syncYamlToVisual() {
  visual.value = yamlToVisual(form.yaml_content, form.description, graders.value)
  form.description = visual.value.description || form.description
  restoreProviderProbes(String(route.params.id), visual.value.providers)
}

function ensureProvidersValid(): boolean {
  if (activeTab.value === 'yaml') {
    syncYamlToVisual()
  }
  const result = validateVisualProviders(visual.value.providers)
  if (result.ok) return true
  activeTab.value = 'visual'
  visualStep.value = 3
  message.error(result.message || '供应商配置不完整')
  return false
}

function onDescriptionChange() {
  syncDescriptionToVisual()
  if (activeTab.value === 'yaml') {
    form.yaml_content = visualToYaml(
      {
        ...yamlToVisual(form.yaml_content, form.description, graders.value),
        description: form.description,
      },
      form.yaml_content,
      graders.value,
    )
  }
}

function onTabChange(key: string | number) {
  const next = String(key)
  if (next === activeTab.value) return
  if (activeTab.value === 'visual' && next === 'yaml') {
    syncVisualToYaml()
  } else if (activeTab.value === 'yaml' && next === 'visual') {
    syncYamlToVisual()
  }
  activeTab.value = next
}

async function loadGraders() {
  try {
    graders.value = await api.listGraders()
  } catch {
    graders.value = []
  }
}

async function load() {
  loading.value = true
  try {
    await loadGraders()
    config.value = await api.getConfig(String(route.params.id))
    form.name = config.value.name
    form.description = (config.value.description || '').trim()
    form.yaml_content = config.value.yaml_content
    form.max_concurrency = config.value.max_concurrency ?? 2
    form.cache = Boolean(config.value.cache)
    visual.value = yamlToVisual(form.yaml_content, form.description, graders.value)
    restoreProviderProbes(String(route.params.id), visual.value.providers)
    const resolvedDescription = form.description || visual.value.description || ''
    form.description = resolvedDescription === 'My eval' ? '' : resolvedDescription
    visual.value.description = form.description
    form.yaml_content = visualToYaml(visual.value, form.yaml_content, graders.value)
    activeTab.value = 'visual'
    visualStep.value = 1
  } catch {
    message.error('配置不存在')
    router.push('/configs')
  } finally {
    loading.value = false
  }
}

async function save(): Promise<boolean> {
  try {
    if (!ensureProvidersValid()) return false
    if (activeTab.value === 'visual') {
      syncVisualToYaml()
    } else {
      syncYamlToVisual()
      syncVisualToYaml()
    }
    config.value = await api.updateConfig(String(route.params.id), {
      name: form.name,
      description: form.description,
      yaml_content: form.yaml_content,
      max_concurrency: form.max_concurrency,
      cache: form.cache,
    })
    persistProviderProbes(String(route.params.id), visual.value.providers)
    message.success('已保存')
    return true
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '保存失败')
    return false
  }
}

async function runEval() {
  running.value = true
  try {
    const saved = await save()
    if (!saved) return
    const run = await api.createRun({
      config_id: String(route.params.id),
      max_concurrency: form.max_concurrency,
      cache: form.cache,
      description: form.description,
    })
    message.success('测评已启动')
    router.push(`/runs/${run.id}`)
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '启动失败')
  } finally {
    running.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page detail-page">
    <a-spin :spinning="loading" class="page-spin">
      <div class="grid">
        <div class="panel editor-panel">
          <a-tabs class="top-tabs" :active-key="activeTab" @change="onTabChange">
            <template #leftExtra>
              <a-tooltip title="返回列表">
                <a-button type="text" class="back-btn" @click="router.push('/configs')">
                  <ArrowLeftOutlined />
                </a-button>
              </a-tooltip>
            </template>
            <a-tab-pane key="visual" tab="可视化" class="fill-pane">
              <div class="visual-stack">
                <nav class="stepper" aria-label="录入步骤">
                  <template v-for="(item, index) in steps" :key="item.step">
                    <button
                      type="button"
                      class="step"
                      :class="{ active: visualStep === item.step, done: visualStep > item.step }"
                      @click="visualStep = item.step"
                    >
                      <span class="circle">{{ item.step }}</span>
                      <span class="step-label">{{ item.label }}</span>
                    </button>
                    <span
                      v-if="index < steps.length - 1"
                      class="step-line"
                      :class="{ filled: visualStep > item.step }"
                      aria-hidden="true"
                    />
                  </template>
                </nav>

                <div class="step-body">
                  <section v-show="visualStep === 1" class="panel-block">
                    <header class="panel-head">
                      <div class="head-text">
                        <h3>基本信息</h3>
                        <p>填写任务名称与描述，便于在任务列表中识别和管理本次测评配置。</p>
                      </div>
                    </header>
                    <div class="panel-body">
                      <div class="meta-grid">
                        <div class="field">
                          <label>任务名称</label>
                          <a-input v-model:value="form.name" placeholder="请录入任务名称" />
                        </div>
                        <div class="field">
                          <label>描述</label>
                          <a-textarea
                            v-model:value="form.description"
                            :rows="4"
                            placeholder="请录入描述内容"
                            @update:value="onDescriptionChange"
                          />
                        </div>
                      </div>
                    </div>
                  </section>

                  <VisualConfigForm
                    v-show="visualStep !== 1"
                    v-model="visual"
                    :config-id="String(route.params.id || '')"
                    :task-name="form.name"
                    :section="
                      (visualStep === 1
                        ? 'prompts'
                        : steps[visualStep - 1].key) as 'prompts' | 'providers' | 'tests'
                    "
                  />
                </div>
              </div>
            </a-tab-pane>
            <a-tab-pane key="yaml" tab="YAML" class="fill-pane">
              <div class="yaml-wrap">
                <div class="yaml-bar">
                  <span>promptfooconfig.yaml</span>
                  <span class="mono muted">切回可视化会再解析</span>
                </div>
                <a-textarea
                  v-model:value="form.yaml_content"
                  class="mono editor yaml-editor"
                />
              </div>
            </a-tab-pane>
          </a-tabs>
        </div>

        <aside class="panel side">
          <div class="side-top">
            <div class="side-head">
              <h3>运行</h3>
              <p>保存后启动 promptfoo</p>
            </div>

            <div class="matrix">
              <div class="matrix-label">测评矩阵</div>
              <div class="matrix-value mono">{{ matrixHint }}</div>
              <div class="matrix-hint">提示词 × 供应商 × 测试用例</div>
            </div>

            <a-form layout="vertical" class="side-form">
              <a-form-item label="并发数">
                <a-input-number v-model:value="form.max_concurrency" :min="1" :max="20" style="width: 100%" />
              </a-form-item>
              <a-form-item label="使用缓存">
                <a-switch v-model:checked="form.cache" />
              </a-form-item>
            </a-form>
          </div>

          <div class="side-actions">
            <a-button class="side-btn" @click="save">保存</a-button>
            <a-button class="side-btn" type="primary" :loading="running" @click="runEval">运行</a-button>
          </div>
        </aside>
      </div>
    </a-spin>
  </div>
</template>

<style scoped>
.page.detail-page {
  height: 100%;
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.page-spin {
  flex: 1;
  min-height: 0;
  height: 100%;
}

.detail-page :deep(.ant-spin-nested-loading),
.detail-page :deep(.ant-spin-container) {
  height: 100%;
  min-height: 0;
}

.detail-page :deep(.ant-spin-container) {
  display: flex;
  flex-direction: column;
}

.grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 16px;
  align-items: stretch;
  flex: 1;
  min-height: 0;
  height: 100%;
}

.editor-panel {
  padding: 12px 24px 20px;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.top-tabs {
  flex: 1;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  display: flex !important;
  flex-direction: column;
}

.top-tabs :deep(.ant-tabs-nav) {
  margin-bottom: 16px;
  flex-shrink: 0;
}

.top-tabs :deep(.ant-tabs-extra-content) {
  display: flex;
  align-items: center;
}

.top-tabs :deep(.ant-tabs-content-holder) {
  flex: 1 1 auto;
  min-height: 0;
  height: 0; /* force flex child to take remaining height in column flex */
  overflow: hidden;
}

.top-tabs :deep(.ant-tabs-content),
.top-tabs :deep(.ant-tabs-tabpane),
.top-tabs :deep(.ant-tabs-tabpane-active) {
  height: 100%;
}

.top-tabs :deep(.ant-tabs-tabpane-active) {
  display: flex !important;
  flex-direction: column;
}

.back-btn {
  width: 32px;
  height: 32px;
  padding: 0;
  margin-right: 4px;
  color: var(--ek-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.back-btn:hover {
  color: var(--ek-ink);
}

.visual-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
  flex: 1;
  min-height: 0;
  height: 100%;
}

.step-body {
  flex: 1 1 auto;
  min-height: 0;
  height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
}

.step-body > .panel-block {
  flex: 1;
  min-height: 100%;
}

.step-body :deep(.visual) {
  flex: 1;
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.step-body :deep(.panel-block) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.step-body :deep(.panel-block-compact) {
  flex: 0 0 auto;
  min-height: auto;
  height: auto;
}

.step-body :deep(.panel-body) {
  flex: 1;
}

.step-body :deep(.panel-block-compact .panel-body) {
  flex: 0 0 auto;
}

.stepper {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0;
  padding: 4px 8px 8px;
  flex-shrink: 0;
}

.step {
  appearance: none;
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  min-width: 64px;
  color: var(--ek-muted);
}

.circle {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  border: 1.5px solid var(--ek-border);
  background: var(--ek-surface);
  color: var(--ek-secondary);
  display: grid;
  place-items: center;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 13px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.step-label {
  font-size: 12px;
  line-height: 16px;
  color: inherit;
  white-space: nowrap;
}

.step:hover .circle {
  border-color: rgba(15, 118, 110, 0.35);
  color: var(--ek-accent-ink);
}

.step.active {
  color: var(--ek-accent-ink);
}

.step.active .circle {
  background: var(--ek-accent);
  border-color: var(--ek-accent);
  color: #fff;
}

.step.done .circle {
  border-color: var(--ek-accent);
  color: var(--ek-accent-ink);
  background: rgba(15, 118, 110, 0.08);
}

.step-line {
  flex: 1;
  height: 1.5px;
  margin: 15px 8px 0;
  background: var(--ek-border);
  align-self: flex-start;
}

.step-line.filled {
  background: var(--ek-accent);
}

.panel-block {
  border: 1px solid var(--ek-border);
  border-radius: 16px;
  background: var(--ek-surface);
  overflow: hidden;
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.panel-head {
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

.head-text p {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 18px;
  color: var(--ek-muted);
}

.panel-body {
  padding: 16px 20px 20px;
  flex: 1;
}

.meta-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field label {
  font-size: 12px;
  line-height: 16px;
  color: var(--ek-muted);
}

.yaml-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
  height: 100%;
  min-height: 0;
}

.yaml-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--ek-secondary);
  flex-shrink: 0;
}

.yaml-bar .muted {
  color: var(--ek-muted);
}

.editor {
  font-size: 13px;
  line-height: 1.55;
  background: #f3f5f8;
}

.yaml-editor {
  flex: 1;
  min-height: 0;
  resize: none;
}

.yaml-editor :deep(textarea) {
  height: 100% !important;
  min-height: 280px;
  resize: none;
}

.side {
  padding: 20px;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.side-top {
  flex: 1;
}

.side-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 500;
  color: var(--ek-ink);
}

.side-head p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ek-muted);
  line-height: 18px;
}

.matrix {
  margin: 16px 0 0;
  padding: 14px 16px;
  border-radius: 12px;
  background: var(--ek-raised);
  border: 1px solid var(--ek-border);
}

.matrix-label {
  font-size: 12px;
  color: var(--ek-muted);
  line-height: 16px;
}

.matrix-value {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 500;
  letter-spacing: -0.02em;
  color: var(--ek-accent-ink);
  line-height: 1.1;
}

.matrix-hint {
  margin-top: 4px;
  font-size: 11px;
  color: var(--ek-muted);
}

.side-form {
  margin-top: 16px;
}

.side-form :deep(.ant-form-item) {
  margin-bottom: 12px;
}

.side-actions {
  margin-top: auto;
  padding-top: 16px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.side-btn {
  width: 100%;
}

.mono {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 960px) {
  .detail-page {
    height: auto;
    min-height: calc(100vh - 48px);
    overflow: visible;
  }

  .grid {
    grid-template-columns: 1fr;
    height: auto;
  }

  .editor-panel,
  .side {
    height: auto;
  }

  .top-tabs :deep(.ant-tabs-content-holder),
  .step-body {
    height: auto;
    overflow: visible;
  }
}
</style>
