// Uses built assets and isolated API responses; never writes business conversations.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({headless:true, channel:'chrome'});
 try {
  const page = await browser.newPage({viewport:{width:1360,height:900}});
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  const root=path.resolve(__dirname,'../../src/cortexa/web/static/dist');
  const origin=process.env.LIVE_ORIGIN || 'http://memory.local'; let fail=true; let reads=0;
  const refs=[{type:'memory',name:'记忆 · 华东销售',memory_id:'mem1'},{type:'memory',name:'记忆 2',memory_id:'mem2'},{type:'memory',name:'旧记忆'}];
  await page.route(origin+'/**', async route=>{
   const u=new URL(route.request().url()); let data=[];
   if(u.pathname.startsWith('/api/')) {
    if(u.pathname==='/api/auth/me') data={id:'test',display_name:'测试用户',system_permissions:[],memberships:[{workspace_id:'ws',permissions:['agent.use','agent.read']}]};
    else if(u.pathname==='/api/workspaces') data=[{id:'ws',name:'测试空间'}];
    else if(u.pathname==='/api/auth/agents' || u.pathname==='/api/collaboration/agents') data=[{id:'main',name:'销售部',agent_type:'llm',status:'active'}];
    else if(u.pathname==='/api/config') data={conversation_debug_enabled:false};
    else if(u.pathname==='/api/me/conversation-debug') data={allowed:false,enabled:false};
    else if(u.pathname==='/api/conversations') data=[{id:'conv',agent_id:'main',agent_name:'销售部',title:'销售计划'}];
    else if(u.pathname.endsWith('/goal-options')) data={enabled:true,agent_type:'llm',collaboration_mode:'AUTONOMOUS',allowed_collaboration_modes:['AUTONOMOUS']};
    else if(u.pathname.endsWith('/messages')) data=[{id:'msg',role:'assistant',content:'计划',metadata_json:{steps:[{status:'runtime_done',message:'销售部 · 召回 3 条记忆',sources:refs}]}}];
    else if(u.pathname.includes('/memory-sources/')) {
     reads++;
     if(fail) {fail=false; return route.fulfill({status:503,json:{detail:'加载暂时失败'}});}
     if(u.pathname.endsWith('mem2')) return route.fulfill({status:410,json:{detail:'该记忆已撤回、归档或不可用'}});
     data={id:'mem1',content:'华东销售记忆正文\n<script>window.memoryXSS=true</script>',type:'semantic',subject_name:'华东销售',status:'active',confidence:.8,source_mode:'explicit',has_conflict:false,updated_at:'2026-10-09T10:00:00Z',evidences:[{id:'e1',accessible:true,label:'内部业务沟通',source_type:'conversation',summary:'9月会议确认的销售数据'},{id:'e2',accessible:false,label:'业务依据',source_type:'knowledge'}]};
    }
    return route.fulfill({json:data});
   }
   if(process.env.LIVE_ORIGIN) return route.continue();
   const file=u.pathname.startsWith('/static/dist/')?path.join(root,u.pathname.slice(13)):path.join(root,'index.html');
   return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto(origin+'/chat');
  await page.locator('.conv-title-text').getByText('销售计划',{exact:true}).click();
  const timeline=page.locator('.runtime-timeline').first();
  await timeline.locator('.flow-header').click();
  await timeline.getByRole('button',{name:'记忆 · 华东销售',exact:true}).click();
  const modal=page.locator('.source-modal');
  await modal.getByText('加载暂时失败',{exact:false}).waitFor();
  await modal.getByRole('button',{name:'重试',exact:true}).click();
  await modal.getByText('9月会议确认的销售数据',{exact:true}).waitFor();
  assert.match(await modal.innerText(),/华东销售记忆正文/);
  assert.match(await modal.innerText(),/该来源已不可用或无权查看/);
  assert.equal(await page.evaluate(()=>window.memoryXSS),undefined);
  await page.screenshot({path:'/tmp/cortexa-memory-source.png'});
  await modal.locator('.modal-close').click();
  await timeline.getByRole('button',{name:'记忆 2',exact:true}).click();
  await modal.getByText('该记忆已撤回、归档或不可用',{exact:false}).waitFor();
  assert.doesNotMatch(await modal.innerText(),/华东销售记忆正文/);
  await modal.locator('.modal-close').click();
  await timeline.getByRole('button',{name:'旧记忆',exact:true}).click();
  await modal.getByText('历史记录未保存记忆标识，无法定位详情。',{exact:true}).waitFor();
  assert.equal(reads,3);
  assert.deepEqual(errors,[]);
  console.log('PASS: memory detail, source evidence, retry, unavailable source, historical missing identity, escaped content');
 } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
