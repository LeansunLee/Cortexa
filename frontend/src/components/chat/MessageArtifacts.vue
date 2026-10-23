<template>
  <section class="artifacts-section" aria-label="对话产出物">
    <h4 class="artifacts-heading"><span class="heading-mark" aria-hidden="true"></span>{{ title }}（{{ artifacts.length }}）</h4>
    <div class="candidate-grid">
      <article v-for="a in artifacts" :key="a.id" class="artifact-summary" tabindex="0" role="button"
        :title="`查看 ${a.title}`" @click="$emit('open', a)" @keydown.enter.prevent="$emit('open', a)">
        <div class="summary-badges">
          <span class="summary-format">{{ a.format === 'markdown' ? 'Markdown' : '文本' }}</span>
          <span class="summary-size">{{ formatSize(a.size) }}</span>
        </div>
        <div class="summary-body">
          <h5 class="summary-title" :title="a.title">{{ a.title }}</h5>
          <p class="summary-filename" :title="a.filename">{{ a.filename }}</p>
        </div>
        <div class="summary-actions">
          <button type="button" class="action-secondary" @click.stop="$emit('open', a)">查看</button>
          <a class="action-download" :href="artifactApi.downloadUrl(conversationId, a.id)" download :aria-label="`下载 ${a.title}`" @click.stop>
            <Download :size="14" /> 下载
          </a>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { Download } from 'lucide-vue-next'
import { artifactApi } from '../../api'

defineProps({
  conversationId: String,
  artifacts: { type: Array, default: () => [] },
  title: { type: String, default: '产出物' },
})
defineEmits(['open'])

function formatSize(n) {
  if (n == null) return ''
  return n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`
}
</script>

<style scoped>
/* 与「可执行工作」候选区统一的区块样式 */
.artifacts-section { margin-top: 16px; }
.artifacts-heading {
  display: flex; align-items: center; gap: 7px;
  margin: 0 0 10px; font-size: 13px; line-height: 20px; font-weight: 600;
}
.heading-mark { width: 4px; height: 14px; border-radius: 999px; background: var(--primary); }
.candidate-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr)); gap: 16px; }
/* 与 WorkCard 统一的卡片样式 */
.artifact-summary {
  box-sizing: border-box; height: 240px; min-width: 0; padding: 18px;
  display: flex; flex-direction: column; gap: 10px;
  border: 1px solid var(--border); border-radius: 14px; background: var(--surface);
  color: var(--text); cursor: pointer;
  box-shadow: 0 2px 6px color-mix(in srgb, var(--text) 3%, transparent);
  transition: border-color .18s, box-shadow .18s;
}
.artifact-summary:hover, .artifact-summary:focus-visible {
  border-color: color-mix(in srgb, var(--primary) 36%, var(--border));
  box-shadow: 0 4px 14px color-mix(in srgb, var(--text) 6%, transparent);
  outline: none;
}
.summary-badges { display: flex; align-items: center; justify-content: space-between; gap: 8px; height: 22px; flex-shrink: 0; }
.summary-format, .summary-size { display: inline-flex; align-items: center; padding: 1px 7px; border-radius: 6px; font-size: 11px; line-height: 20px; font-weight: 500; background: var(--surface2); color: var(--text2); }
.summary-body { min-height: 96px; display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }
.summary-title { margin: 0; font-size: 15px; font-weight: 600; line-height: 22px; max-height: 44px; flex-shrink: 0; color: var(--text); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.summary-filename { margin: 0; font-size: 12px; line-height: 18px; color: var(--text3); overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.summary-actions { margin-top: auto; display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
.action-secondary { height: 28px; padding: 3px 10px; border-radius: 6px; font-family: inherit; font-size: 12px; line-height: 20px; font-weight: 500; cursor: pointer; color: var(--text2); background: transparent; border: 1px solid var(--border); }
.action-secondary:hover { background: var(--surface2); color: var(--text); }
.action-download { display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 3px 10px; border-radius: 6px; font-size: 12px; line-height: 20px; font-weight: 500; color: var(--primary); background: var(--primary-light); border: 1px solid var(--primary); text-decoration: none; }
.action-download:hover { filter: brightness(0.97); }
@media (prefers-reduced-motion: reduce) { .artifact-summary { transition: none; } }
</style>
