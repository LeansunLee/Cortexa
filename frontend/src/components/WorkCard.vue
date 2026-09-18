<template>
  <div class="work-summary" :class="{ 'is-candidate': item.status === 'candidate' }">
    <div class="summary-badges">
      <span class="summary-priority" :class="item.priority || 'P2'">{{ item.priority || 'P2' }}</span>
      <span class="summary-status" :class="item.status"><i aria-hidden="true"></i>{{ states[item.status] || '待确认' }}</span>
    </div>
    <div class="summary-body">
      <h3 class="summary-title" :title="item.title">{{ item.title }}</h3>
      <p class="summary-goal" :title="item.goal">{{ item.goal || '暂未填写执行目标' }}</p>
    </div>
    <div v-if="$slots.actions" class="summary-actions" :class="{ 'is-candidate': item.status === 'candidate' }"><slot name="actions" /></div>
    <div v-if="item.status !== 'candidate'" class="summary-footer">
      <span class="summary-owner" :title="`负责人：${item.assignee_name || '待指定'}`"><UserRound :size="14" /><span>{{ item.assignee_name || '待指定' }}</span></span>
      <span class="summary-due" :class="{ 'is-overdue': overdue }" :title="`截止时间：${dueLabel}`"><Clock3 :size="14" />{{ dueLabel }}</span>
    </div>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { UserRound, Clock3 } from 'lucide-vue-next'
const props = defineProps({ item: { type: Object, required: true } })
const states = {draft:'草稿',pending:'待处理',todo:'待开始',in_progress:'进行中',review:'待验收',completed:'已完成',rejected:'退回修改',cancelled:'已取消',candidate:'待确认',accepted:'已创建'}
const due = computed(() => props.item.due_at || props.item.suggested_due_at)
const dueLabel = computed(() => due.value ? new Date(due.value).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '未设截止时间')
const overdue = computed(() => due.value && !['completed','cancelled','candidate'].includes(props.item.status) && new Date(due.value) < new Date())
</script>
<style scoped>
.work-summary { box-sizing:border-box; height:240px; min-width:0; padding:18px; display:flex; flex-direction:column; gap:10px; border:1px solid var(--border); border-radius:14px; background:var(--surface); color:var(--text); box-shadow:0 2px 6px color-mix(in srgb,var(--text) 3%,transparent); transition:border-color .18s,box-shadow .18s; }
.work-summary:hover { border-color:color-mix(in srgb,var(--primary) 36%,var(--border)); box-shadow:0 4px 14px color-mix(in srgb,var(--text) 6%,transparent); }
.work-summary.is-candidate { padding-bottom:10px; }
.summary-badges { display:flex; align-items:center; justify-content:space-between; gap:8px; height:22px; flex-shrink:0; }
.summary-priority,.summary-status { display:inline-flex; align-items:center; gap:5px; padding:1px 7px; border-radius:6px; font-size:11px; line-height:20px; font-weight:500; background:var(--surface2); color:var(--text2); }
.summary-priority.P0 { color:var(--danger); background:var(--danger-bg); font-weight:700; }
.summary-priority.P1 { color:var(--text); background:var(--surface2); font-weight:600; }
.summary-status i { width:5px; height:5px; border-radius:50%; background:currentColor; }
.summary-status.completed,.summary-status.accepted { color:var(--success); background:var(--success-bg); }
.summary-status.in_progress { color:var(--primary); background:var(--primary-light); }
.summary-status.review,.summary-status.rejected { color:var(--primary); background:var(--primary-light); }
.summary-body { min-height:96px; display:flex; flex-direction:column; gap:8px; flex-shrink:0; }
.work-summary .summary-title { margin:0; font-size:15px; font-weight:600; line-height:22px; max-height:44px; flex-shrink:0; color:var(--text); }
.work-summary .summary-goal { margin:0; font-size:13px; line-height:21px; height:42px; flex-shrink:0; color:var(--text2); }
.summary-title,.summary-goal { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; overflow-wrap:anywhere; }
.summary-actions { display:flex; justify-content:flex-end; align-items:center; gap:8px; height:28px; flex-shrink:0; }
.summary-actions.is-candidate { margin-top:auto; }
.summary-footer { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-top:auto; min-height:20px; font-size:12px; line-height:20px; color:var(--text2); }
.summary-owner,.summary-due { display:flex; align-items:center; gap:5px; min-width:0; }
.summary-owner span { overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.summary-footer svg { flex-shrink:0; color:var(--text3); }
.summary-due { flex-shrink:0; white-space:nowrap; font-variant-numeric:tabular-nums; }
.summary-due.is-overdue { color:var(--danger); }
</style>
