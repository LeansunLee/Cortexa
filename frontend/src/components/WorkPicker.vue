<template>
  <div class="project-picker">
    <div v-if="references.length" class="project-refs"><span v-for="w in references" :key="w.id" class="project-chip">@ {{ w.title }}<button type="button" :disabled="disabled" :aria-label="`移除工作${w.title}`" @click="$emit('update',references.filter(x=>x.id!==w.id))">×</button></span></div>
    <div v-if="open" class="project-menu"><p class="hint">本轮引用，最多 5 个工作；仅提供你有权查看的。</p><p v-if="error" role="alert">{{ error }} <button class="btn btn-ghost btn-sm" @click="load">重试</button></p><input v-if="!error" v-model="keyword" placeholder="搜索工作名称" aria-label="搜索引用工作" />
      <SearchSelect v-if="!error" :model-value="''" :options="options" placeholder="搜索并选择工作" aria-label="引用工作" @update:model-value="select" /><button class="btn btn-ghost btn-sm" @click="open=false;$emit('close')">关闭</button></div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { workApi } from '../api'
import SearchSelect from './SearchSelect.vue'
const props=defineProps({references:{type:Array,default:()=>[]},disabled:Boolean})
const emit=defineEmits(['update','close'])
const works=ref([]),open=ref(false),error=ref(''),keyword=ref('')
const statusLabels={draft:'草稿',pending:'待处理',todo:'待开始',in_progress:'进行中',review:'待验收',completed:'已完成',rejected:'退回修改',cancelled:'已取消'}
const options=computed(()=>works.value.filter(w=>!props.references.some(r=>r.id===w.id)).map(w=>({value:w.id,label:`${w.title}（${statusLabels[w.status]||w.status}）`})))
async function load(){error.value='';try{const {data}=await workApi.list({view:'all',search:keyword.value||undefined,limit:200});works.value=data||[]}catch{error.value='工作列表加载失败'}}
function select(id){if(props.disabled || props.references.length>=5)return;const w=works.value.find(w=>w.id===id);if(w){emit('update',[...props.references,{id:w.id,title:w.title}]);open.value=false;emit('close')}}
watch(keyword,load)
defineExpose({openMenu:()=>{if(!props.disabled){open.value=!open.value;if(open.value)load()}}})
onMounted(load)
</script>
