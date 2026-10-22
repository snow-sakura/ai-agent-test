<script setup lang="ts">
withDefaults(defineProps<{ label: string; value: string | number; sub?: string; color?: string }>(), {
  sub: '',
  color: '',
})
</script>

<template>
  <div class="card stat-card">
    <div class="s-label">{{ label }}</div>
    <div class="s-value" :style="color ? { color } : {}">{{ value }}</div>
    <div class="s-sub" v-if="sub">{{ sub }}</div>
  </div>
</template>
