<template>
  <span class="context-hints">
    <span class="llm-context-hint" tabindex="0" :aria-label="`LLM：${text}`" @click.stop>
      <Sparkles :size="11" aria-hidden="true" />
      <span>LLM</span>
      <span class="llm-context-tooltip" aria-hidden="true">{{ text }}</span>
    </span>
    <span v-if="collaborationText" class="collaboration-context-hint" tabindex="0" :aria-label="`协同：${collaborationText}`" @click.stop>
      <UsersRound :size="11" aria-hidden="true" />
      <span>协同</span>
      <span class="collaboration-context-tooltip" aria-hidden="true">{{ collaborationText }}</span>
    </span>
  </span>
</template>

<script setup>
import { Sparkles, UsersRound } from 'lucide-vue-next'
defineProps({
  text: { type: String, required: true },
  collaborationText: { type: String, default: '' },
})
</script>

<style scoped>
.context-hints { display: inline-flex; align-items: center; gap: 4px; margin-left: 6px; vertical-align: middle; }
.llm-context-hint {
  position: relative; display: inline-flex; align-items: center; gap: 3px;
  padding: 2px 5px; border: 1px solid var(--primary);
  border-radius: 5px; color: var(--primary); background: var(--primary-light);
  font-size: 10px; font-weight: 700; line-height: 1.2; vertical-align: middle;
  white-space: nowrap; cursor: help;
}
.llm-context-hint:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.collaboration-context-hint {
  position: relative; display: inline-flex; align-items: center; gap: 3px;
  padding: 2px 5px; border: 1px solid var(--info, #2563eb);
  border-radius: 5px; color: var(--info); background: var(--info-bg);
  font-size: 10px; font-weight: 700; line-height: 1.2; white-space: nowrap; cursor: help;
}
.collaboration-context-hint:focus-visible { outline: 2px solid var(--info, #2563eb); outline-offset: 2px; }
.llm-context-tooltip {
  position: absolute; z-index: 50; top: calc(100% + 7px); left: 0;
  width: max-content; max-width: min(280px, 80vw); padding: 8px 10px;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface); color: var(--text); box-shadow: var(--shadow-md);
  font-size: 11px; font-weight: 400; line-height: 1.55; white-space: normal;
  opacity: 0; visibility: hidden; pointer-events: none;
}
.collaboration-context-tooltip {
  position: absolute; z-index: 50; top: calc(100% + 7px); left: 0;
  width: max-content; max-width: min(280px, 80vw); padding: 8px 10px;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface); color: var(--text); box-shadow: var(--shadow-md);
  font-size: 11px; font-weight: 400; line-height: 1.55; white-space: normal;
  opacity: 0; visibility: hidden; pointer-events: none;
}
.llm-context-hint:hover .llm-context-tooltip,
.llm-context-hint:focus-visible .llm-context-tooltip { opacity: 1; visibility: visible; }
.collaboration-context-hint:hover .collaboration-context-tooltip,
.collaboration-context-hint:focus-visible .collaboration-context-tooltip { opacity: 1; visibility: visible; }
</style>
