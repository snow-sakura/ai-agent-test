<script setup lang="ts">
import ToolLayout from '@/layouts/ToolLayout.vue'

/* 薄适配层：27 工具页继续使用 ModuleShell API（slug / #actions / #default），
   实际壳由 layouts/ToolLayout 承载（AppTopBar + 模块侧栏 + 面包屑） */
defineProps<{ slug: string }>()
</script>

<template>
  <ToolLayout :slug="slug">
    <template #actions>
      <slot name="actions" />
    </template>
    <template #default="slotProps">
      <slot name="default" v-bind="slotProps" />
    </template>
  </ToolLayout>
</template>
