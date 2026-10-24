<template>
  <form class="user-question-card" aria-label="待你决策" @submit.prevent="submit">
    <header><span class="question-badge">?</span><div><strong>{{ question.agent_name }} 需要你的选择</strong><small>{{ question.status === 'interrupted' ? '执行已中断，待核实结果' : question.status === 'answering' ? '回答已提交，等待执行结果' : '回答后将继续原任务' }}</small></div></header>
    <h3>{{ question.question }}</h3>
    <p v-if="question.answer" class="question-submitted">已提交：{{ question.answer }}<template v-if="question.auto">（超时按推荐自动继续）</template></p>
    <p v-if="question.notice" role="status">{{ question.notice }}</p>
    <fieldset v-if="question.options?.length" :disabled="busy || question.status !== 'pending'">
      <legend class="sr-only">{{ question.multi_select ? '可以选择多项' : '请选择一项' }}</legend>
      <label v-for="(option, index) in question.options" :key="index" :class="{ selected: selected.includes(index), recommended: index === question.recommended_option_index }">
        <input :type="question.multi_select ? 'checkbox' : 'radio'" :name="`question-${question.id}`" :checked="selected.includes(index)" @change="choose(index)" />
        <span>{{ option }}<em v-if="index === question.recommended_option_index" class="recommend-tag">推荐</em></span>
      </label>
    </fieldset>
    <p v-if="question.recommendation_reason && question.status === 'pending'" class="recommend-reason">推荐理由：{{ question.recommendation_reason }}</p>
    <label v-if="question.allow_free_text" class="question-text">{{ question.options?.length ? '补充说明 / 其他答案' : '你的回答' }}
      <textarea v-model="text" rows="2" maxlength="4000" placeholder="填写你的想法…" :disabled="busy || question.status !== 'pending'" />
    </label>
    <footer><span>{{ question.multi_select ? '可多选' : '单选' }}<template v-if="question.allow_free_text"> · 支持自由填写</template><template v-if="autoHint"> · {{ autoHint }}</template></span><button v-if="question.can_recover" type="button" class="btn btn-primary" :disabled="busy" @click="$emit('recover', question.id)">{{ busy ? '正在核实…' : '核实原会话并继续' }}</button><button v-else type="submit" class="btn btn-primary" :disabled="busy || question.status !== 'pending' || (!selected.length && !text.trim())">{{ busy || question.status === 'answering' ? '正在继续…' : '确认并继续' }}</button></footer>
  </form>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
const props = defineProps({ question: { type: Object, required: true }, busy: Boolean })
const emit = defineEmits(['answer','recover'])
const selected = ref([])
const text = ref('')
const autoHint = computed(() => {
  if (props.question.status !== 'pending' || props.question.multi_select || props.question.recommended_option_index == null || !props.question.auto_timeout_seconds) return ''
  const hours = props.question.auto_timeout_seconds / 3600
  const span = hours >= 1 ? `${Math.round(hours)} 小时` : `${Math.round(props.question.auto_timeout_seconds / 60)} 分钟`
  return `超过 ${span} 未选择将按推荐继续`
})
watch(() => props.question.id, () => { selected.value = []; text.value = '' })
const choose = index => { selected.value = props.question.multi_select ? selected.value.includes(index) ? selected.value.filter(i => i !== index) : [...selected.value, index] : [index] }
const submit = () => { if (!props.busy && props.question.status === 'pending' && (selected.value.length || text.value.trim())) emit('answer', { question_id: props.question.id, selected_indices: selected.value, text: text.value.trim() }) }
</script>
<style scoped>
.user-question-card{width:100%;box-sizing:border-box;padding:22px;border:1px solid var(--border);border-radius:18px;background:var(--surface-card);box-shadow:0 4px 18px rgba(15,23,42,.04);color:var(--text-primary)}
header{display:flex;gap:12px;align-items:center}header div{display:flex;flex-direction:column;gap:4px}header strong{font-size:13px;font-weight:600;line-height:1.75}header small,footer>span{color:var(--text-secondary);font-size:12px}.question-badge{width:32px;height:32px;border-radius:50%;background:var(--surface2);display:grid;place-items:center;font-weight:700;color:var(--primary)}h3{font-size:13px;font-weight:400;line-height:1.75;margin:18px 0 14px;white-space:pre-wrap;overflow-wrap:anywhere}fieldset{border:0;padding:0;margin:0;display:grid;gap:8px}fieldset label{display:flex;gap:10px;align-items:flex-start;padding:12px 14px;border:1px solid var(--border);border-radius:10px;cursor:pointer;font-size:13px;line-height:1.75}fieldset label.selected{border-color:var(--primary);background:var(--surface2)}fieldset label.recommended{border-color:color-mix(in srgb,var(--primary) 45%,var(--border))}.recommend-tag{display:inline-flex;align-items:center;margin-left:8px;padding:0 7px;border-radius:999px;border:1px solid var(--primary);background:var(--primary-light);color:var(--primary);font-size:11px;font-style:normal;font-weight:600;line-height:18px;vertical-align:1px}.recommend-reason{margin:12px 0 0;padding:10px 12px;border-left:3px solid var(--primary);border-radius:8px;background:color-mix(in srgb,var(--primary) 6%,var(--surface));color:var(--text2);font-size:12.5px;line-height:1.7}input{margin:4px 0 0;accent-color:var(--primary);flex-shrink:0}.question-text{display:grid;gap:8px;margin-top:16px;font-size:13px;color:var(--text-secondary)}textarea{box-sizing:border-box;width:100%;resize:vertical;min-height:70px;padding:12px;border:1px solid var(--border);border-radius:10px;color:var(--text-primary);background:var(--surface);font:inherit}footer{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:16px}.question-submitted{font-size:13px;color:var(--text2);line-height:1.6}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}@media(max-width:600px){.user-question-card{padding:16px}footer{flex-wrap:wrap}footer button{margin-left:auto}}
</style>
