const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1360,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const root=path.resolve(__dirname,'../../src/cortexa/web/static/dist');
  const origin=process.env.LIVE_ORIGIN || 'http://recovery.local';
  let status='WAITING', recovered=false, stops=0, checks=0, dispatches=0;
  await page.route(origin+'/**',async route=>{
   const req=route.request(),u=new URL(req.url());let data=[];
   if(u.pathname.startsWith('/api/')){
    if(u.pathname==='/api/auth/me')data={id:'test',display_name:'测试用户',system_permissions:[],memberships:[{workspace_id:'ws',permissions:['agent.use','agent.read']}]};
    else if(u.pathname==='/api/workspaces')data=[{id:'ws',name:'测试空间'}];
    else if(u.pathname==='/api/auth/agents'||u.pathname==='/api/collaboration/agents')data=[{id:'main',name:'Peter',agent_type:'llm',status:'active'}];
    else if(u.pathname==='/api/config')data={conversation_debug_enabled:false};
    else if(u.pathname==='/api/me/conversation-debug')data={allowed:false,enabled:false};
    else if(u.pathname==='/api/conversations')data=[{id:'conv',agent_id:'main',agent_name:'Peter',title:'恢复任务'}];
    else if(u.pathname.endsWith('/goal-options'))data={enabled:true,agent_type:'llm',collaboration_mode:'AUTONOMOUS',allowed_collaboration_modes:['AUTONOMOUS']};
    else if(u.pathname.endsWith('/question'))data={question:null};
    else if(u.pathname.endsWith('/messages'))data=[{id:'a1',role:'assistant',content:recovered?'已接回原会话报告':'需要核实原会话',metadata_json:{goal_id:'g1'}}];
    else if(u.pathname.endsWith('/goals/g1'))data={goal_id:'g1',status,revision:1,reason:status==='WAITING'?'action_result_unknown':null,can_reconcile:status==='WAITING',pending_agents:[],consumed:{}};
    else if(u.pathname.endsWith('/goals/g1/reconcile')){
     checks++;assert.deepEqual(req.postDataJSON(),{});recovered=true;status='COMPLETE';
     const events=[{type:'token',content:'已接回原会话报告'},{type:'done',id:'a2',goal_id:'g1',status:'COMPLETE',revision:2,content:'已接回原会话报告'}];
     return route.fulfill({contentType:'text/event-stream',body:events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join('')});
    } else if(u.pathname.endsWith('/goals/g1/stop')){stops++;status='WAITING';data={goal_id:'g1',status,reason:'cancelled',can_reconcile:false};}
    else if(req.method()==='POST'&&(u.pathname.endsWith('/goals/stream')||u.pathname.endsWith('/messages/stream'))){dispatches++;throw Error('Recovery must not dispatch a new task');}
    return route.fulfill({json:data});
   }
   if(process.env.LIVE_ORIGIN)return route.continue();
   const file=u.pathname.startsWith('/static/dist/')?path.join(root,u.pathname.slice(13)):path.join(root,'index.html');
   return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto(origin+'/chat');
  await page.locator('.conv-title-text').getByText('恢复任务',{exact:true}).click();
  await page.getByRole('button',{name:'检查原会话并继续',exact:true}).waitFor();
  await page.locator('.chat-input').fill('尚未发送的草稿');
  await page.getByRole('button',{name:'检查原会话并继续',exact:true}).click();
  await page.getByText('已接回原会话报告',{exact:true}).waitFor();
  assert.equal(await page.locator('.chat-input').inputValue(),'尚未发送的草稿');
  assert.equal(checks,1);assert.equal(dispatches,0);
  status='RUNNING';await page.reload();
  await page.locator('.conv-title-text').getByText('恢复任务',{exact:true}).click();
  await page.getByRole('button',{name:'停止任务',exact:true}).click();
  await page.waitForFunction(()=>!document.body.innerText.includes('任务仍在后台执行'));
  assert.equal(stops,1);assert.deepEqual(errors,[]);
  console.log('PASS: owned recovery control, read-only recovery endpoint, no new dispatch, preserved draft, background explicit stop');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
