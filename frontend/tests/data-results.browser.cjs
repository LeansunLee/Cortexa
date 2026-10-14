const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
;(async () => {
 const browser = await chromium.launch({headless:true,channel:'chrome'})
 try {
  for (const [width, dark] of [[1280,false],[390,true]]) {
   const page = await browser.newPage({viewport:{width,height:900}})
   const origin=process.env.LIVE_ORIGIN || 'http://prompt.local'
   const root=path.resolve(__dirname,'../../src/cortexa/web/static/dist')
   const errors=[];page.on('pageerror',e=>errors.push(e.message))
   let reads=0, reject=true
   const step={status:'runtime_done',message:'品牌部 · 返回 511 条数据；状态 SUCCESS',tool:'action-1'}
   await page.route(origin+'/**',async route=>{
    const u=new URL(route.request().url());let data=[]
    if(u.pathname.startsWith('/api/')) {
     if(u.pathname==='/api/auth/me') data={id:'test',display_name:'测试',system_permissions:[],memberships:[{workspace_id:'ws',permissions:['agent.use','agent.read','conversation.debug']}]}
     else if(u.pathname==='/api/workspaces') data=[{id:'ws',name:'测试'}]
     else if(['/api/auth/agents','/api/collaboration/agents'].includes(u.pathname)) data=[{id:'main',name:'Peter',agent_type:'llm',status:'active'}]
     else if(u.pathname==='/api/config') data={conversation_debug_enabled:true}
     else if(u.pathname==='/api/me/conversation-debug') data={allowed:true,enabled:true}
     else if(u.pathname==='/api/conversations') data=[{id:'conv',agent_id:'main',agent_name:'Peter',title:'检查请求'}]
     else if(u.pathname.endsWith('/goal-options')) data={enabled:true,collaboration_mode:'AUTONOMOUS',allowed_collaboration_modes:['AUTONOMOUS']}
     else if(u.pathname.endsWith('/messages')) data=[{id:'a1',role:'assistant',content:'报告已完成',metadata_json:{steps:[step]}}]
     else if(u.pathname.endsWith('/data-results/action-1')) {
      reads++
      if(reject){reject=false;return route.fulfill({status:503,json:{detail:'暂时无法读取'}})}
      const offset=Number(u.searchParams.get('offset') || 0)
      data={status:'PARTIAL',columns:['车型','数量'],rows:Array.from({length:Math.min(50,511-offset)},(_,i)=>({'车型':'<script>window.promptXss=true</script>','数量':offset+i})),returned_rows:511,row_count:900,truncated:true}
     }
     return route.fulfill({json:data})
    }
    if(process.env.LIVE_ORIGIN)return route.continue()
    const file=u.pathname.startsWith('/static/dist/')?path.join(root,u.pathname.slice(13)):path.join(root,'index.html')
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'})
   })
   await page.goto(origin+'/chat')
   await page.locator('.conv-title-text').getByText('检查请求',{exact:true}).click()
   await page.locator('.runtime-timeline summary').first().click()
   await page.getByRole('button',{name:'查看数据',exact:true}).waitFor()
   assert.equal(reads,0,'request is fetched only on click')
   await page.getByRole('button',{name:'查看数据',exact:true}).click()
   const dialog=page.getByRole('dialog')
   await dialog.getByText('暂时无法读取',{exact:false}).waitFor()
   await dialog.getByRole('button',{name:'重试'}).click()
   await dialog.getByText('结果已截断',{exact:false}).waitFor()
   assert.equal(reads,2)
   await dialog.getByRole('button',{name:'下一页'}).click()
   await dialog.getByText('51–100 / 511',{exact:true}).waitFor()
   assert.equal(reads,3)
   assert.equal(await page.evaluate(()=>window.promptXss),undefined)
   await page.evaluate(dark=>{document.documentElement.dataset.colorTheme='glass';document.documentElement.dataset.theme=dark?'dark':'light'},dark)
   const box=await dialog.boundingBox()
   assert.ok(box.x>=0 && box.x+box.width<=width && box.height<=900*.86)
   await page.screenshot({path:`/tmp/cortexa-data-results-${width}.png`})
   await page.keyboard.press('Escape')
   assert.equal(await dialog.isVisible(),false)
   assert.equal(await page.getByRole('button',{name:'查看数据',exact:true}).evaluate(el=>el===document.activeElement),true)
   await page.reload()
   await page.locator('.conv-title-text').getByText('检查请求',{exact:true}).click()
   await page.locator('.runtime-timeline summary').first().click()
   assert.equal(await page.getByRole('button',{name:'查看数据',exact:true}).count(),1)
   assert.deepEqual(errors,[])
   await page.close()
  }
  console.log('PASS data results: history, lazy read, retry, paging, escaped records, Escape/focus and narrow layout')
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1})
