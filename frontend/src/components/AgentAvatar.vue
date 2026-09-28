<template>
  <span v-if="inlineSvg" class="agent-avatar-inline" aria-hidden="true" v-html="inlineSvg" />
  <img v-else-if="avatar" :src="avatarUrl(avatar)" alt="头像" />
  <Bot v-else :size="28" />
</template>
<script setup>
import { computed } from 'vue'
import { Bot } from 'lucide-vue-next'
import { avatarUrl } from '../utils/avatar'

const props = defineProps({ avatar: { type: String, default: '' } })

// Preset avatars are inlined so their background follows the app theme
// (html[data-theme]) instead of only the OS color scheme.
const sources = import.meta.glob('../../../src/cortexa/web/static/avatars/*.svg', { query: '?raw', import: 'default', eager: true })
const presetMap = {}
for (const [file, svg] of Object.entries(sources)) {
  const name = file.split('/').at(-1).replace(/\.svg$/, '')
  presetMap[`/static/avatars/${name}.svg`] = svg.replace(/<style>[\s\S]*?<\/style>/, '')
}
const inlineSvg = computed(() => presetMap[props.avatar] || '')
</script>
<style>
.agent-avatar-inline { display: block; width: 100%; height: 100%; }
.agent-avatar-inline svg { display: block; width: 100%; height: 100%; border-radius: inherit; }
.agent-avatar-inline .av-bg { fill: var(--_av-bg-light); }
:root[data-theme="dark"] .agent-avatar-inline .av-bg { fill: var(--_av-bg-dark); }
</style>
