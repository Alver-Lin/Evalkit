<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ExperimentOutlined, FileTextOutlined } from '@ant-design/icons-vue'

const route = useRoute()
const router = useRouter()

const selectedKeys = computed(() => {
  if (route.path.startsWith('/runs')) return ['runs']
  return ['configs']
})

function go(key: string) {
  router.push(`/${key}`)
}
</script>

<template>
  <a-layout class="shell">
    <a-layout-sider :width="256" theme="light" class="sider">
      <div class="brand" @click="go('configs')">
        <div class="mark" aria-hidden="true">E</div>
        <div>
          <div class="title">EvalKit</div>
          <div class="subtitle">Promptfoo 评测工作台</div>
        </div>
      </div>
      <a-menu
        mode="inline"
        :selected-keys="selectedKeys"
        class="nav"
        @click="(info: { key: string | number }) => go(String(info.key))"
      >
        <a-menu-item key="configs">
          <ExperimentOutlined />
          <span>测评任务</span>
        </a-menu-item>
        <a-menu-item key="runs">
          <FileTextOutlined />
          <span>测评报告</span>
        </a-menu-item>
      </a-menu>
    </a-layout-sider>
    <a-layout class="main">
      <a-layout-content class="content">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  background: var(--ek-bg);
}

.sider {
  border-right: 1px solid var(--ek-border);
  background: var(--ek-surface) !important;
}

.brand {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 20px 16px 16px;
  cursor: pointer;
}

.mark {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  color: #fff;
  background: var(--ek-ink);
  font-size: 13px;
  font-weight: 500;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}

.title {
  font-size: 16px;
  font-weight: 500;
  letter-spacing: -0.01em;
  color: var(--ek-ink);
  line-height: 1.2;
}

.subtitle {
  margin-top: 2px;
  color: var(--ek-muted);
  font-size: 12px;
  line-height: 16px;
}

.nav {
  border-inline-end: none !important;
  padding: 4px 0 16px;
}

.nav :deep(.ant-menu-item-selected) {
  color: var(--ek-accent-ink);
  background: rgba(15, 118, 110, 0.08);
}

.nav :deep(.ant-menu-item-selected::after) {
  display: none;
}

.main {
  background: var(--ek-bg);
  min-height: 100vh;
  min-width: 0;
  flex: 1;
}

.content {
  margin: 24px;
  padding: 0 4px;
  min-height: calc(100vh - 48px);
  height: calc(100vh - 48px);
  max-height: calc(100vh - 48px);
  box-sizing: border-box;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
}

/* List/detail pages fill the viewport; report pages grow and scroll. */
.content > .list-page,
.content > .detail-page {
  flex: 1;
  min-height: 0;
  height: 100%;
}

.content > .detail-page {
  overflow: hidden;
}

.content > .page:not(.list-page):not(.detail-page) {
  flex: 0 0 auto;
  height: auto;
  min-height: 100%;
}
</style>
