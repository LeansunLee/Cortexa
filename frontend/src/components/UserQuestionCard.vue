<template>
  <form class="user-question-card" :class="{ preparing }" aria-label="待你决策" @submit.prevent="submit">
    <header><span class="question-badge" :class="{ arriving: preparing }">?</span><div><strong>{{ question.agent_name }} 需要你的选择</strong><small>{{ statusHint }}</small></div></header>
    <h3 class="q-title">{{ question.question }}</h3>
    <p v-if="question.answer" class="question-submitted">已提交：{{ question.answer }}<template v-if="question.auto">（超时按推荐自动继续）</template></p>
    <p v-if="question.notice" role="status">{{ question.notice }}</p>

    <!-- Entrance skeleton: the agent is laying out the options. -->
    <div v-if="preparing" class="q-skeleton" aria-hidden="true">
      <p class="q-preparing">正在整理选项<span class="loading-dots"><i></i><i></i><i></i></span></p>
      <div v-for="n in skeletonCount" :key="n" class="sk sk-option"></div>
    </div>

    <fieldset v-else-if="question.options?.length" :disabled="busy || question.status !== 'pending'">
      <legend class="sr-only">{{ question.multi_select ? '可以选择多项' : '请选择一项' }}</legend>
      <label v-for="(option, index) in question.options" :key="index"
        :class="{ selected: selected.includes(index), recommended: index === question.recommended_option_index, settled: question.status !== 'pending' && !selected.includes(index) }"
        :style="{ animationDelay: `${index * 60}ms` }">
        <input :type="question.multi_select ? 'checkbox' : 'radio'" :name="`question-${question.id}`" :checked="selected.includes(index)" @change="choose(index)" />
        <span>{{ option }}<em v-if="index === question.recommended_option_index" class="recommend-tag">推荐</em></span>
      </label>
    </fieldset>
    <p v-if="!preparing && question.recommendation_reason && question.status === 'pending'" class="recommend-reason">推荐理由：{{ question.recommendation_reason }}</p>
    <label v-if="question.allow_free_text" class="question-text">{{ question.options?.length ? '补充说明 / 其他答案' : '你的回答' }}
      <textarea v-model="text" rows="2" maxlength="4000" placeholder="填写你的想法…" :disabled="busy || question.status !== 'pending'" />
    </label>
    <footer><span>{{ question.multi_select ? '可多选' : '单选' }}<template v-if="question.allow_free_text"> · 支持自由填写</template><template v-if="autoHint"> · {{ autoHint }}</template></span><button v-if="question.can_recover" type="button" class="btn btn-primary" :disabled="busy" @click="$emit('recover', question.id)">{{ busy ? '正在核实…' : '核实原会话并继续' }}</button><button v-else type="submit" class="btn btn-primary" :disabled="busy || question.status !== 'pending' || (!selected.length && !text.trim())">{{ busy || question.status === 'answering' ? '正在继续…' : '确认并继续' }}</button></footer>
  </form>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
