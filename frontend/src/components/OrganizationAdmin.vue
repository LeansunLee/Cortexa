<template>
  <div class="organization-admin">
    <div class="org-toolbar"><button class="btn btn-primary" @click="editUnit()">新增部门</button><button class="btn" @click="load">刷新</button></div>
    <p v-if="error" role="alert" class="org-error">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="loading">正在加载组织与职责…</p>
    <div v-else class="org-layout">
      <nav aria-label="组织树" class="org-tree">
        <button :class="{selected:selected==='all'}" @click="selected='all'">全部成员（{{ members.length }}）</button>
        <button :class="{selected:selected==='none'}" @click="selected='none'">未分配部门</button>
        <div v-for="u in tree" :key="u.id" class="org-node" :style="{paddingLeft:`${u.depth*14}px`}">
          <button :class="{selected:selected===u.id}" @click="selected=u.id">{{ u.name }}{{ u.status==='disabled'?'（停用）':'' }}<small v-if="u.manager_user_id">负责人：{{ memberName(u.manager_user_id) }}</small></button>
          <button :aria-label="`编辑${u.name}`" @click="editUnit(u)">编辑</button>
        </div>
        <p v-if="!units.length" class="org-hint">尚无部门，可先新增部门再维护成员职责。</p>
      </nav>
      <section class="org-members" aria-label="部门成员">
        <label>搜索成员<input v-model.trim="search" placeholder="姓名、岗位、职责标签" /></label>
        <p class="org-hint">{{ visibleMembers.length }} 位有效成员 · 部门与职责用于协作推荐，权限仍由空间角色管理。</p>
        <article v-for="m in visibleMembers" :key="m.user_id" class="org-member">
          <div><strong>{{ m.display_name }}</strong><span>{{ m.org_unit_name || '未分配部门' }} · {{ m.position_title || '未填写岗位' }}</span><p>{{ m.responsibility || '暂无职责描述' }}</p><p v-if="m.coverage_scope">负责范围：{{ m.coverage_scope }}</p><div class="org-tags"><span v-for="t in m.responsibility_tags" :key="t">{{ t }}</span></div></div>
          <button class="btn" @click="editProfile(m)">编辑职责</button>
        </article>
        <p v-if="!visibleMembers.length" class="org-hint">暂无符合条件的成员。</p>
      </section>
    </div>
    <Teleport v-if="pageTabActive && dialog" to="body">
      <div class="org-overlay" @click.self="!saving && (dialog='')">
        <form class="org-dialog" role="dialog" aria-modal="true" aria-labelledby="org-dialog-title" @submit.prevent="save" @keydown.esc="!saving && (dialog='')">
          <h2 id="org-dialog-title">{{ dialog==='unit' ? (form.id?'编辑部门':'新增部门') : `${form.display_name} · 成员职责` }}</h2>
          <template v-if="dialog==='unit'">
            <label>部门名称<input v-model.trim="form.name" required maxlength="120" autofocus /></label>
            <label>组织编码<input v-model.trim="form.code" maxlength="80" placeholder="可选，空间内唯一" /></label>
            <label>上级部门<SearchSelect aria-label="上级部门" v-model="form.parent_id" :options="parentOptions" /></label>
            <label>类型<SearchSelect aria-label="类型" v-model="form.type" :options="[{value:'department',label:'部门'},{value:'team',label:'小组'}]" /></label>
            <label>部门负责人<SearchSelect aria-label="部门负责人" v-model="form.manager_user_id" :options="managerOptions" /></label>
            <label>排序<input v-model.number="form.sort_order" type="number" min="0" max="100000" required /></label>
            <label>状态<SearchSelect aria-label="状态" v-model="form.status" :options="[{value:'active',label:'有效'},{value:'disabled',label:'停用'}]" /></label>
          </template>
          <template v-else>
            <label>所属部门<SearchSelect aria-label="所属部门" v-model="form.org_unit_id" :options="unitOptions" /></label>
            <label>岗位名称<input v-model.trim="form.position_title" maxlength="120" /></label>
            <label>职责描述<textarea v-model.trim="form.responsibility" rows="4" maxlength="2000" /></label>
            <label>职责标签<input v-model="form.tagsText" placeholder="用逗号分隔，如：前端、Vue、测试" /><small>最多 30 个，每个不超过 40 字</small></label>
            <label>负责范围<textarea v-model.trim="form.coverage_scope" rows="2" maxlength="1000" /></label>
          </template>
          <p v-if="dialogError" role="alert" class="org-error">{{ dialogError }}</p>
          <footer><button v-if="dialog==='unit' && form.id" type="button" class="btn" :disabled="saving" @click="removeUnit">删除部门</button><button type="button" class="btn" :disabled="saving" @click="dialog=''">取消</button><button class="btn btn-primary" :disabled="saving">{{ saving?'保存中…':'保存' }}</button></footer>
        </form>
      </div>
    </Teleport>
  </div>
