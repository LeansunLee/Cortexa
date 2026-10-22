<template>
  <div class="msg-artifacts" aria-label="本条回复的产出物">
    <article v-for="a in artifacts" :key="a.id" class="msg-artifact" tabindex="0" role="button"
      :title="`查看 ${a.title}`" @click="$emit('open', a)" @keydown.enter.prevent="$emit('open', a)">
      <span class="msg-artifact-icon"><FileText :size="14" /></span>
      <span class="msg-artifact-body">
        <span class="msg-artifact-title">{{ a.title }}</span>
        <span class="msg-artifact-meta">{{ a.filename }} · {{ formatSize(a.size) }} · 点击查看/编辑</span>
      </span>
      <a class="msg-artifact-download" :href="artifactApi.downloadUrl(conversationId, a.id)" download
        :aria-label="`下载 ${a.title}`" @click.stop><Download :size="13" /></a>
    </article>
  </div>
</template>

<script setup>
import { Download, FileText } from 'lucide-vue-next'
import { artifactApi } from '../../api'

defineProps({ conversationId: String, artifacts: { type: Array, default: () => [] } })
defineEmits(['open'])

function formatSize(n) {
  if (n == null) return ''
  return n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`
}
</script>

<style scoped>
.msg-artifacts { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
.msg-artifact { display: flex; align-items: center; gap: 8px; max-width: 460px; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); cursor: pointer; }
.msg-artifact:hover, .msg-artifact:focus-visible { border-color: var(--primary); outline: none; }
.msg-artifact-icon { width: 26px; height: 26px; display: grid; place-items: center; border-radius: 8px; background: var(--primary-light); color: var(--primary); flex-shrink: 0; }
.msg-artifact-body { min-width: 0; flex: 1; display: flex; flex-direction: column; }
.msg-artifact-title { font-size: 12.5px; line-height: 17px; font-weight: 500; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.msg-artifact-meta { font-size: 11px; line-height: 15px; color: var(--text3); }
.msg-artifact-download { display: grid; place-items: center; width: 24px; height: 24px; border-radius: var(--radius-xs); color: var(--text3); flex-shrink: 0; }
.msg-artifact-download:hover { background: var(--surface2); color: var(--text); }
</style>