const props = defineProps({ question: { type: Object, required: true }, busy: Boolean })
const emit = defineEmits(['answer','recover'])
const selected = ref([])
const text = ref('')
const preparing = ref(false)
let prepareTimer = null
const reducedMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
const skeletonCount = computed(() => Math.max(2, Math.min(props.question.options?.length || 2, 4)))
const statusHint = computed(() => props.question.status === 'interrupted' ? '执行已中断，待核实结果' : props.question.status === 'answering' ? '回答已提交，等待执行结果' : '回答后将继续原任务')
const autoHint = computed(() => {
  if (props.question.status !== 'pending' || props.question.multi_select || props.question.recommended_option_index == null || !props.question.auto_timeout_seconds) return ''
  const hours = props.question.auto_timeout_seconds / 3600
  const span = hours >= 1 ? `${Math.round(hours)} 小时` : `${Math.round(props.question.auto_timeout_seconds / 60)} 分钟`
  return `超过 ${span} 未选择将按推荐继续`
})
function playEntrance() {
  selected.value = []
  text.value = ''
  clearTimeout(prepareTimer)
  if (reducedMotion || props.question.status !== 'pending') { preparing.value = false; return }
  preparing.value = true
  prepareTimer = setTimeout(() => { preparing.value = false }, 620)
}
watch(() => props.question.id, playEntrance, { immediate: true })
onBeforeUnmount(() => clearTimeout(prepareTimer))
const choose = index => { selected.value = props.question.multi_select ? selected.value.includes(index) ? selected.value.filter(i => i !== index) : [...selected.value, index] : [index] }
const submit = () => { if (!props.busy && props.question.status === 'pending' && (selected.value.length || text.value.trim())) emit('answer', { question_id: props.question.id, selected_indices: selected.value, text: text.value.trim() }) }
</script>
<style scoped>
.user-question-card{width:100%;box-sizing:border-box;padding:22px;border:1px solid var(--border);border-radius:18px;background:var(--surface-card);box-shadow:0 4px 18px rgba(15,23,42,.04);color:var(--text-primary);position:relative}
header{display:flex;gap:12px;align-items:center}header div{display:flex;flex-direction:column;gap:4px}header strong{font-size:13px;font-weight:600;line-height:1.75}header small,footer>span{color:var(--text-secondary);font-size:12px}
.question-badge{width:32px;height:32px;border-radius:50%;background:var(--surface2);display:grid;place-items:center;font-weight:700;color:var(--primary);flex-shrink:0}
.question-badge.arriving{animation:badge-halo 1.1s ease-out 1}
.q-title{font-size:13px;font-weight:400;line-height:1.75;margin:18px 0 14px;white-space:pre-wrap;overflow-wrap:anywhere}
.q-title,.recommend-reason,.question-text,footer{animation:rise-in .45s ease both}
/* Entrance skeleton */
.q-skeleton{display:flex;flex-direction:column;gap:8px}
.q-preparing{margin:0 0 6px;display:flex;align-items:center;gap:6px;color:var(--text-secondary);font-size:12.5px}
.loading-dots{display:inline-flex;align-items:center;gap:3px}
.loading-dots i{width:5px;height:5px;border-radius:50%;background:var(--primary);animation:dots-bounce 1.4s infinite ease-in-out}
.loading-dots i:nth-child(1){animation-delay:-.32s}
.loading-dots i:nth-child(2){animation-delay:-.16s}
.sk{border-radius:10px;background:linear-gradient(90deg,var(--surface2) 25%,var(--border) 45%,var(--surface2) 65%);background-size:200% 100%;animation:sk-shimmer 1.4s linear infinite}
.sk-option{height:46px}
/* Options */
fieldset{border:0;padding:0;margin:0;display:grid;gap:8px}
fieldset legend{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
fieldset label{display:flex;gap:10px;align-items:flex-start;padding:12px 14px;border:1px solid var(--border);border-radius:10px;cursor:pointer;font-size:13px;line-height:1.75;position:relative;overflow:hidden;animation:rise-in .45s ease both;transition:transform .16s ease,border-color .16s ease,background .16s ease}
fieldset label:hover{transform:translateY(-1px);border-color:color-mix(in srgb,var(--primary) 32%,var(--border))}
fieldset label.selected{border-color:var(--primary);background:var(--surface2)}
fieldset label.settled{opacity:.62}
/* Recommended: persistent accent + one-time sweep */
fieldset label.recommended{border-color:color-mix(in srgb,var(--primary) 45%,var(--border))}
fieldset label.recommended::before{content:'';position:absolute;left:0;top:10px;bottom:10px;width:3px;border-radius:999px;background:linear-gradient(180deg,var(--primary),color-mix(in srgb,var(--primary) 40%,transparent))}
fieldset label.recommended:not(.settled)::after{content:'';position:absolute;inset:0;border-radius:inherit;background:linear-gradient(105deg,transparent 42%,color-mix(in srgb,var(--primary) 14%,transparent) 50%,transparent 58%);transform:translateX(-130%);animation:sweep-once 1.5s ease .35s 1 forwards;pointer-events:none}
.recommend-tag{display:inline-flex;align-items:center;margin-left:8px;padding:0 7px;border-radius:999px;border:1px solid var(--primary);background:var(--primary-light);color:var(--primary);font-size:11px;font-style:normal;font-weight:600;line-height:18px;vertical-align:1px;animation:pop-in .3s cubic-bezier(.34,1.56,.64,1) .5s 1 both}
.recommend-reason{margin:12px 0 0;padding:10px 12px;border-left:3px solid var(--primary);border-radius:8px;background:color-mix(in srgb,var(--primary) 6%,var(--surface));color:var(--text2);font-size:12.5px;line-height:1.7}
input{margin:4px 0 0;accent-color:var(--primary);flex-shrink:0}
.question-text{display:grid;gap:8px;margin-top:16px;font-size:13px;color:var(--text-secondary)}
textarea{box-sizing:border-box;width:100%;resize:vertical;min-height:70px;padding:12px;border:1px solid var(--border);border-radius:10px;color:var(--text-primary);background:var(--surface);font:inherit}
footer{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:16px}
.question-submitted{font-size:13px;color:var(--text2);line-height:1.6}
@media(max-width:600px){.user-question-card{padding:16px}footer{flex-wrap:wrap}footer button{margin-left:auto}}
@keyframes rise-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@keyframes dots-bounce{0%,80%,100%{transform:scale(.6);opacity:.35}40%{transform:scale(1);opacity:1}}
@keyframes sk-shimmer{from{background-position:200% 0}to{background-position:-200% 0}}
@keyframes badge-halo{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--primary) 35%,transparent)}70%{box-shadow:0 0 0 12px transparent}100%{box-shadow:0 0 0 0 transparent}}
@keyframes sweep-once{to{transform:translateX(130%)}}
@keyframes pop-in{from{opacity:0;transform:scale(.6)}to{opacity:1;transform:scale(1)}}
@media (prefers-reduced-motion: reduce){.user-question-card *,.user-question-card::before,.user-question-card::after{animation:none !important;transition:none !important}}
</style>
<style>
/* Glass appearance: liquid panel per the house rule — native blur only, never backdrop-filter: url(). */
:root[data-color-theme="glass"] .user-question-card{
  background-color:var(--glass-menu-background,var(--surface));
  background-image:var(--glass-popover-gradient,none);
  border-color:var(--glass-edge-border,var(--border));
  box-shadow:var(--glass-edge-shadow,none),0 18px 44px color-mix(in srgb,var(--text) 16%,transparent);
  backdrop-filter:blur(22px) saturate(135%);
  -webkit-backdrop-filter:blur(22px) saturate(135%);
}
:root[data-color-theme="glass"] .user-question-card::before{
  content:'';position:absolute;inset:0;border-radius:inherit;pointer-events:none;z-index:0;
  background:linear-gradient(180deg,rgba(255,255,255,calc(var(--glass-edge-alpha,.2) * .2)) 0%,transparent 16%);
}
:root[data-color-theme="glass"] .user-question-card>*{position:relative;z-index:1}
:root[data-color-theme="glass"] .user-question-card fieldset label:hover{
  background:var(--glass-selection-background,var(--primary-light));
}
</style>
