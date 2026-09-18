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
let workRows = [], listReads = 0, releaseList = null;
const permissions=['agent.use','agent.read','knowledge.manage','data.manage','config.manage','meeting.use'];
await page.route('http://tabs.local/**', async r=>{
 const u=new URL(r.request().url());
 if(u.pathname.startsWith('/api/')){
 let data=[];
 if(u.pathname==='/api/auth/me') data={id:'test',display_name:'测试用户',username:'test',system_permissions:permissions,memberships:[{workspace_id:'w1',permissions},{workspace_id:'w2',permissions}]};
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
await page.goto('http://tabs.local/works');
await page.getByRole('tab',{name:'工作',exact:true}).waitFor();
assert.equal(await page.locator('.app-page-heading-title, .app-page-heading-description').count(),0);
assert.equal(await page.locator('.app-page-heading').evaluate(el=>getComputedStyle(el).justifyContent),'flex-start');
// Manual creation stays on the list and reloads it; each detail gets its own tab.
for (const title of ['工作甲','工作乙']) {
 const readsBefore=listReads;
 await page.getByRole('button',{name:'＋ 新建工作',exact:true}).click();
 const dialog=page.getByRole('dialog');
 await dialog.getByLabel('标题',{exact:true}).fill(title);
 await dialog.getByLabel('执行目标',{exact:true}).fill('验证工作标签');
 await dialog.locator('select').nth(0).selectOption('owner');
 await dialog.getByRole('button',{name:'创建并派发'}).click();
 await dialog.waitFor({state:'hidden'});
 await page.locator('.work-card').filter({hasText:title}).waitFor();
 assert.equal(new URL(page.url()).pathname,'/works');
 assert.equal(await page.getByRole('tab').count(),1);
 assert.ok(listReads>readsBefore);
}
// Hold a filter request open and verify controls and cards remain mounted.
const oldFilter = await page.getByRole('combobox',{name:'状态筛选'}).elementHandle();
const oldCard = await page.locator('.work-card').first().elementHandle();
releaseList = true;
const filterRequest = page.waitForRequest(r => new URL(r.url()).pathname === '/api/works' && new URL(r.url()).searchParams.get('status') === 'todo');
await page.getByRole('combobox',{name:'状态筛选'}).selectOption('todo');
await filterRequest;
await page.waitForFunction(() => document.querySelector('.work-page').getAttribute('aria-busy') === 'true');
assert.equal(await oldFilter.evaluate(el => el.isConnected && el.getBoundingClientRect().height > 0), true);
assert.equal(await oldCard.evaluate(el => el.isConnected && el.getBoundingClientRect().height > 0), true);
assert.equal(await page.getByText('正在加载工作…',{exact:true}).isVisible(),false);
const resume = releaseList; releaseList = null; resume();
await page.waitForFunction(() => document.querySelector('.work-page').getAttribute('aria-busy') === 'false');
for (const title of ['工作甲','工作乙']) {
 await page.locator('.work-card').filter({hasText:title}).click();
 await page.getByRole('tab',{name:title,exact:true}).waitFor();
 assert.equal(await page.locator('[role="tabpanel"]:visible .app-page-heading-title').count(),0);
 await page.getByRole('tab',{name:'工作',exact:true}).click();
}
assert.equal(await page.getByRole('tab').count(),3);
await page.locator('.work-card').filter({hasText:'工作甲'}).click();
await page.getByRole('tab',{name:'工作甲',exact:true}).waitFor();
assert.equal(await page.getByRole('tab').count(),3);
await page.getByRole('button',{name:'关闭工作甲标签页'}).click();
await page.getByRole('tab',{name:'工作乙',exact:true}).waitFor();
await page.getByRole('button',{name:'关闭工作乙标签页'}).click();
await page.getByRole('tab',{name:'工作',exact:true}).waitFor();
await page.locator('.sidebar a[href="/knowledge"]').click();
await page.getByRole('tab',{name:'空间知识库',exact:true}).waitFor();
await page.getByRole('button',{name:'创建知识库',exact:true}).click();
await page.getByPlaceholder('例如：产品文档、业务手册').fill('暂存知识库');
await page.goBack();
assert.equal(await page.getByPlaceholder('例如：产品文档、业务手册').isVisible(),false);
await page.getByRole('tab',{name:'空间知识库',exact:true}).click();
assert.equal(await page.getByPlaceholder('例如：产品文档、业务手册').inputValue(),'暂存知识库');
await page.getByRole('button',{name:'取消',exact:true}).click();
await page.getByRole('tab',{name:'工作',exact:true}).click();
assert.equal(await page.getByRole('tab').count(),2);
const search=page.getByPlaceholder(/搜索/).first();
await search.fill('标签保留测试');
await page.getByRole('tab',{name:'空间知识库',exact:true}).click();
await page.getByRole('tab',{name:'工作',exact:true}).click();
assert.equal(await search.inputValue(),'标签保留测试');
await page.getByRole('tab',{name:'工作',exact:true}).press('ArrowRight');
assert.equal(await page.getByRole('tab',{name:'空间知识库',exact:true}).getAttribute('aria-selected'),'true');
await page.getByRole('button',{name:'关闭空间知识库标签页'}).click();
assert.equal(await page.getByRole('tab').count(),1);
assert.equal(await search.inputValue(),'标签保留测试');
await page.locator('.sidebar a[href="/knowledge"]').click();
await page.goBack();
assert.equal(await page.getByRole('tab',{name:'工作',exact:true}).getAttribute('aria-selected'),'true');
for(const scheme of ['light','dark']){
 await page.emulateMedia({colorScheme:scheme});
 await page.screenshot({path:`/tmp/agentdevstu-tabs-${scheme}.png`});
}
await page.setViewportSize({width:390,height:844});
assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
await page.screenshot({path:'/tmp/agentdevstu-tabs-mobile.png'});
await page.getByRole('combobox',{name:'切换工作空间'}).selectOption('w2');
await page.waitForTimeout(100);
assert.equal(await page.getByRole('tab').count(),1);
assert.equal(await search.inputValue(),'');
assert.deepEqual(errors,[]);
console.log('PASS: stable filtering, work title tabs, manual create refreshes list without navigation, independent work detail tabs, open, deduplicate, preserve input, switch, keyboard, close, history, theme, mobile, workspace reset; no browser errors');
await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