</template>
<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import api from '../api'
import SearchSelect from './SearchSelect.vue'
const pageTabActive = inject('pageTabActive', true)
const units=ref([]), members=ref([]), selected=ref('all'), search=ref(''), loading=ref(false), saving=ref(false)
const error=ref(''), notice=ref(''), dialog=ref(''), dialogError=ref(''), form=ref({})
const message=e=>typeof e.response?.data?.detail==='string'?e.response.data.detail:'操作失败，请检查输入后重试'
const tree=computed(()=>{
 const out=[], seen=new Set()
 function visit(parent,depth){ for(const u of units.value.filter(x=>x.parent_id===parent)){if(seen.has(u.id))continue;seen.add(u.id);out.push({...u,depth});visit(u.id,depth+1)} }
 visit(null,0);return out
})
const visibleMembers=computed(()=>members.value.filter(m=>(selected.value==='all'||(selected.value==='none'?!m.org_unit_id:m.org_unit_id===selected.value)) && `${m.display_name} ${m.position_title} ${m.responsibility_tags.join(' ')}`.toLowerCase().includes(search.value.toLowerCase())))
const memberName=id=>members.value.find(m=>m.user_id===id)?.display_name || '成员已离开或停用'
const unitOptions=computed(()=>[{value:null,label:'未分配部门'},...tree.value.filter(u=>u.status==='active').map(u=>({value:u.id,label:'　'.repeat(u.depth)+u.name}))])
const parentOptions=computed(()=>{
 const blocked=new Set([form.value.id]);let changed=true
 while(changed){changed=false;for(const u of units.value)if(blocked.has(u.parent_id)&&!blocked.has(u.id)){blocked.add(u.id);changed=true}}
 return [{value:null,label:'无（顶层部门）'},...tree.value.filter(u=>!blocked.has(u.id)).map(u=>({value:u.id,label:'　'.repeat(u.depth)+u.name}))]
})
const managerOptions=computed(()=>[{value:null,label:'暂不设置'},...members.value.map(m=>({value:m.user_id,label:m.display_name}))])
async function load(){loading.value=true;error.value='';try{const result=await Promise.all([api.get('/organization/units'),api.get('/organization/members')]);[units.value,members.value]=result.map(r=>r.data)}catch(e){error.value=message(e)}finally{loading.value=false}}
function editUnit(u){dialogError.value='';notice.value='';form.value=u?{...u}:{name:'',code:'',parent_id:selected.value!=='all'&&selected.value!=='none'?selected.value:null,type:'department',manager_user_id:null,sort_order:0,status:'active'};dialog.value='unit'}
function editProfile(m){dialogError.value='';notice.value='';form.value={...m,tagsText:m.responsibility_tags.join('、')};dialog.value='profile'}
async function save(){if(saving.value)return;saving.value=true;dialogError.value='';try{
 const f=form.value
 if(dialog.value==='unit') {const data=Object.fromEntries(['name','code','parent_id','type','manager_user_id','sort_order','status'].map(k=>[k,f[k]]));if(f.id)await api.put(`/organization/units/${f.id}`,data);else await api.post('/organization/units',data)}
 else await api.put(`/organization/members/${f.user_id}`,{org_unit_id:f.org_unit_id,position_title:f.position_title,responsibility:f.responsibility,responsibility_tags:f.tagsText.split(/[,，、;；\n]/).map(t=>t.trim()).filter(Boolean),coverage_scope:f.coverage_scope})
 dialog.value='';notice.value='已保存';await load()
}catch(e){dialogError.value=message(e)}finally{saving.value=false}}
async function removeUnit(){if(!confirm(`删除部门“${form.value.name}”？部门内有成员或下级部门时无法删除。`))return;saving.value=true;dialogError.value='';try{await api.delete(`/organization/units/${form.value.id}`);if(selected.value===form.value.id)selected.value='all';dialog.value='';notice.value='部门已删除';await load()}catch(e){dialogError.value=message(e)}finally{saving.value=false}}
onMounted(load)
</script>
<style scoped>
.organization-admin .btn:not(.btn-primary),.org-dialog .btn:not(.btn-primary){background:var(--surface);color:var(--text);border:1px solid var(--border)}
.organization-admin .btn:not(.btn-primary):hover,.org-dialog .btn:not(.btn-primary):hover{background:var(--surface2)}

.organization-admin{padding:20px;color:var(--text)}.org-toolbar{display:flex;gap:10px;margin-bottom:20px}.org-layout{display:grid;grid-template-columns:minmax(200px,28%) 1fr;gap:24px}.org-tree{border-right:1px solid var(--border);padding-right:14px;overflow:auto}.org-tree button{background:var(--surface);color:var(--text);border:1px solid var(--border);padding:10px;text-align:left;border-radius:var(--radius-sm);cursor:pointer}.org-tree>button{display:block;width:100%;margin-bottom:8px}.org-node{display:flex;gap:4px;margin-bottom:6px}.org-node>button:first-child{flex:1;min-width:0;overflow-wrap:anywhere}.org-tree .selected{background:var(--primary-light);color:var(--primary)}.org-node small{display:block;color:var(--text2);font-size:11px;margin-top:6px}.org-members{min-width:0}.org-members label,.org-dialog label{display:grid;gap:7px;font-size:13px}.org-member{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;border-top:1px solid var(--border);padding:18px 0}.org-member>div{min-width:0;overflow-wrap:anywhere}.org-member strong{display:block;margin-bottom:6px}.org-member span,.org-member p,.org-hint{font-size:13px;color:var(--text2);line-height:1.6;white-space:pre-wrap}.org-member button{flex-shrink:0}.org-tags{display:flex;gap:6px;flex-wrap:wrap}.org-tags span{padding:3px 7px;background:var(--surface2);border-radius:5px}.org-error{color:var(--danger)}.org-overlay{position:fixed;inset:0;z-index:2000;background:var(--overlay,#080b12a6);display:flex;align-items:center;justify-content:center;padding:20px}.org-dialog{background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:16px;padding:24px;width:min(540px,100%);max-height:90dvh;overflow:auto;display:grid;gap:14px}.org-dialog h2{margin:0;font-size:18px}.org-dialog input,.org-dialog textarea,.org-members input{box-sizing:border-box;width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);font:inherit}.org-dialog small{color:var(--text3)}.org-dialog footer{display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap}@media(max-width:700px){.organization-admin{padding:14px}.org-layout{grid-template-columns:1fr}.org-tree{border-right:0;border-bottom:1px solid var(--border);max-height:240px;padding-bottom:14px}.org-member{flex-wrap:wrap}}
</style>
