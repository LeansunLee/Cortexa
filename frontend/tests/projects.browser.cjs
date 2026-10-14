const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright')
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict')
;(async()=>{const browser=await chromium.launch({headless:true,channel:'chrome'});try{
 const page=await browser.newPage({viewport:{width:1280,height:950}}),origin=process.env.LIVE_ORIGIN||'http://projects.local',root=path.resolve(__dirname,'../../src/cortexa/web/static/dist')
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 let project=null,work={id:'w1',title:'测算销售目标',goal:'测算',status:'in_progress',assignee_name:'成员',permissions:{project:true},project_id:null},sent=null
 await page.route(origin+'/**',async route=>{const req=route.request(),u=new URL(req.url()),p=u.pathname;let data=[]
 if(p.startsWith('/api/')){
 if(p==='/api/auth/me')data={id:'user',display_name:'测试',system_permissions:[],memberships:[{workspace_id:'ws',permissions:['agent.use','agent.read']}]}
 else if(p==='/api/workspaces')data=[{id:'ws',name:'测试'}]
 else if(['/api/auth/agents','/api/collaboration/agents'].includes(p))data=[{id:'main',name:'Peter',agent_type:'llm'}]
 else if(p==='/api/conversations')data=[{id:'conv',agent_id:'main',agent_name:'Peter',title:'项目对话'}]
 else if(p.endsWith('/messages'))data=[]
 else if(p.endsWith('/messages/stream')){sent=req.postDataJSON();return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({type:'done',id:'reply',content:'项目摘要已读取',project_ids:sent.project_ids,sources:[{type:'project',project_id:'p1',name:'浙江商家拓展'}]})+'\n\n'})}
 else if(p.endsWith('/goal-options'))data={enabled:false,collaboration_mode:'EXPLICIT_ONLY'}
 else if(p==='/api/works/members')data=[{id:'user',name:'测试'},{id:'member',name:'成员'}]
 else if(p==='/api/projects' && req.method()==='POST'){project={...req.postDataJSON(),id:'p1',owner_name:'测试',permissions:{manage:true},counts:{},visible_work_count:0,progress:0,statistics_scope:'按可见工作统计'};data=project}
 else if(p==='/api/projects')data=project?[project]:[]
 else if(p==='/api/projects/p1')data=project
 else if(p==='/api/projects/p1/deliverables')data=[]
 else if(p==='/api/projects/p1/activities')data=[]
 else if(p==='/api/works')data=u.searchParams.get('project_id')?(work.project_id==='p1'?[work]:[]):[work]
 else if(p==='/api/projects/works/w1/assignment'){work.project_id=req.postDataJSON().project_id;data=work}
 else if(p==='/api/config')data={conversation_debug_enabled:false}
 else if(p==='/api/me/conversation-debug')data={allowed:false,enabled:false}
 return route.fulfill({json:data})}
 if(process.env.LIVE_ORIGIN)return route.continue()
 const file=p.startsWith('/static/dist/')?path.join(root,p.slice(13)):path.join(root,'index.html');return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'})})
 await page.goto(origin+'/projects');await page.getByRole('button',{name:'新建项目',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'编辑项目'});await dialog.getByLabel('项目名称').fill('浙江商家拓展');await dialog.getByLabel('项目目标').fill('拓展浙江门店');await dialog.getByRole('button',{name:'保存',exact:true}).click()
 await page.getByRole('heading',{name:'浙江商家拓展'}).waitFor();await page.getByRole('button',{name:'选择现有工作'}).click();await page.getByRole('option',{name:'测算销售目标'}).click();await page.getByRole('button',{name:'关联工作',exact:true}).click()
 await page.getByRole('link',{name:'测算销售目标',exact:true}).waitFor();assert.equal(work.status,'in_progress')
 await page.screenshot({path:'/tmp/cortexa-project-detail.png'})
 await page.getByRole('button',{name:'移出项目',exact:true}).click();await page.getByText('没有可见工作',{exact:true}).waitFor();assert.equal(work.project_id,null)
 await page.getByRole('link',{name:'在 Agent 对话中引用'}).click();await page.locator('.conv-title-text').getByText('项目对话',{exact:true}).click();await page.locator('.project-chip').getByText('# 浙江商家拓展',{exact:false}).waitFor()
 await page.locator('.chat-input').fill('总结项目');await page.getByRole('button',{name:'发送消息并执行已配置的协作任务'}).click();await page.getByText('项目摘要已读取',{exact:true}).waitFor();assert.deepEqual(sent.project_ids,['p1']);assert.equal(await page.locator('.project-chip').count(),0)
 await page.setViewportSize({width:390,height:900});await page.goto(origin+'/projects/p1');await page.getByRole('heading',{name:'浙江商家拓展'}).waitFor();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));await page.screenshot({path:'/tmp/cortexa-project-narrow.png'})
 assert.deepEqual(errors,[]);console.log('PASS project create, association without status reset, removal, chat reference, per-turn clearing and narrow layout')
 }finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1})
