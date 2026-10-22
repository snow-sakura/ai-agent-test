<script setup lang="ts">
import { computed, defineAsyncComponent, type Component } from 'vue'
import { useRoute } from 'vue-router'

/* Resolves the implemented view for a tool slug; falls back to a
   placeholder while pages are being ported from the design mockups. */
const views = import.meta.glob<{ default: Component }>('./tools/*.vue')

const route = useRoute()
const slug = computed(() => String(route.params.slug || ''))

const impl = computed(() => {
  const key = './tools/' + slug.value + '.vue'
  const loader = views[key]
  return loader ? defineAsyncComponent(loader) : null
})

const ICON = '\u{1F6A7}'
const TIP = '\u8be5\u6a21\u5757\u6b63\u5728\u6309\u8bbe\u8ba1\u7a3f\u9010\u9875\u79fb\u690d\u4e2d\u2026'
</script>

<template>
  <component :is="impl" v-if="impl" :key="slug" />
  <div v-else class="workspace" style="min-height:100vh">
    <aside class="sidebar" />
    <main class="main-area">
      <div class="card" style="padding:60px;text-align:center">
        <div style="font-size:40px">{{ ICON }}</div>
        <div class="card-title" style="margin-top:10px">{{ slug }}</div>
        <div class="text-dim" style="margin-top:6px">{{ TIP }}</div>
      </div>
    </main>
  </div>
</template>
