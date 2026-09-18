<template>
  <div class="access-admin">
    <PageHeader><span class="admin-badge"><ShieldCheck :size="16" /> {{ auth.user?.is_superadmin ? '超级管理员' : '授权管理员' }}</span></PageHeader>
    <nav class="access-tabs" aria-label="访问管理分类"><button v-for="t in tabs" :key="t.key" :class="{active:tab===t.key}" @click="tab=t.key">{{ t.name }}</button></nav>
    <div v-if="error" class="notice error" role="alert">{{ error }}<button @click="error=''">×</button></div><div v-if="success" class="notice success">{{ success }}</div>
    <div v-if="loading" class="loading">正在加载…</div>
    <section v-else class="panel">
      <OrganizationAdmin v-if="tab==='organization'" />
      <template v-if="tab==='users'">
        <div class="toolbar"><div><h2>用户管理 <span>{{ users.length }}</span></h2><p>账号停用后，已有登录会话立即失效。</p></div><div class="actions"><input v-model="search" placeholder="搜索姓名或账号" /><button class="btn btn-primary" @click="openUser()"><Plus :size="16" /> 新建用户</button></div></div>
        <table><thead><tr><th>用户</th><th>联系方式</th><th>来源</th><th>状态</th><th>最近登录</th><th>操作</th></tr></thead><tbody><tr v-for="u in filteredUsers" :key="u.id"><td><strong>{{ u.display_name }}</strong><small>{{ u.username }}{{ u.is_superadmin?' · 超管':'' }}</small></td><td>{{ u.email || u.phone || '—' }}</td><td>{{ u.source==='local'?'本地账号':u.source }}</td><td><span :class="['status',u.status]">{{ u.status==='active'?'正常':'已停用' }}</span><small v-if="u.must_change_password">待修改初始密码</small></td><td>{{ date(u.last_login_at) }}</td><td class="row-actions"><button @click="openUser(u)">编辑</button><button @click="openReset(u)">重置密码</button><button v-if="can('roles.manage')" @click="openSystemRoles(u)">系统角色</button><button v-if="can('members.manage')" @click="assignUser(u)">空间授权</button><button v-if="!u.is_superadmin && u.id!==auth.user.id" @click="toggleUser(u)">{{ u.status==='active'?'停用':'启用' }}</button></td></tr></tbody></table><div v-if="!filteredUsers.length" class="empty">没有匹配的用户。</div>
      </template>
      <template v-if="tab==='members'">
        <div class="toolbar"><div><h2>当前空间成员</h2><p>先加入空间，再分配 Agent。移除成员会撤销该空间全部授权。</p></div><button class="btn btn-primary" @click="openMember()"><UserPlus :size="16" /> 添加成员</button></div>
        <table><thead><tr><th>用户</th><th>空间角色</th><th>可用 Agent</th><th>操作</th></tr></thead><tbody><tr v-for="m in members" :key="m.id"><td><strong>{{ m.display_name }}</strong><small>{{ m.username }}</small></td><td>{{ roleNames(m.role_ids) }}</td><td>{{ m.all_agents?'全部已发布 Agent（含未来新增）':m.agent_ids.length+' 个指定 Agent' }}</td><td class="row-actions"><button @click="openMember(m)">编辑授权</button><button class="danger" @click="removeMember(m)">移除</button></td></tr></tbody></table><div v-if="!members.length" class="empty">当前空间暂无成员。</div>
      </template>
      <template v-if="tab==='roles'">
        <div class="toolbar"><div><h2>角色管理</h2><p>角色定义操作权限，分配时限定系统或工作空间范围。</p></div><button v-if="auth.user.is_superadmin" class="btn btn-primary" @click="openRole()"><Plus :size="16" /> 新建角色</button></div>
        <div class="role-grid"><article v-for="r in roles" :key="r.id"><div class="role-heading"><h3>{{ r.name }}</h3><span class="pill">{{ r.builtin?'内置':'自定义' }}</span></div><p>{{ r.scope==='system'?'系统级':'工作空间级' }} · {{ r.permissions.length }} 项权限</p><div class="chips"><span v-for="p in r.permissions" :key="p">{{ permissionName(p) }}</span></div><div class="row-actions" v-if="!r.builtin && auth.user.is_superadmin"><button @click="openRole(r)">编辑</button><button class="danger" @click="removeRole(r)">删除</button></div></article></div>
      </template>
      <template v-if="tab==='resources'"><div class="toolbar"><div><h2>功能资源目录</h2><p>权限编码与后端操作绑定，通过角色分配。业务资源在空间成员授权中选择。</p></div></div><table><thead><tr><th>功能资源</th><th>权限编码</th><th>范围</th></tr></thead><tbody><tr v-for="p in permissions" :key="p.code"><td>{{p.name}}</td><td><code>{{p.code}}</code></td><td>{{p.scope==='system'?'系统':'工作空间'}}</td></tr></tbody></table></template>
      <template v-if="tab==='audit'"><div class="toolbar"><div><h2>安全审计</h2><p>最近 200 条登录、账号变更和授权操作，不记录密码。</p></div><button @click="load">刷新</button></div><table><thead><tr><th>时间</th><th>操作人</th><th>操作</th><th>目标</th><th>详情</th></tr></thead><tbody><tr v-for="a in logs" :key="a.id"><td>{{date(a.created_at)}}</td><td>{{a.actor||'未登录'}}</td><td>{{a.action}}</td><td class="mono">{{a.target||'—'}}</td><td><details><summary>查看</summary><pre>{{JSON.stringify(a.detail,null,2)}}</pre></details></td></tr></tbody></table></template>
      <template v-if="tab==='identity'"><div class="toolbar"><div><h2>第三方身份预留</h2><p>登记身份来源与字段映射。实际单点登录和同步适配尚未启用。</p></div><button class="btn btn-primary" @click="openProvider()"><Plus :size="16" /> 登记来源</button></div><table><thead><tr><th>系统</th><th>编码</th><th>协议</th><th>身份地址</th><th>状态</th></tr></thead><tbody><tr v-for="p in providers" :key="p.id"><td>{{p.name}}</td><td>{{p.code}}</td><td>{{p.protocol}}</td><td>{{p.issuer||'—'}}</td><td><span class="pill">待接入</span></td></tr></tbody></table><div v-if="!providers.length" class="empty">尚未登记第三方身份来源。</div></template>
    </section>
    <div v-if="dialog" class="dialog-backdrop" @click.self="!saving&&(dialog='')"><form class="dialog" @submit.prevent="save"><header><h2>{{ dialogTitle }}</h2><button type="button" :disabled="saving" @click="dialog=''">×</button></header><div class="dialog-content">
      <template v-if="dialog==='user'"><label>登录账号<input v-model.trim="form.username" :disabled="!!form.id" required pattern="[a-zA-Z0-9_.-]{3,80}" placeholder="3–80 位字母、数字、下划线" /></label><label>姓名<input v-model.trim="form.display_name" required maxlength="160" /></label><label v-if="!form.id">初始密码<input v-model="form.password" type="password" required minlength="8" maxlength="128" autocomplete="new-password" /><small>至少 8 位；首次登录强制修改。</small></label><label>邮箱<input v-model.trim="form.email" type="email" /></label><label>手机号<input v-model.trim="form.phone" maxlength="40" /></label></template>
      <template v-if="dialog==='reset'"><p>为 {{form.display_name}} 设置临时密码，将注销该用户所有会话。</p><label>临时密码<input v-model="form.password" type="password" required minlength="8" maxlength="128" autocomplete="new-password" /></label><small>至少 8 位。用户下次登录必须修改。</small></template>
      <template v-if="dialog==='role'"><label>角色名称<input v-model.trim="form.name" required maxlength="120" /></label><label>角色编码<input v-model.trim="form.code" :disabled="!!form.id" pattern="[a-z][a-z0-9_]{2,79}" required /></label><label>角色范围<SearchSelect v-model="form.scope" :disabled="!!form.id" :options="roleScopeOptions" @change="form.permissions=[]" /></label><div class="check-grid"><label v-for="p in permissions.filter(p=>p.scope===form.scope)" :key="p.code" class="check"><input type="checkbox" v-model="form.permissions" :value="p.code" />{{p.name}}</label></div></template>
      <template v-if="dialog==='systemRoles'"><p>{{form.display_name}} 的系统角色</p><div class="check-grid"><label v-for="r in roles.filter(r=>r.scope==='system')" :key="r.id" class="check"><input type="checkbox" v-model="form.role_ids" :value="r.id" />{{r.name}}</label></div></template>
      <template v-if="dialog==='member'"><label>用户<SearchSelect v-model="form.user_id" :disabled="!!form.id" placeholder="选择已有用户" :options="memberUserOptions" /></label><p class="field-title">空间角色（可多选）</p><div class="check-grid"><label v-for="r in roles.filter(r=>r.scope==='workspace')" :key="r.id" class="check"><input type="checkbox" v-model="form.role_ids" :value="r.id" />{{r.name}}</label></div><p class="field-title">可用 Agent</p><label class="check"><input type="checkbox" v-model="form.all_agents" />全部已发布 Agent，自动包含未来发布的 Agent</label><div v-if="!form.all_agents" class="check-grid agents-check"><label v-for="a in agentOptions" :key="a.id" class="check"><input type="checkbox" v-model="form.agent_ids" :value="a.id" />{{a.name}}<small v-if="a.status!=='active'">未发布</small></label><p v-if="!agentOptions.length">当前没有可分配的 Agent。</p></div><small>Agent 使用权限需要空间角色包含“使用获授权的已发布 Agent”。</small></template>
      <template v-if="dialog==='provider'"><label>来源名称<input v-model.trim="form.name" required /></label><label>唯一编码<input v-model.trim="form.code" required pattern="[a-z][a-z0-9_]{2,79}" /></label><label>协议<SearchSelect v-model="form.protocol" :options="providerProtocolOptions" /></label><label>身份提供方地址<input v-model.trim="form.issuer" type="url" /></label><label>字段映射（JSON）<textarea v-model="form.mapping" rows="4" placeholder='{"display_name":"name"}' /></label></template>
      <div v-if="dialogError" class="notice error" role="alert">{{dialogError}}</div>
    </div><footer><button type="button" :disabled="saving" @click="dialog=''">取消</button><button type="submit" class="btn btn-primary" :disabled="saving">{{saving?'保存中…':'保存'}}</button></footer></form></div>
  </div>
