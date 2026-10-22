<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { uiMore } from '@/composables/ui'
import { T } from '@/data/root-texts'

/* Content height cap + shared "more content" modal (design cap-box behaviour). */
const props = withDefaults(defineProps<{ height?: number; title?: string }>(), {
  height: 240,
  title: '',
})

const el = ref<HTMLElement | null>(null)
const clipped = ref(false)

function measure() {
  if (!el.value) return
  clipped.value = el.value.scrollHeight > props.height + 12
}
onMounted(measure)

function openMore() {
  if (el.value) uiMore(props.title || T.moreContent, el.value.innerHTML)
}

const CHEV = '\u2304'
</script>

<template>
  <div
    ref="el"
    :class="'cap-fade' + (clipped ? ' cap-clip' : '')"
    :style="clipped ? { maxHeight: height + 'px', overflow: 'hidden' } : {}"
  >
    <slot />
  </div>
  <div class="cap-more-row" v-if="clipped">
    <button class="btn btn-ghost btn-sm btn-more" type="button" @click="openMore">{{ CHEV }} {{ T.moreContent }}</button>
  </div>
</template>
