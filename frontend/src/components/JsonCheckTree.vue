<script setup lang="ts">
import { computed } from 'vue'
import type { JsonPathNode } from '@/utils/jsonPathSelect'

defineOptions({ name: 'JsonCheckTree' })

const props = defineProps<{
  nodes: JsonPathNode[]
  selected: string[]
}>()

const emit = defineEmits<{
  /** Apply the same checked state to one or many paths (parent cascade). */
  toggle: [paths: string[], checked: boolean]
}>()

const selectedSet = computed(() => new Set(props.selected))

/**
 * Paths controlled by clicking this checkbox:
 * - leaf: itself
 * - parent: all selectable descendants (not the parent path itself),
 *   so checking `data` checks id / document / … without duplicating the whole object
 */
function controlledPaths(node: JsonPathNode): string[] {
  if (!node.children.length) {
    return node.selectable ? [node.path] : []
  }
  const out: string[] = []
  function walkDescendants(n: JsonPathNode) {
    for (const child of n.children) {
      if (child.selectable) out.push(child.path)
      if (child.children.length) walkDescendants(child)
    }
  }
  walkDescendants(node)
  return out
}

function branchState(node: JsonPathNode): 'none' | 'some' | 'all' {
  const paths = controlledPaths(node)
  if (!paths.length) return 'none'
  let hit = 0
  for (const path of paths) {
    if (selectedSet.value.has(path)) hit += 1
  }
  if (hit === 0) return 'none'
  if (hit === paths.length) return 'all'
  return 'some'
}

function onToggle(node: JsonPathNode, checked: boolean) {
  const paths = controlledPaths(node)
  if (!paths.length) return
  emit('toggle', paths, checked)
}
</script>

<template>
  <ul class="json-tree">
    <li v-for="node in nodes" :key="node.path" class="json-tree-item">
      <div class="json-tree-row">
        <label class="json-tree-label" :class="{ 'is-branch': node.kind !== 'value' }">
          <a-checkbox
            v-if="node.selectable || node.children.length"
            :checked="branchState(node) === 'all'"
            @update:checked="(v: boolean) => onToggle(node, v)"
          />
          <span v-else class="json-tree-spacer" />
          <span class="json-key mono">{{ node.key }}</span>
          <span class="json-sep">:</span>
          <span class="json-val mono" :class="{ muted: node.kind !== 'value' }">{{ node.preview }}</span>
        </label>
      </div>
      <JsonCheckTree
        v-if="node.children.length"
        class="json-tree-nested"
        :nodes="node.children"
        :selected="selected"
        @toggle="(paths, checked) => emit('toggle', paths, checked)"
      />
    </li>
  </ul>
</template>

<style scoped>
.json-tree {
  list-style: none;
  margin: 0;
  padding: 0;
}

.json-tree-nested {
  margin: 2px 0 2px 18px;
  padding-left: 10px;
  border-left: 1px solid rgba(17, 24, 39, 0.08);
}

.json-tree-item {
  margin: 0;
}

.json-tree-row {
  min-width: 0;
}

.json-tree-label {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 3px 4px;
  border-radius: 6px;
  cursor: pointer;
  min-width: 0;
}

.json-tree-label:hover {
  background: rgba(15, 118, 110, 0.06);
}

.json-tree-spacer {
  width: 16px;
  flex: 0 0 auto;
}

.json-key {
  flex: 0 0 auto;
  color: #0f766e;
  font-size: 12px;
  line-height: 20px;
}

.json-sep {
  color: var(--ek-muted);
  line-height: 20px;
}

.json-val {
  flex: 1 1 auto;
  min-width: 0;
  color: var(--ek-ink);
  font-size: 12px;
  line-height: 20px;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.muted {
  color: var(--ek-muted);
}

.mono {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
</style>
