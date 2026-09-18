const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const root=process.env.FRONTEND_DIST_DIR || path.resolve(__dirname,'../../src/agentdevstu/web/static/dist'),permissions=['members.manage','agent.use'];
 let units=[],profile={user_id:'engineer',display_name:'王工',org_unit_id:null,org_unit_name:'',position_title:'',responsibility:'',responsibility_tags:[],coverage_scope:''},createdWork;
 await page.route('http://org.local/**',async r=>{
 const u=new URL(r.request().url()),method=r.request().method();let data=[];
 if(u.pathname.startsWith('/api/')){
 if(u.pathname==='/api/auth/me')data={id:'admin',display_name:'管理员',username:'admin',system_permissions:[],memberships:[{workspace_id:'ws',permissions}]};
 else if(u.pathname==='/api/workspaces')data=[{id:'ws',name:'测试空间'}];
 else if(u.pathname==='/api/organization/units'&&method==='POST'){data={id:'dept',workspace_id:'ws',...r.request().postDataJSON()};units.push(data)}
 else if(u.pathname==='/api/organization/units')data=units;
 else if(u.pathname==='/api/organization/members/engineer'&&method==='PUT'){profile={...profile,...r.request().postDataJSON()};profile.org_unit_name=units.find(d=>d.id===profile.org_unit_id)?.name||'';data=profile}
 else if(u.pathname==='/api/organization/members')data=[profile];
 else if(u.pathname==='/api/works/members')data=[{id:'admin',name:'管理员'},{id:'engineer',name:'王工'}];
 else if(u.pathname==='/api/works/assignee-recommendations')data=r.request().postDataJSON().goal.includes('前端')?[{user_id:'engineer',display_name:'王工',org_unit_name:'研发部',position_title:'前端工程师',score:65,reason:'匹配：前端、Vue；当前可见同类已完成工作 0 项，未完成工作 0 项'}]:[];
 else if(u.pathname==='/api/works'&&method==='POST'){createdWork={id:'work',...r.request().postDataJSON()};data=createdWork}
 return r.fulfill({json:data});}
 const file=u.pathname.startsWith('/static/dist/')?path.join(root,u.pathname.slice(13)):path.join(root,'index.html');
 await r.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
 });
 await page.goto('http://org.local/access');
 await page.getByRole('button',{name:'组织与职责',exact:true}).click();
 await page.getByRole('button',{name:'新增部门',exact:true}).click();
 await page.getByLabel('部门名称',{exact:true}).fill('研发部');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await page.getByRole('navigation',{name:'组织树'}).getByRole('button',{name:'研发部',exact:true}).waitFor();
 await page.getByRole('button',{name:'编辑职责',exact:true}).click();
 await page.getByRole('button',{name:'所属部门',exact:true}).click();
 await page.getByRole('option',{name:'研发部',exact:true}).click();
 await page.getByLabel('岗位名称',{exact:true}).fill('前端工程师');
 await page.getByLabel('职责描述',{exact:true}).fill('负责 Vue 前端开发和业务页面');
 await page.getByLabel('职责标签',{exact:false}).fill('前端、Vue');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await page.getByText('研发部 · 前端工程师',{exact:true}).waitFor();
 assert.deepEqual(profile.responsibility_tags,['前端','Vue']);
 const shots=process.env.ORG_SCREENSHOT_DIR;if(shots)fs.mkdirSync(shots,{recursive:true});
 for(const appearance of ['light','dark']){await page.emulateMedia({colorScheme:appearance});if(shots)await page.screenshot({path:path.join(shots,`organization-${appearance}.png`),fullPage:true})}
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 if(shots)await page.screenshot({path:path.join(shots,'organization-mobile.png'),fullPage:true});
 await page.setViewportSize({width:1440,height:1000});
 await page.goto('http://org.local/works');
 await page.getByRole('button',{name:/新建工作/}).click();
 await page.getByLabel('标题',{exact:true}).fill('开发页面');
 await page.getByLabel('执行目标',{exact:true}).fill('完成 Vue 前端业务页面');
 await page.getByRole('button',{name:/王工 · 65 分/}).click();
 if(await page.locator('.work-editor select').count())assert.equal(await page.locator('.work-editor select').first().inputValue(),'engineer');else assert.equal(await page.getByRole('button',{name:'负责人',exact:true}).innerText(),'王工');
 await page.getByLabel('执行目标',{exact:true}).fill('布置展台');
 await page.getByText('暂无职责匹配，请手动选择负责人。',{exact:true}).waitFor();
 if(await page.locator('.work-editor select').count())assert.equal(await page.locator('.work-editor select').first().inputValue(),'engineer');else assert.equal(await page.getByRole('button',{name:'负责人',exact:true}).innerText(),'王工');
 await page.getByLabel('执行目标',{exact:true}).fill('完成 Vue 前端业务页面');
 await page.getByRole('button',{name:/王工 · 65 分/}).waitFor();
 if(shots)await page.screenshot({path:path.join(shots,'recommendations.png'),fullPage:true});
 await page.getByRole('button',{name:'创建并派发',exact:true}).click();
 await page.locator('.work-editor').waitFor({state:'detached'});
 assert.equal(createdWork.assignee_id,'engineer');assert.equal(createdWork.reviewer_id,'admin');assert.deepEqual(errors,[]);
 console.log('Organization CRUD, responsive themes, recommendations and manual selection passed');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
