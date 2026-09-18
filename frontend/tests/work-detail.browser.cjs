// Run after npm run build, with Playwright available (or PLAYWRIGHT_MODULE set).
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
(async () => {
const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
const page = await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror', e=>errors.push(e.message));
const root=path.resolve(__dirname, '../../src/agentdevstu/web/static/dist');
let memoryCalls=0, logs=[], activities=[], failedOnce=false; let workRows = [{id:'1',title:'9月目标分解表制作',goal:'将430台月目标拆解到周、城市、门店颗粒度',priority:'P2',status:'completed',assignee_name:'阿木',due_at:'2026-09-12T17:39:00',source_type:'agent_collaboration',source_label:'Agent 对话'}, {id:'2',title:'跨城市门店销售目标执行跟踪与复盘报告制作',goal:'覆盖各区域门店销售目标执行情况，整理偏差与改进建议。'.repeat(4),priority:'P1',status:'in_progress',assignee_name:'负责人名字很长的情况',source_type:'manual',source_label:'人工创建'}], listReads = 0, releaseList = null;
workRows[0]={...workRows[0],priority:'P0',deliverable_requirement:'提交按周、城市和门店分解的目标表。',creator_name:'李生',reviewer_name:'李生',permissions:{log:true,memory:true,knowledge:true},created_at:'2026-09-09T10:00:00'};
const permissions=['agent.use','agent.read','knowledge.manage','data.manage','config.manage','meeting.use'];
await page.route('http://tabs.local/**', async r=>{
 const u=new URL(r.request().url());
 if(u.pathname.startsWith('/api/')){
 let data=[];
 if(u.pathname==='/api/works/1/logs' && r.request().method()==='POST') {const p=r.request().postDataJSON();data={id:'log'+logs.length,action:'log',actor_name:'测试用户',created_at:new Date().toISOString(),data_json:{content:p.content,version:1},can_edit:true};logs.push(data);return r.fulfill({status:201,json:data});}
 else if(u.pathname.startsWith('/api/works/1/logs/') && r.request().method()==='PATCH') {const p=r.request().postDataJSON();const l=logs.find(e=>u.pathname.endsWith(e.id));l.data_json={...p,version:p.version+1,edited_at:new Date().toISOString()};data=l;}
 else if(u.pathname==='/api/works/1/activities') data=[...logs,...activities];
 else if(u.pathname==='/api/works/1/deliverables') data=[{id:'d1',type:'file',filename:'九月目标分解表.xlsx',created_at:'2026-09-09T12:00:00',metadata_json:{size:54321}},{id:'d2',type:'text',content:'已完成目标分解。'.repeat(120),created_at:'2026-09-09T12:00:00',metadata_json:{size:1000}}];
 else if(u.pathname==='/api/works/1/memory') {memoryCalls++;const p=r.request().postDataJSON();if(p.type==='focus' && !failedOnce){failedOnce=true;return r.fulfill({status:500,json:{detail:'模拟失败'}})}data={memory_id:'m'+memoryCalls};activities.push({id:data.memory_id,action:'memory',actor_name:'测试用户',data_json:p,created_at:new Date().toISOString()});}
 else if(u.pathname==='/api/auth/agents') data=[{id:'a1',name:'业务分析 Agent'}];
 else if(u.pathname==='/api/knowledge') data=[{id:'k1',name:'业务知识库'}];
 else if(u.pathname==='/api/auth/me') data={id:'test',display_name:'测试用户',username:'test',system_permissions:permissions,memberships:[{workspace_id:'w1',permissions},{workspace_id:'w2',permissions}]};
 else if(u.pathname==='/api/workspaces') data=[{id:'w1',name:'测试空间'},{id:'w2',name:'第二空间'}];
 else if(u.pathname==='/api/works/members') data=[{id:'owner',name:'负责人'},{id:'test',name:'测试用户'}];
 else if(u.pathname==='/api/works' && r.request().method()==='POST') {
   data={...r.request().postDataJSON(),id:`work-${workRows.length+1}`,permissions:{edit:true},status:'todo'};
   workRows.push(data);
 } else if(u.pathname==='/api/works') {listReads++; if (releaseList) await new Promise(resolve => { releaseList = resolve; }); data=workRows;}
 else if(/^\/api\/works\/[^/]+$/.test(u.pathname)) data=workRows.find(w=>u.pathname.endsWith('/'+w.id));
 return r.fulfill({json:data});
 }
 const file=u.pathname.startsWith('/static/dist/')?path.join(root,u.pathname.slice(13)):path.join(root,'index.html');
 await r.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
});


await page.goto('http://tabs.local/works/1');
await page.getByRole('heading',{name:'工作日志',exact:false}).waitFor();
await page.getByRole('button',{name:'＋ 写日志',exact:true}).click();
await page.getByLabel('记录工作进展').fill('完成第一轮目标核对');
await page.getByRole('button',{name:'保存日志',exact:true}).click();
await page.locator('.log-entry').getByText('完成第一轮目标核对',{exact:true}).waitFor();
await page.locator('.log-entry').getByRole('button',{name:'编辑',exact:true}).click();
await page.getByLabel('编辑日志',{exact:true}).fill('已完成全部门店目标核对');
await page.getByRole('button',{name:'保存日志',exact:true}).click();
await page.locator('.log-entry').getByText('已完成全部门店目标核对',{exact:true}).waitFor();
await page.reload();
await page.locator('.log-entry').getByText('已完成全部门店目标核对',{exact:true}).waitFor();
await page.getByRole('button',{name:'＋ 添加一条',exact:true}).click();
for(let i=0;i<2;i++) {
const entry=page.locator('.memory-entry').nth(i);
await entry.getByLabel('目标 Agent').selectOption('a1');
await entry.getByLabel('记忆类型').selectOption(i?'focus':'semantic');
await entry.getByLabel('记忆内容').fill(i?'持续关注门店周达成率':'9月目标为430台');
}
await page.getByRole('button',{name:'保存 2 条记忆',exact:true}).click();
await page.getByText(/已保存 1 条，其余内容已保留/).waitFor();
assert.equal(await page.locator('.memory-entry').nth(1).getByLabel('记忆内容').inputValue(),'持续关注门店周达成率');
await page.getByRole('button',{name:'保存 1 条记忆',exact:true}).click();
await page.locator('.saved-memories article').nth(1).waitFor();
assert.equal(memoryCalls,3);
assert.equal(activities.length,2);
for(const [width,scheme] of [[1440,'light'],[1440,'dark'],[390,'dark']]) {
await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme:scheme});
await page.locator('.overview-panel').scrollIntoViewIfNeeded();
await page.screenshot({path:`/tmp/work-detail-${width}-${scheme}.png`,fullPage:true});
const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
assert.equal(overflow,false);
}
await page.locator('.delivery-preview summary').click();
assert.equal(await page.locator('.delivery-preview p').isVisible(),true);
await page.goto('http://tabs.local/works');
await page.locator('.summary-priority.P0').waitFor();
await page.screenshot({path:'/tmp/work-p0-dark.png'});
assert.deepEqual(errors,[]);
console.log('PASS: log create/edit/reload, multi-memory focus + partial failure retry, delivery preview, mobile and dark layout');
await browser.close();
})();
