// Isolated API fixtures; tests the built editor without modifying user data.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  const origin=process.env.LIVE_ORIGIN || 'http://rules.local';
  const root=path.resolve(__dirname,'../../src/cortexa/web/static/dist');
  let agent={id:'agent',name:'Peter',role:'营销负责人',agent_type:'llm',status:'active',work_rules:'执行方式\n先核实销售数据\n\n工作边界\n不得编造销售实绩',tags:[],input_schema:{},output_schema:{},knowledge_base_ids:[],tool_ids:[]};
  let saved;
  await page.route(origin+'/**',async route=>{
   const req=route.request(),u=new URL(req.url());let data=[];
   if(u.pathname.startsWith('/api/')){
    if(u.pathname==='/api/auth/me')data={id:'user',display_name:'验收用户',system_permissions:[],memberships:[{workspace_id:'ws',permissions:['agent.read','agent.update','agent.use']}]};
    else if(u.pathname==='/api/workspaces')data=[{id:'ws',name:'测试空间'}];
    else if(u.pathname==='/api/agents' || u.pathname==='/api/auth/agents')data=[agent];
    else if(u.pathname==='/api/agents/agent' && req.method()==='PUT'){saved=req.postDataJSON();agent={...agent,...saved};data=agent;}
    else if(u.pathname==='/api/agents/agent')data=agent;
    else if(u.pathname.includes('/config/'))data={providers:[]};
    return route.fulfill({json:data});
   }
   if(process.env.LIVE_ORIGIN) return route.continue();
   const file=u.pathname.startsWith('/static/dist/')?path.join(root,u.pathname.slice(13)):path.join(root,'index.html');
   return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto(origin+'/agents');
  await page.locator('.agent-card').click();
  await page.locator('.editor-nav .nav-item').filter({hasText:'工作规则'}).click();
  assert.equal(await page.locator('.editor-nav .nav-item').filter({hasText:/工作方式|工作边界/}).count(),0);
  const textarea=page.locator('.section:visible textarea');
  assert.match(await textarea.inputValue(),/先核实销售数据/);
  assert.match(await textarea.inputValue(),/不得编造销售实绩/);
  await textarea.fill('先核实历史销售；需要时邀请相关 Agent；不得编造实绩。');
  await page.locator('.editor-actions').getByRole('button',{name:'保存',exact:true}).click();
  await page.getByText('保存成功',{exact:true}).waitFor();
  assert.equal(saved.work_rules,'先核实历史销售；需要时邀请相关 Agent；不得编造实绩。');
  assert.ok(!('behavior' in saved) && !('boundaries' in saved));
  await page.reload();await page.locator('.agent-card').click();
  await page.locator('.editor-nav .nav-item').filter({hasText:'工作规则'}).click();
  assert.equal(await textarea.inputValue(),saved.work_rules);
  await page.locator('.preset-card-item').filter({hasText:'协作型'}).click();
  assert.match(await textarea.inputValue(),/执行要求/);
  assert.match(await textarea.inputValue(),/工作规则 - 协作型/);
  await page.screenshot({path:'/tmp/cortexa-agent-work-rules.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: unified rules editor, migrated content, save payload, reload, execution and boundary preset');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
