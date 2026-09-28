// Real built UI, isolated API responses; no production accounts/data are changed.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page = await browser.newPage({viewport:{width:1360,height:900}});
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  const origin=process.env.LIVE_ORIGIN || 'http://goal.local';
  const root=path.resolve(__dirname,'../../src/cortexa/web/static/dist');
  const agents=[{id:'main',name:'主Agent',agent_type:'llm',status:'active'}, {id:'sales',name:'销售Agent',agent_type:'llm',description:'查询销售'}, {id:'analysis',name:'分析Agent',agent_type:'llm',description:'分析销售'}];
  const permissions=['agent.use','agent.read','agent.update'];
  let messages=[], goal=null, request=null, decision=null, resumed=0, legacy=0, conversationTitle=null, secondTitle=null;
  const allModes=['EXPLICIT_ONLY','ASK_BEFORE_COLLABORATION','AUTONOMOUS'];
  let allowedModes=[...allModes]; const savedModes={}; let rejectSave=false;
  await page.route(origin+'/**', async route=>{
   const req=route.request(), u=new URL(req.url()); let data=[];
   if(u.pathname.startsWith('/api/')) {
    if(u.pathname==='/api/auth/me') data={id:'test',display_name:'测试用户',username:'test',system_permissions:[],memberships:[{workspace_id:'ws',permissions}]};
    else if(u.pathname==='/api/workspaces') data=[{id:'ws',name:'测试空间'}];
    else if(u.pathname==='/api/auth/agents' || u.pathname==='/api/collaboration/agents') data=agents;
    else if(u.pathname==='/api/config') data={conversation_debug_enabled:false};
    else if(u.pathname==='/api/me/conversation-debug') data={allowed:false,enabled:false};
    else if(u.pathname==='/api/conversations') data=[{id:'conv',agent_id:'main',agent_name:'主Agent',title:conversationTitle},{id:'conv2',agent_id:'main',agent_name:'主Agent',title:secondTitle}];
    else if(u.pathname.endsWith('/goal-options')) {
      const selected=savedModes[u.pathname.split('/')[3]] || 'EXPLICIT_ONLY';
      data={enabled:true,agent_type:'llm',collaboration_mode:allowedModes.includes(selected)?selected:allowedModes.at(-1),allowed_collaboration_modes:allowedModes};
    }
    else if(u.pathname.endsWith('/collaboration-mode')) {
      if(rejectSave) return route.fulfill({status:422,json:{detail:'工作空间限制已更新'}});
      const mode=req.postDataJSON().collaboration_mode;
      assert.ok(allowedModes.includes(mode)); savedModes[u.pathname.split('/')[3]]=mode;
      data={collaboration_mode:mode,allowed_collaboration_modes:allowedModes};
    }
    else if(u.pathname.endsWith('/message-route')) data={use_goal:req.postDataJSON().content!=='你好'};
    else if(u.pathname.endsWith('/messages')) data=u.pathname.includes('/conv2/')?[]:messages;
    else if(u.pathname.endsWith('/goals/stream')) {
      request=req.postDataJSON();
      conversationTitle='分析销售';
      goal={goal_id:'goal',status:'WAITING',reason:'collaboration_approval_required',revision:4,pending_agents:['sales','analysis']};
      messages=[{id:'u1',role:'user',content:request.content,metadata_json:{goal_id:'goal'}},{id:'a1',role:'assistant',content:'请选择协作参与者',metadata_json:{goal_id:'goal'}}];
      const events=[{type:'user_message',id:'u1',goal_id:'goal',conversation_title:conversationTitle}, {type:'goal_status',...goal},{type:'done',id:'a1',content:'请选择协作参与者',...goal}];
      return route.fulfill({contentType:'text/event-stream',body:events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join('')});
    } else if(u.pathname.endsWith('/candidates')) data=agents.slice(1);
    else if(u.pathname.endsWith('/authorization')) {decision=req.postDataJSON();goal={...goal,revision:5,reason:'collaboration_authorized',pending_agents:[]};data=goal;}
    else if(u.pathname.endsWith('/resume')) {
      resumed++; assert.equal(req.postDataJSON().revision,5);
      goal={...goal,revision:9,status:'COMPLETE',reason:null};
      const done={type:'done',id:'a2',content:'目标已完成',...goal,collaborations:[{agent_name:'销售Agent',status:'success',result:'销量 2'}]};
      messages.push({id:'a2',role:'assistant',content:done.content,metadata_json:{goal_id:'goal',collaborations:[{agent_name:'销售Agent',status:'success',summary:'销量摘要',goal_result:{conversation_id:'conv',goal_id:'goal',action_id:'action'}}]}});
      return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify(done)+'\n\n'});
    } else if(u.pathname.endsWith('/goals/goal/collaborations/action')) data={result:'归档完整结果：销量 2'};
    else if(u.pathname.endsWith('/goals/goal')) data=goal;
    else if(u.pathname.endsWith('/messages/stream')) { legacy++; secondTitle='你好'; const events=[{type:'user_message',id:'ordinary-user',conversation_title:secondTitle},{type:'done',id:'ordinary',content:'普通回复'}]; return route.fulfill({contentType:'text/event-stream',body:events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join('')}); }
    return route.fulfill({json:data});
   }
   if (process.env.LIVE_ORIGIN) return route.continue();
   const file=u.pathname.startsWith('/static/dist/')?path.join(root,u.pathname.slice(13)):path.join(root,'index.html');
   return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto(origin+'/chat');
  await page.locator('.conv-item').first().locator('.conv-title-text').click();
  const modeSelect=page.getByRole('button',{name:'协作方式',exact:true});
  const labels={EXPLICIT_ONLY:'不主动',ASK_BEFORE_COLLABORATION:'询问',AUTONOMOUS:'主动'};
  const chooseMode=async mode=>{await modeSelect.click();await page.getByRole('option',{name:labels[mode],exact:true}).click();};
  await modeSelect.click();
  assert.equal((await modeSelect.innerText()).trim(),'不主动');
  assert.deepEqual(await page.getByRole('option').allTextContents(),['不主动','询问','主动']);
  assert.equal(await page.locator('.search-select-menu input').count(),0);
  await page.keyboard.press('ArrowDown');
  assert.equal(await page.evaluate(()=>document.activeElement.textContent.trim()),'询问');
  const {themeVariables}=await import('../src/utils/theme.js');
  for(const appearance of ['light','dark']) {
    await page.evaluate(({appearance,vars})=>{
      const root=document.documentElement;
      root.dataset.theme=appearance;root.style.colorScheme=appearance;root.dataset.colorTheme='glass';
      Object.entries(vars).forEach(([key,value])=>root.style.setProperty(key,value));
    },{appearance,vars:themeVariables({value:'#00856A',mode:'glass',finish:'clear'})});
    await page.waitForTimeout(220);
    assert.match(await page.locator('.search-select-menu').evaluate(e=>getComputedStyle(e).backdropFilter),/blur/);
    const bounds=await page.locator('.search-select-menu').boundingBox();
    assert.ok(bounds.x>=0 && bounds.y>=0 && bounds.y+bounds.height<=900,'menu stays inside viewport');
    const optionBottom=await page.getByRole('option').last().evaluate(e=>e.getBoundingClientRect().bottom);
    assert.ok(optionBottom<=bounds.y+bounds.height,'all three options are fully visible');
    await page.screenshot({path:`/tmp/cortexa-collaboration-dropdown-${appearance}.png`});
  }
  await page.keyboard.press('Escape');
  await chooseMode('AUTONOMOUS');
  await page.getByText('由 Agent 自行决策是否协作',{exact:true}).waitFor();
  rejectSave=true;
  await chooseMode('ASK_BEFORE_COLLABORATION');
  await page.getByText('协作方式保存失败：工作空间限制已更新',{exact:true}).waitFor();
  await page.waitForFunction(()=>document.querySelector('[aria-label="协作方式"]').textContent.trim()==='主动');
  rejectSave=false;
  await chooseMode('ASK_BEFORE_COLLABORATION');
  await page.getByText('需要其他 Agent 协作时，先询问你',{exact:true}).waitFor();
  await page.reload();
  await page.locator('.conv-item').first().locator('.conv-title-text').click();
  await page.getByText('需要其他 Agent 协作时，先询问你',{exact:true}).waitFor();
  assert.equal((await modeSelect.innerText()).trim(),'询问');
  await page.locator('.chat-input').fill('@分析Agent @销售Agent 分析销售');
  await page.locator('.agent-chip').nth(1).waitFor();
  assert.equal(await page.locator('.chip-order').count(),0);
  assert.equal(await page.getByTitle('提前执行').count(),0);
  assert.equal(await page.getByPlaceholder('分工（可选）').count(),2);
  await page.locator('.chat-send').click();
  await page.locator('.goal-candidate').nth(1).waitFor();
  assert.equal(await page.locator('.chat-conv-title').innerText(), '分析销售');
  assert.ok(request.idempotency_key);
  assert.deepEqual(request.participants.map(p=>p.agent_id),['analysis','sales']);
  assert.ok(request.participants.every(p=>!p.task));
  for(const [theme,width] of [['light',1360],['dark',1360],['dark',600]]) {
    await page.setViewportSize({width,height:900});
    await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    const bounds=await page.locator('.goal-panel').boundingBox();
    assert.ok(bounds.x>=0 && bounds.x+bounds.width<=width+1);
    assert.ok(await page.getByRole('button',{name:'全部拒绝并继续',exact:true}).isVisible());
    const modeBounds=await page.locator('.chat-collaboration-mode').boundingBox();
    assert.ok(modeBounds.x>=0 && modeBounds.x+modeBounds.width<=width+1);
    await page.screenshot({path:`/tmp/cortexa-collaboration-${theme}-${width}.png`});
  }
  await page.locator('.goal-candidate input').first().check();
  await page.getByRole('button',{name:'允许所选并继续',exact:true}).click();
  await page.getByText('目标已完成',{exact:true}).first().waitFor();
  assert.deepEqual(decision.approved_agents,['sales']); assert.deepEqual(decision.denied_agents,['analysis']); assert.equal(resumed,1);
  await page.reload();
  await page.locator('.conv-title-text').getByText('分析销售',{exact:true}).click();
  assert.equal(await page.locator('.goal-panel').count(),0);
  await page.locator('.collab-summary').click();
  await page.getByText('完整输出',{exact:true}).click();
  await page.getByText('归档完整结果：销量 2',{exact:true}).waitFor();
  await page.locator('.conv-item').nth(1).click();
  await page.waitForFunction(()=>document.querySelector('[aria-label="协作方式"]').textContent.trim()==='不主动');
  await page.locator('.chat-input').fill('你好');
  await page.locator('.chat-send').click();
  await page.getByText('普通回复',{exact:true}).waitFor(); assert.equal(legacy,1);
  assert.equal(await page.locator('.chat-conv-title').innerText(),'你好');
  for(const count of [2,1]) {
    allowedModes=allModes.slice(0,count);
    await page.reload();
    await page.locator('.conv-title-text').getByText('分析销售',{exact:true}).click();
    await modeSelect.click();
    assert.equal(await page.getByRole('option').count(),count);
    assert.deepEqual(await page.getByRole('option').allTextContents(),allowedModes.map(mode=>labels[mode]));
    assert.equal((await modeSelect.innerText()).trim(),labels[allowedModes.at(-1)]);
    await page.keyboard.press('Escape');
  }
  assert.deepEqual(errors,[]);
  console.log('PASS: collaboration choices, save failure, persistence, per-conversation default, workspace ceilings, automatic routing, unordered participants, approval, resume, reload, ordinary greeting, responsive layout (mocked APIs)');
 } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