</template>
<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ShieldCheck, Plus, UserPlus } from 'lucide-vue-next'
import api from '../api'
import OrganizationAdmin from '../components/OrganizationAdmin.vue'
import { auth, can, refreshAuth } from '../auth'
const tab=ref(''), loading=ref(false), saving=ref(false), error=ref(''), success=ref(''), dialog=ref(''), dialogError=ref(''), form=ref({}), search=ref('')
const users=ref([]), members=ref([]), roles=ref([]), permissions=ref([]), logs=ref([]), providers=ref([]), userOptions=ref([]), agentOptions=ref([])
const roleScopeOptions=[{value:'workspace',label:'工作空间'},{value:'system',label:'系统'}]
const providerProtocolOptions=[{value:'oidc',label:'OIDC'},{value:'dingtalk',label:'钉钉'},{value:'custom',label:'自定义'}]
const tabs=computed(()=>[
 {key:'users',name:'用户',permission:'users.manage'}, {key:'members',name:'空间成员',permission:'members.manage'},
 {key:'organization',name:'组织与职责',permission:'members.manage'},
 {key:'roles',name:'角色',permission:'roles.manage'}, {key:'resources',name:'资源目录',permission:'roles.manage'},
 {key:'audit',name:'审计日志',permission:'audit.read'}, {key:'identity',name:'第三方身份',permission:'identity.manage'}
].filter(t=>can(t.permission)))
const filteredUsers=computed(()=>users.value.filter(u=>(u.username+' '+u.display_name).toLowerCase().includes(search.value.toLowerCase())))
const memberUserOptions=computed(()=>[{value:'',label:'选择已有用户',disabled:true},...userOptions.value.map(u=>({value:u.id,label:u.display_name+'（'+u.username+'）'}))])
const dialogTitle=computed(()=>({user:form.value.id?'编辑用户':'新建用户',reset:'重置密码',role:form.value.id?'编辑角色':'新建角色',member:'空间成员与 Agent 授权',systemRoles:'分配系统角色',provider:'登记身份来源'}[dialog.value]))
const ws=()=>auth.workspaceId
const date=v=>v?new Date(v).toLocaleString('zh-CN',{hour12:false}):'—'
const permissionName=code=>permissions.value.find(p=>p.code===code)?.name||code
const roleNames=ids=>roles.value.filter(r=>ids.includes(r.id)).map(r=>r.name).join('、')||'未分配角色'
const message=e=>typeof e.response?.data?.detail==='string'?e.response.data.detail:(e.response?.status===422?'请检查输入格式和必填项':e.message||'操作失败')
async function load(){loading.value=true;error.value='';try{
 if(!tabs.value.some(t=>t.key===tab.value))tab.value=tabs.value[0]?.key||''
 if(tab.value==='users'){users.value=(await api.get('/admin/users')).data;roles.value=(await api.get('/admin/roles')).data}
 if(tab.value==='members'){
  const result=await Promise.all([api.get(`/admin/workspaces/${ws()}/members`),api.get('/admin/roles'),api.get('/admin/user-options'),api.get(`/admin/workspaces/${ws()}/agents`)])
  ;[members.value,roles.value,userOptions.value,agentOptions.value]=result.map(r=>r.data)
 }
 if(['roles','resources'].includes(tab.value)){const result=await Promise.all([api.get('/admin/roles'),api.get('/admin/permissions')]);[roles.value,permissions.value]=result.map(r=>r.data)}
 if(tab.value==='audit')logs.value=(await api.get('/admin/audit')).data
 if(tab.value==='identity')providers.value=(await api.get('/admin/identity-providers')).data
}catch(e){error.value=message(e)}finally{loading.value=false}}
function open(type,data){dialogError.value='';form.value=data;dialog.value=type}
function openUser(u){open('user',u?{...u}:{username:'',display_name:'',password:'',email:'',phone:''})}
function openReset(u){open('reset',{id:u.id,display_name:u.display_name,password:''})}
function openRole(r){open('role',r?{...r,permissions:[...r.permissions]}:{name:'',code:'',scope:'workspace',permissions:[]})}
function openMember(m){open('member',m?{...m,role_ids:[...m.role_ids],agent_ids:[...m.agent_ids]}:{user_id:'',role_ids:[],agent_ids:[],all_agents:false})}
function openProvider(){open('provider',{code:'',name:'',protocol:'oidc',issuer:'',mapping:'{}'})}
async function openSystemRoles(u){try{const {data}=await api.get(`/admin/users/${u.id}/system-roles`);open('systemRoles',{id:u.id,display_name:u.display_name,role_ids:data})}catch(e){error.value=message(e)}}
async function assignUser(u){tab.value='members';await load();if(error.value)return;const existing=members.value.find(m=>m.user_id===u.id);openMember(existing);if(!existing)form.value.user_id=u.id}
async function changed(text){success.value=text;await refreshAuth();await load();setTimeout(()=>{success.value=''},4000)}
async function toggleUser(u){if(u.status==='active'&&!confirm(`停用 ${u.display_name} 并注销其所有会话？`))return;try{await api.patch(`/admin/users/${u.id}`,{status:u.status==='active'?'disabled':'active'});await changed('账号状态已更新')}catch(e){error.value=message(e)}}
async function removeMember(m){if(!confirm(`移除 ${m.display_name}？该空间内所有角色和 Agent 授权将一起撤销。`))return;try{await api.delete(`/admin/workspaces/${ws()}/members/${m.user_id}`);await changed('成员及授权已移除')}catch(e){error.value=message(e)}}
async function removeRole(r){if(!confirm(`删除角色 ${r.name}？`))return;try{await api.delete(`/admin/roles/${r.id}`);await changed('角色已删除')}catch(e){error.value=message(e)}}
async function save(){saving.value=true;dialogError.value='';const f=form.value;try{
 if(dialog.value==='user'){const data={display_name:f.display_name,email:f.email||null,phone:f.phone||null};if(f.id)await api.patch(`/admin/users/${f.id}`,data);else await api.post('/admin/users',{...data,username:f.username,password:f.password})}
 if(dialog.value==='reset')await api.post(`/admin/users/${f.id}/reset-password`,{password:f.password})
 if(dialog.value==='role'){const data={code:f.code,name:f.name,scope:f.scope,permissions:f.permissions};if(f.id)await api.put(`/admin/roles/${f.id}`,data);else await api.post('/admin/roles',data)}
 if(dialog.value==='systemRoles')await api.put(`/admin/users/${f.id}/system-roles`,{role_ids:f.role_ids})
 if(dialog.value==='member')await api.put(`/admin/workspaces/${ws()}/members`,{user_id:f.user_id,role_ids:f.role_ids,agent_ids:f.agent_ids,all_agents:f.all_agents})
 if(dialog.value==='provider')await api.post('/admin/identity-providers',{code:f.code,name:f.name,protocol:f.protocol,issuer:f.issuer||null,field_mapping:JSON.parse(f.mapping)})
 dialog.value='';await changed('已保存')
}catch(e){dialogError.value=message(e)}finally{saving.value=false}}
watch(tab,load)
onMounted(()=>{tab.value=tabs.value[0]?.key||''})
</script>
<style scoped>
.access-admin{max-width:1440px;margin:8px auto}.admin-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px}.overline{font-size:10px;letter-spacing:2px;color:var(--primary);font-weight:600}h1{font-size:28px;margin:10px 0}header p:not(.overline),.toolbar p{font-size:13px;color:var(--text2);line-height:1.7}.admin-badge{display:flex;align-items:center;gap:8px;font-size:12px;background:var(--primary-light);color:var(--primary);padding:10px 14px;border-radius:24px}.access-tabs{display:flex;gap:24px;border-bottom:1px solid var(--border);margin-bottom:24px}.access-tabs button{padding:12px 0;border:0;border-bottom:2px solid transparent;background:none;border-radius:0;color:var(--text2)}.access-tabs .active{border-bottom-color:var(--primary);color:var(--primary);font-weight:600}.panel{background:white;border:1px solid var(--border);border-radius:14px;overflow:auto;min-height:300px}.toolbar{display:flex;align-items:center;justify-content:space-between;padding:24px;gap:20px}.toolbar h2{font-size:17px;margin-bottom:6px}.toolbar h2 span{font-size:12px;color:var(--text3);margin-left:8px}.actions{display:flex;gap:12px}button{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:9px 14px;border:1px solid var(--border);border-radius:8px;background:#fff;cursor:pointer;color:var(--text2);font-size:13px}button:disabled{opacity:.5;cursor:wait}.primary{background:var(--primary);color:white;border-color:var(--primary)}input,select,textarea{padding:10px 12px;border:1px solid var(--border);border-radius:8px;font:inherit;font-size:13px;outline:none;background:#fff}input:focus,select:focus,textarea:focus{border-color:var(--primary)}table{width:100%;border-collapse:collapse;font-size:13px;text-align:left}th{background:var(--surface2);color:var(--text2);font-weight:500;padding:13px 24px;white-space:nowrap}td{padding:18px 24px;border-top:1px solid var(--border);vertical-align:middle}td strong{font-weight:550}small{display:block;font-size:11px;color:var(--text3);margin-top:6px;line-height:1.6}.status,.pill{font-size:11px;padding:4px 8px;border-radius:5px;background:var(--surface2);color:var(--text2)}.status.active{background:#ecfdf5;color:#047857}.status.disabled{background:#fff1f2;color:#be123c}.row-actions{white-space:nowrap}.row-actions button{border:0;background:transparent;padding:4px 7px;color:var(--primary);font-size:12px}.row-actions .danger{color:var(--danger)}.notice{padding:12px 16px;border-radius:8px;font-size:13px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:center}.notice button{padding:0 4px;border:0;background:none}.error{background:#fff1f2;color:#be123c}.success{background:#ecfdf5;color:#047857}.loading,.empty{padding:70px;text-align:center;font-size:14px;color:var(--text3)}.role-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;padding:0 24px 24px}.role-grid article{border:1px solid var(--border);border-radius:10px;padding:20px}.role-heading{display:flex;justify-content:space-between;gap:12px}.role-heading h3{font-size:15px}.role-grid p{font-size:12px;color:var(--text3);margin:12px 0}.chips{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0}.chips span{font-size:11px;padding:5px 7px;background:var(--surface2);border-radius:4px;color:var(--text2)}code,.mono{font-size:11px}.mono{max-width:170px;overflow-wrap:anywhere}pre{max-width:360px;white-space:pre-wrap;font-size:11px}.dialog-backdrop{position:fixed;inset:0;background:#11182766;display:flex;align-items:center;justify-content:center;z-index:2000;padding:28px}.dialog{width:600px;max-width:100%;max-height:90vh;background:#fff;border-radius:16px;display:flex;flex-direction:column;box-shadow:0 20px 70px #0003}.dialog header{display:flex;align-items:center;justify-content:space-between;padding:22px 26px;border-bottom:1px solid var(--border)}.dialog h2{font-size:18px}.dialog header button{border:0;font-size:22px;padding:0 4px}.dialog-content{padding:8px 26px 24px;overflow:auto}.dialog-content>label{display:block;font-size:13px;font-weight:500;margin-top:18px}.dialog-content>label>input,.dialog-content>label>select,.dialog-content>label>textarea{display:block;width:100%;margin-top:8px}.dialog-content p{font-size:13px;line-height:1.7;margin-top:16px;color:var(--text2)}.check-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}.check{display:flex!important;align-items:center;gap:9px;font-size:12px!important;font-weight:400!important;line-height:1.5}.check input{width:15px!important;height:15px;margin:0!important;accent-color:var(--primary)}.check small{margin:0}.agents-check{border:1px solid var(--border);padding:14px;border-radius:8px;max-height:240px;overflow:auto}.field-title{font-weight:600}.dialog footer{padding:18px 26px;display:flex;gap:10px;justify-content:flex-end;border-top:1px solid var(--border)}@media(max-width:900px){.toolbar{align-items:flex-start;flex-direction:column}.access-tabs{gap:16px}.admin-badge{display:none}.check-grid{grid-template-columns:1fr}}
/* Theme-aware overrides for the access pages and all create/edit dialogs. */
.panel{background:var(--surface);color:var(--text)}
button{background:var(--surface);color:var(--text2)}
button:hover:not(:disabled){background:var(--surface2);color:var(--text)}
.primary,.btn-primary{background:var(--primary);background-image:var(--theme-gradient,none);color:var(--primary-text,#fff);border-color:var(--primary)}
.primary:hover:not(:disabled),.btn-primary:hover:not(:disabled){background:var(--primary-hover);background-image:var(--theme-gradient-hover,none);color:var(--primary-text,#fff)}
input,select,textarea{background:var(--surface);color:var(--text)}
input::placeholder,textarea::placeholder{color:var(--text3)}
input:disabled,select:disabled,textarea:disabled{background:var(--surface2);color:var(--text3)}
.dialog{background:var(--surface);color:var(--text);border:1px solid var(--border);box-shadow:0 20px 70px #0006}
.dialog-backdrop{background:#080b12a6;backdrop-filter:blur(3px)}
.role-grid article,.agents-check{background:var(--surface)}
.dialog header button,.notice button,.row-actions button,.access-tabs button{background:transparent}
.status.active{background:var(--success-bg);color:var(--success)}
.status.disabled{background:var(--danger-bg);color:var(--danger)}
.error{background:var(--danger-bg);color:var(--danger)}
.success{background:var(--success-bg);color:var(--success)}
.notice button:hover:not(:disabled),.dialog header button:hover:not(:disabled){background:var(--surface2)}
.dialog footer button[type="button"]{background:var(--surface);color:var(--text2)}

/* Page-local underline tabs: do not inherit raised material-button treatments. */
.access-admin .access-tabs{display:flex;gap:8px;overflow-x:auto;max-width:100%;border-bottom:1px solid var(--border);margin-bottom:24px;scrollbar-width:thin}
.access-admin .access-tabs>button{position:relative;flex:0 0 auto;min-height:44px;padding:10px 14px;border:0;border-radius:8px 8px 0 0;background:transparent;box-shadow:none;color:var(--text2);white-space:nowrap;font-weight:500;backdrop-filter:none;transform:none}
.access-admin .access-tabs>button:hover{background:var(--surface2);color:var(--text)}
.access-admin .access-tabs>button.active{background:transparent;color:var(--navigation-color,var(--primary));font-weight:600;box-shadow:none}
.access-admin .access-tabs>button.active::after{content:"";position:absolute;left:14px;right:14px;bottom:0;height:2px;border-radius:2px;background:currentColor}
.access-admin .access-tabs>button:focus-visible{outline:2px solid var(--navigation-color,var(--primary));outline-offset:-3px}
@media(max-width:640px){.access-admin .access-tabs{gap:4px}.access-admin .access-tabs>button{padding-inline:12px}}
</style>
