// Built UI with isolated API responses; no development conversations are changed.
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
  const origin='http://timeline.local'; let messages=[];
  let releaseMessages; const reconciliation=new Promise(resolve=>{releaseMessages=resolve});
  const stats={input_tokens:100,output_tokens:20,token_count:120,usage_source:'provider'};
  const source={type:'knowledge_base',name:'9月销售达成报告',document_id:'doc-1'};
  await page.route(origin+'/**', async route=>{
   const u=new URL(route.request().url()); let data=[];
   if(u.pathname.startsWith('/api/')) {
    if(u.pathname==='/api/auth/me') data={id:'test',display_name:'测试用户',system_permissions:[],memberships:[{workspace_id:'ws',permissions:['agent.use','agent.read']}]};
    else if(u.pathname==='/api/workspaces') data=[{id:'ws',name:'测试空间'}];
    else if(u.pathname==='/api/auth/agents' || u.pathname==='/api/collaboration/agents') data=[{id:'main',name:'Peter',agent_type:'llm',status:'active'}];
    else if(u.pathname==='/api/config') data={conversation_debug_enabled:false};
    else if(u.pathname==='/api/me/conversation-debug') data={allowed:false,enabled:false};
    else if(u.pathname==='/api/conversations') data=[{id:'conv',agent_id:'main',agent_name:'Peter',title:'研究10月销售目标'}];
    else if(u.pathname.endsWith('/goal-options')) data={enabled:true,agent_type:'llm',collaboration_mode:'AUTONOMOUS',allowed_collaboration_modes:['AUTONOMOUS']};
    else if(u.pathname.endsWith('/message-route')) data={use_goal:true};
    else if(u.pathname.endsWith('/messages')) { if(messages.length) await reconciliation; data=messages; }
    else if(u.pathname.endsWith('/goals/stream')) {
     const events=[
      {type:'user_message',id:'u1',goal_id:'goal'},
      {type:'runtime_progress',agent_name:'Peter',agent_id:'main',action_id:'query',status:'running',message:'检索知识库'},
      {type:'runtime_progress',agent_name:'Peter',agent_id:'main',action_id:'query',status:'completed',message:'知识检索返回 1 个来源',sources:[source]},
      {type:'runtime_progress',agent_name:'销售部',agent_id:'sales',action_id:'reason',status:'running',message:'正在生成回复'},
      {type:'runtime_draft',agent_name:'销售部',agent_id:'sales',action_id:'reason',content:'根据9月达成情况，'},
      {type:'runtime_draft',agent_name:'销售部',agent_id:'sales',action_id:'reason',content:'建议分区域设置10月目标。'},
      {type:'runtime_usage',agent_name:'销售部',agent_id:'sales',action_id:'reason',stats},
      {type:'done',id:'a1',goal_id:'goal',status:'COMPLETE',content:'目标规划完成'}];
     messages=[{id:'a1',role:'assistant',content:'目标规划完成',metadata_json:{execution_goal:'研究10月销售目标',execution_usage:[{agent_id:'sales',agent_name:'销售部',...stats}],steps:[{status:'runtime_done',message:'Peter · 知识检索返回 1 个来源',sources:[source]},{status:'runtime_done',message:'销售部 · 正在生成回复',agent_name:'销售部',draft:'根据9月达成情况，建议分区域设置10月目标。',usage:stats}]}}];
     return route.fulfill({contentType:'text/event-stream',body:events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join('')});
    }
    return route.fulfill({json:data});
   }
   const file=u.pathname.startsWith('/static/dist/')?path.join(root,u.pathname.slice(13)):path.join(root,'index.html');
   return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto(origin+'/chat');
  await page.locator('.conv-title-text').getByText('研究10月销售目标',{exact:true}).click();
  assert.equal(await page.locator('.chat-input-hint').count(),0);
  const composer = page.locator('.chat-input-wrap');
  const inputBox = await page.locator('.chat-input').boundingBox();
  const modeBox = await page.locator('.chat-collaboration-mode').boundingBox();
  assert.ok(inputBox.height <= 40, 'default input is one line');
  assert.ok(modeBox.x >= inputBox.x + inputBox.width, 'mode is to the right of input');
  assert.ok((await composer.boundingBox()).height <= 58, 'composer is a single compact row');
  await page.locator('.chat-input').fill('第一行\n第二行\n第三行');
  await page.waitForFunction(()=>document.querySelector('.chat-input').clientHeight > 60);
  await page.locator('.chat-input').fill('研究10月销售目标');
  await page.locator('.chat-send').click();
  await page.getByText('目标规划完成',{exact:true}).waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('.runtime-timeline').length===2);
  const timeline=page.locator('.runtime-timeline').first();
  await timeline.locator('.flow-header').click();
  assert.equal(await timeline.locator('.flow-step').count(),2);
  assert.match(await timeline.locator('.flow-total').innerText(),/120 Token/);
  assert.equal(await timeline.locator('.flow-goal p').innerText(),'研究10月销售目标');
  await timeline.locator('.flow-draft summary').click();
  assert.match(await timeline.locator('.flow-step').nth(1).innerText(),/根据9月达成情况，建议分区域设置10月目标/);
  await timeline.locator('.flow-usage summary').click();
  assert.match(await timeline.locator('.usage-row').innerText(),/销售部/);
  await timeline.locator('.flow-sources button').click();
  await page.getByText('9月销售达成报告',{exact:true}).last().waitFor();
  await page.keyboard.press('Escape');
  releaseMessages();
  await page.waitForFunction(()=>document.querySelectorAll('.runtime-timeline').length===1);
  await page.reload();
  await page.locator('.conv-title-text').getByText('研究10月销售目标',{exact:true}).click();
  await timeline.locator('.flow-header').click();
  await timeline.locator('.flow-draft summary').click();
  await timeline.locator('.flow-usage summary').click();
  await page.screenshot({path:'/tmp/cortexa-runtime-timeline.png',fullPage:true});
  await page.setViewportSize({width:780,height:900});
  assert.equal(await timeline.evaluate(el=>el.scrollWidth <= el.clientWidth),true);
  assert.deepEqual(errors,[]);
  console.log('PASS: embedded streamed draft, document source, call/Agent Token totals, saved timeline, responsive layout');
 } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
