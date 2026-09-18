const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const dist=path.resolve(__dirname,'../../src/agentdevstu/web/static/dist');
const origin=process.env.LIVE_ORIGIN||'http://textdoc.local';
(async()=>{const browser=await chromium.launch({headless:true,channel:'chrome'});try{
for (const appearance of ['light', 'dark', 'system']) for (const width of [1440, 390]) {
const page=await browser.newPage({viewport:{width,height:1000},colorScheme:appearance==='light'?'light':'dark'}),errors=[];
await page.addInitScript(appearance=>{
  for(const key of ['theme-color','theme-color:user:user']) localStorage.setItem(key,JSON.stringify({value:'#008575',mode:'glass',finish:'clear'}));
  for(const key of ['ui-appearance','ui-appearance:user:user']) localStorage.setItem(key,appearance);
},appearance);
page.on('pageerror',e=>errors.push(e.message));
let content='',name='';
const doc=()=>({id:'doc',name,status:'active',content:'文档测试摘要',metadata_json:{size:20},created_by:'user'});
await page.route(origin+'/**',async route=>{const u=new URL(route.request().url());
if(u.pathname.startsWith('/api/')){let data={};
if(u.pathname==='/api/auth/me')data={id:'user',username:'tester',display_name:'验证账号',system_permissions:['knowledge.manage','knowledge.use'],memberships:[{workspace_id:'ws',permissions:['knowledge.manage','knowledge.use']}]};
else if(u.pathname==='/api/workspaces')data=[{id:'ws',name:'测试工作空间'}];
else if(u.pathname==='/api/knowledge')data=[{id:'kb',name:'文本文档验证',status:'active',document_count:name?1:0}];
else if(u.pathname==='/api/knowledge/kb')data={id:'kb',name:'文本文档验证',documents:name?[doc()]:[],folders:[{id:'folder',name:'资源管理器测试文件夹',parent_id:null}]};
else if(u.pathname.endsWith('/folders'))data=[{id:'folder',name:'资源管理器测试文件夹',parent_id:null}];
else if(route.request().method()==='POST'&&u.pathname.endsWith('/documents')){({content,name}=route.request().postDataJSON());data=doc();}
else if(u.pathname.endsWith('/preview'))data={name,kind:'text',status:'ready',page_count:1};
else if(u.pathname.endsWith('/content')&&route.request().method()==='PUT'){content=route.request().postDataJSON().content;data=doc();}
else if(u.pathname.endsWith('/content')||u.pathname.includes('/pages/'))data={content};
return route.fulfill({json:data});}
if(process.env.LIVE_ORIGIN)return route.continue();
const file=u.pathname.startsWith('/static/dist/')?path.join(dist,u.pathname.slice('/static/dist/'.length)):path.join(dist,'index.html');
if(!fs.existsSync(file))return route.fulfill({status:404,body:''});
return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});
});
await page.goto(origin+'/knowledge');
await page.getByRole('button',{name:'展开',exact:true}).click();
await page.getByRole('button',{name:'展开资源管理器',exact:true}).click();
await page.locator('.folder-tree').waitFor();
assert.ok(await page.locator('.folder-tree .tree-root').isVisible());
await page.locator('.folder-tree .tree-item').filter({hasText:'资源管理器测试文件夹'}).locator('.tree-folder').click();
await page.locator('.folder-tree .tree-root').click();
assert.equal(await page.evaluate(()=>document.documentElement.dataset.colorTheme),'glass');
assert.deepEqual(await page.locator('.toolbar-actions button').allTextContents(),['新建文件夹','创建文本文档','上传文件']);
await page.getByRole('button',{name:'新建文件夹',exact:true}).click();
const folderInput=page.getByPlaceholder('请输入文件夹名称');
await folderInput.fill('新建文件夹');
await folderInput.blur();
assert.equal(await folderInput.evaluate(el=>getComputedStyle(el).borderStyle),'solid');
assert.equal(await folderInput.evaluate(el=>getComputedStyle(el).borderWidth),'1px');
await folderInput.focus();
const inputStyles=await folderInput.evaluate(el=>({outline:getComputedStyle(el).outlineWidth,border:getComputedStyle(el).borderColor,bg:getComputedStyle(el).backgroundColor}));
assert.equal(inputStyles.outline,'2px');
assert.notEqual(inputStyles.bg,'rgba(0, 0, 0, 0)');
await page.screenshot({path:'/tmp/folder-glass-'+width+'-'+appearance+'.png'});
await page.locator('.resource-editor').getByRole('button',{name:'取消',exact:true}).click();
await page.getByRole('button',{name:'创建文本文档',exact:true}).click();
await page.locator('.toastui-editor-ww-container').waitFor();
for(const selector of ['.markdown-editor','.toastui-editor-main','.toastui-editor-ww-container']) assert.equal(await page.locator(selector).evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(255, 255, 255)',selector);
await page.screenshot({path:'/tmp/editor-glass-'+width+'-'+appearance+'.png'});
await page.getByPlaceholder('例如：笔记.txt 或 说明.md').fill('发布验证.md');
const ed=()=>page.locator('.toastui-editor-ww-container [contenteditable=true]');
await ed().click();await page.keyboard.insertText('发布包正文输入验证');
await page.getByRole('button',{name:'创建文档',exact:true}).click();
await page.getByText('发布验证.md',{exact:true}).first().click();
await page.getByRole('button',{name:'编辑',exact:true}).click();
await ed().click();await page.keyboard.insertText('再次编辑');
await page.getByRole('button',{name:'保存',exact:true}).click();
await page.getByRole('button',{name:'编辑',exact:true}).waitFor();
assert.ok(content.includes('再次编辑'));assert.ok(content.includes('发布包正文输入验证'));
assert.ok((await page.locator('.markdown-page').innerText()).includes('再次编辑'));
assert.deepEqual(errors,[]);
await page.getByRole('button',{name:'关闭预览',exact:true}).click();
// Non-Markdown text files use the textarea; shared theme rules must not tint it.
name='发布验证.csv';
await page.reload();
await page.getByRole('button',{name:'展开',exact:true}).click();
await page.getByRole('button',{name:'展开资源管理器',exact:true}).click();
await page.getByText(name,{exact:true}).first().click();
await page.getByRole('button',{name:'编辑',exact:true}).click();
assert.equal(await page.locator('.plain-editor').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(255, 255, 255)');
assert.equal(await page.locator('.plain-editor').evaluate(el=>getComputedStyle(el).color),'rgb(31, 41, 55)');
await page.getByRole('button',{name:'关闭编辑器',exact:true}).click();
await page.getByRole('button',{name:'关闭预览',exact:true}).click();
await page.locator('.folder-tree').waitFor();
await page.screenshot({path:'/tmp/textdoc-restored-explorer.png'});
console.log('PASS glass folder input / white editor / button order / create → edit → save',origin,width,appearance); await page.close(); }
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
