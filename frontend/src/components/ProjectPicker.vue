<template>
  <div class="project-picker">
    <div v-if="references.length" class="project-refs"><span v-for="p in references" :key="p.id" class="project-chip"># {{ p.title }}<button type="button" :disabled="disabled" :aria-label="`移除项目${p.title}`" @click="$emit('update',references.filter(x=>x.id!==p.id))">×</button></span></div>
    <div v-if="open || query !== null" class="project-menu"><p class="hint">本轮引用，最多 3 个项目；仅提供有权查看的内容。</p><p v-if="error" role="alert">{{ error }} <button class="btn btn-ghost btn-sm" @click="load">重试</button></p><input v-if="!error" v-model="keyword" placeholder="搜索项目名称" aria-label="搜索引用项目" />
      <SearchSelect v-if="!error" :model-value="''" :options="options" placeholder="搜索并选择项目" aria-label="引用项目" @update:model-value="select" /><button class="btn btn-ghost btn-sm" @click="open=false;$emit('close')">关闭</button></div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import api from '../api'
import SearchSelect from './SearchSelect.vue'
const props=defineProps({references:{type:Array,default:()=>[]},query:{default:null},disabled:Boolean,initialProject:String})
const emit=defineEmits(['update','close'])
const projects=ref([]),open=ref(false),error=ref(''),keyword=ref('')
let generation=0, initialApplied=false
const options=computed(()=>projects.value.filter(p=>!props.references.some(r=>r.id===p.id) && (!props.query || p.title.toLowerCase().includes(props.query.toLowerCase()))).map(p=>({value:p.id,label:p.title+(p.status==='archived'?'（已归档）':'')})))
async function load(){error.value='';try{const ticket=++generation;const {data}=await api.get('/projects',{params:{search:keyword.value || props.query || ''}});if(ticket!==generation)return;projects.value=data;if(props.initialProject && !initialApplied && !props.references.length){initialApplied=true;const p=projects.value.find(p=>p.id===props.initialProject);if(p)emit('update',[{id:p.id,title:p.title}]);else if(!keyword.value){try{const {data}=await api.get(`/projects/${props.initialProject}`);emit('update',[{id:data.id,title:data.title}])}catch{error.value='所选项目不可访问'}}}}catch{error.value='项目列表加载失败'}}
function select(id){if(props.disabled || props.references.length>=3)return;const p=projects.value.find(p=>p.id===id);if(p){emit('update',[...props.references,{id:p.id,title:p.title}]);open.value=false;emit('close')}}
watch(keyword,load)
watch(()=>props.query,()=>{if(props.query!==null)load()})
defineExpose({openMenu:()=>{if(!props.disabled){open.value=!open.value;if(open.value)load()}}})
onMounted(load)
</script>
<style scoped>
.project-picker{font-size:12px}.project-refs{display:flex;align-items:center;flex-wrap:wrap;gap:6px;padding:4px 8px}.project-chip{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:7px;color:var(--primary);background:var(--primary-light);border:1px solid var(--border)}.project-chip button{border:0;background:transparent;color:inherit;cursor:pointer;font-size:15px}.project-menu{padding:12px;margin:0 8px 8px;border:1px solid var(--border);border-radius:10px;background:var(--surface-panel);display:flex;flex-wrap:wrap;gap:8px}.project-menu .hint{width:100%;margin:0;color:var(--text2)}.project-menu :deep(.search-select){flex:1;min-width:200px}
</style>
