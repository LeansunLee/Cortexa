<template>
  <aside v-if="notices.length" class="budget-notice" aria-label="本轮预算说明">
    <strong>本轮预算说明</strong>
    <ul><li v-for="item in notices" :key="item.field">
      {{ item.label }}（{{ item.field }}）：{{ number(item.used) }} / {{ number(item.limit) }} {{ item.unit }}。
      <template v-if="item.kind === 'limit'">已达到上限。</template>
      <template v-else-if="item.kind === 'reserve'">剩余 {{ number(item.reserve) }} {{ item.unit }} 已预留给最终回复，停止新增执行。</template>
      <template v-else>剩余预算不足以执行下一次调用<template v-if="item.requested">（需要 {{ number(item.requested) }} {{ item.unit }}）</template>。</template>
    </li></ul>
  </aside>
</template>
<script setup>
defineProps({ notices: { type: Array, default: () => [] } })
const number = value => Number(value || 0).toLocaleString('zh-CN')
</script>
<style scoped>
.budget-notice{margin:14px 0;padding:12px 14px;border:1px solid color-mix(in srgb,var(--primary) 30%,transparent);border-left:3px solid var(--primary);border-radius:8px;background:color-mix(in srgb,var(--primary) 7%,var(--surface));color:var(--primary);font-size:13px;line-height:1.75;overflow-wrap:anywhere}.budget-notice strong{font-size:inherit;font-weight:600}.budget-notice ul{list-style:none;margin:5px 0 0;padding:0}.budget-notice li+li{margin-top:4px}
</style>
