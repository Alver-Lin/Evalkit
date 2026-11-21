<script setup lang="ts">
import type { EvalStatus } from '@/types'

defineProps<{ status: EvalStatus }>()

const labelMap: Record<EvalStatus, string> = {
  pending: '等待中',
  running: '运行中',
  succeeded: '成功',
  failed: '失败',
  cancelled: '已暂停',
}

const dotMap: Record<EvalStatus, string> = {
  pending: 'is-mute',
  running: 'is-run',
  succeeded: 'is-ok',
  failed: 'is-fail',
  cancelled: 'is-warn',
}
</script>

<template>
  <span class="status">
    <span class="status-dot" :class="dotMap[status]" />
    {{ labelMap[status] }}
  </span>
</template>

<style scoped>
.status {
  display: inline-flex;
  align-items: center;
  color: var(--ek-secondary);
  font-size: 13px;
  line-height: 20px;
}
</style>
