<script setup lang="ts">
import { toasts, TOAST_ICONS, confirmState, uiConfirmResolve, promptState, uiPromptResolve, moreState } from '@/composables/ui'
import { T } from '@/data/root-texts'
</script>

<template>
  <!-- toast stack (design: #toast-box) -->
  <div id="toast-box">
    <div v-for="t in toasts" :key="t.id" :class="'toast toast-' + t.kind">
      <span class="t-icon">{{ TOAST_ICONS[t.kind] }}</span><span>{{ t.text }}</span>
    </div>
  </div>

  <!-- confirm modal (design: #modal-confirm) -->
  <div :class="'modal-mask' + (confirmState.show ? ' open' : '')">
    <div class="modal modal-sm">
      <div class="modal-head">
        <h3>{{ confirmState.title || T.ok }}</h3>
        <button class="modal-close" @click="uiConfirmResolve(false)">✕</button>
      </div>
      <div class="modal-body">
        <p class="text-dim" style="font-size:13.5px">{{ confirmState.message }}</p>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="uiConfirmResolve(false)">{{ T.cancel }}</button>
        <button :class="'btn ' + (confirmState.danger ? 'btn-danger' : 'btn-primary')" @click="uiConfirmResolve(true)">
          {{ T.ok }}
        </button>
      </div>
    </div>
  </div>

  <!-- prompt modal (design: #modal-prompt) -->
  <div :class="'modal-mask' + (promptState.show ? ' open' : '')">
    <div class="modal modal-sm">
      <div class="modal-head">
        <h3>{{ promptState.title }}</h3>
        <button class="modal-close" @click="uiPromptResolve(false)">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>{{ promptState.label }}</label>
          <input class="input" type="text" v-model="promptState.value" @keyup.enter="uiPromptResolve(true)" />
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="uiPromptResolve(false)">{{ T.cancel }}</button>
        <button class="btn btn-primary" @click="uiPromptResolve(true)">{{ T.ok }}</button>
      </div>
    </div>
  </div>

  <!-- more-content modal shared by CapBox (design: #modal-more) -->
  <div :class="'modal-mask' + (moreState.show ? ' open' : '')" @click.self="moreState.show = false">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ moreState.title }}</h3>
        <button class="modal-close" @click="moreState.show = false">✕</button>
      </div>
      <div class="modal-body">
        <div id="mm-body" class="code-block" style="max-height:60vh;overflow:auto" v-html="moreState.html" />
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="moreState.show = false">{{ T.close }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-mask { pointer-events: none; }
.modal-mask.open { pointer-events: auto; }
</style>
