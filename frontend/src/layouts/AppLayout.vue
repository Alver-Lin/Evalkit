<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

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
        <div class="mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" fill="none">
            <rect width="32" height="32" rx="8" fill="currentColor" class="mark-bg" />
            <rect x="7" y="7" width="7.5" height="7.5" rx="1.5" fill="#fff" fill-opacity=".92" />
            <rect x="17.5" y="7" width="7.5" height="7.5" rx="1.5" fill="#fff" fill-opacity=".38" />
            <rect x="7" y="17.5" width="7.5" height="7.5" rx="1.5" fill="#fff" fill-opacity=".38" />
            <path
              d="M18.8 20.1l2.1 2.1 3.6-3.7"
              stroke="#fff"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </div>
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
          <span class="nav-icon" aria-hidden="true">
            <svg viewBox="0 0 16 16" fill="none">
              <rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1" stroke="currentColor" stroke-width="1.4" />
              <rect x="9" y="2.5" width="4.5" height="4.5" rx="1" stroke="currentColor" stroke-width="1.4" />
              <rect x="2.5" y="9" width="4.5" height="4.5" rx="1" stroke="currentColor" stroke-width="1.4" />
              <path
                d="M9.6 10.7l1.4 1.4 2.4-2.5"
                stroke="currentColor"
                stroke-width="1.4"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </span>
          <span>测评任务</span>
        </a-menu-item>
        <a-menu-item key="runs">
          <span class="nav-icon" aria-hidden="true">
            <svg viewBox="0 0 16 16" fill="none">
              <path
                d="M3 12.5V8.2M7 12.5V4.5M11 12.5V6.8M13.5 13H2.5"
                stroke="currentColor"
                stroke-width="1.4"
                stroke-linecap="round"
              />
            </svg>
          </span>
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
  flex: 0 0 28px;
  color: var(--ek-accent);
  line-height: 0;
}

.mark svg {
  width: 100%;
  height: 100%;
  display: block;
}

.mark-bg {
  color: var(--ek-accent);
  fill: currentColor;
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

.nav :deep(.ant-menu-item) {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-inline: 8px;
  width: calc(100% - 16px);
  border-radius: 8px;
  height: 40px;
  line-height: 40px;
}

.nav :deep(.ant-menu-item .ant-menu-title-content) {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.nav-icon {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 16px;
  color: var(--ek-muted);
}

.nav-icon svg {
  width: 16px;
  height: 16px;
  display: block;
}

.nav :deep(.ant-menu-item-selected) {
  color: var(--ek-accent-ink);
  background: rgba(15, 118, 110, 0.08);
}

.nav :deep(.ant-menu-item-selected .nav-icon) {
  color: var(--ek-accent-ink);
}

.nav :deep(.ant-menu-item:hover .nav-icon) {
  color: var(--ek-accent);
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
