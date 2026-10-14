// Built chat UI with isolated API responses; verifies new conversation and inline title editing.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

;(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' })
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    const origin = process.env.LIVE_ORIGIN || 'http://chat-create.local'
    const root = path.resolve(__dirname, '../../src/cortexa/web/static/dist')
    const agents = [
      { id: 'peter', name: 'Peter', avatar: '/static/avatars/ceo.svg' },
      { id: 'sales', name: '销售 Agent', avatar: '/static/avatars/sales.svg' },
      { id: 'analysis', name: '数据分析 Agent' },
    ]
    const conversations = [{ id: 'existing', agent_id: 'peter', agent_name: 'Peter', title: '最近咋样' }]
    const created = []
    const renamed = []
    const sent = []
    const savedModes = {}
    let rejectCreation = false
    const fixture = process.env.DECISION_FIXTURE ? JSON.parse(fs.readFileSync(process.env.DECISION_FIXTURE,'utf8')) : {
      question:{id:'q1',agent_name:'数据分析部门',status:'pending',question:'10月销售计划先做哪个方向？',options:['销量目标分解','车型结构计划','发货与回款节奏','经销商行动计划','行业竞品对标'],multi_select:false,allow_free_text:true},
      messages:[{id:'reply',role:'assistant',content:'请确认销售计划方向',metadata_json:{goal_id:'goal',goal_status:'WAITING',user_question:{id:'q1',status:'pending'}}}],
      goal:{goal_id:'goal',status:'WAITING',reason:'user_decision_required'}
    }
    fixture.messages[0].metadata_json.user_question = fixture.question
    fixture.goal.user_question ||= fixture.question
    let failQuestion = false
    let pendingQuestion = fixture.question
    let answers = []
    let rejectAnswer = true
    await page.route(origin + '/**', async route => {
      const req = route.request()
      const pathname = new URL(req.url()).pathname
      if (pathname.startsWith('/api/')) {
        let data = []
        if (pathname.endsWith('/question')) { if(failQuestion) return route.fulfill({status:503,json:{detail:'问题接口暂时失败'}}); data = {question:pendingQuestion} }
        else if (pathname.includes('/goals/') && req.method()==='GET') data = fixture.goal
        else if (pathname.endsWith('/question/q1/answer')) {
          if (rejectAnswer) { rejectAnswer=false;return route.fulfill({status:503,json:{detail:'提交未接收，请重试'}}) }
          answers.push(req.postDataJSON())
          await new Promise(resolve=>setTimeout(resolve,150))
          pendingQuestion = { ...pendingQuestion,id:'q2',question:'还需要确认区域',options:['杭州','全国'],multi_select:true }
          return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({type:'user_question',question:pendingQuestion})+'\n\ndata: '+JSON.stringify({type:'done',id:'r1',content:'请确认区域',user_question:pendingQuestion})+'\n\n'})
        }
        else if (pathname.endsWith('/question/q2/answer')) {
          answers.push(req.postDataJSON());pendingQuestion=null
          return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({type:'done',id:'r2',content:'已依据选择完成计划'})+'\n\n'})
        }
        else if (pathname === '/api/auth/me') data = { id: 'user', display_name: '测试用户', username: 'user', system_permissions: [], memberships: [{ workspace_id: 'ws', permissions: ['agent.use', 'agent.read', 'agent.operate'] }] }
        else if (pathname === '/api/workspaces') data = [{ id: 'ws', name: '测试空间' }]
        else if (pathname === '/api/auth/agents') data = agents
        else if (pathname === '/api/collaboration/agents') data = agents
        else if (pathname === '/api/config') data = { conversation_debug_enabled: false }
        else if (pathname === '/api/me/conversation-debug') data = { allowed: false, enabled: false }
        else if (pathname === '/api/collaboration/draft-options') data={enabled:true,collaboration_mode:'EXPLICIT_ONLY',allowed_collaboration_modes:['EXPLICIT_ONLY','ASK_BEFORE_COLLABORATION','AUTONOMOUS']}
        else if (pathname.endsWith('/collaboration-mode')) { savedModes[pathname.split('/')[3]]=req.postDataJSON().collaboration_mode;data={collaboration_mode:req.postDataJSON().collaboration_mode,allowed_collaboration_modes:['EXPLICIT_ONLY','ASK_BEFORE_COLLABORATION','AUTONOMOUS']} }
        else if (pathname.endsWith('/message-route')) data={use_goal:false}
        else if (pathname === '/api/conversations' && req.method() === 'GET') data = conversations
        else if (pathname === '/api/conversations' && req.method() === 'POST') {
          if (rejectCreation) { rejectCreation=false; return route.fulfill({status:503,json:{detail:'暂时不可用'}}) }
          await new Promise(resolve=>setTimeout(resolve,150))
          const payload = req.postDataJSON()
          created.push(payload)
          const agent = agents.find(item => item.id === payload.agent_id)
          data = { id: `new-${created.length}`, agent_id: agent.id, agent_name: agent.name, title: null }
          conversations.unshift(data)
        } else if (/^\/api\/conversations\/[^/]+$/.test(pathname) && req.method() === 'PATCH') {
          const id = pathname.split('/').at(-1)
          const title = req.postDataJSON().title
          renamed.push({ id, title })
          const conversation = conversations.find(item => item.id === id)
          conversation.title = title
          data = conversation
        } else if (pathname.endsWith('/messages/stream')) {
          sent.push({id:pathname.split('/')[3],content:req.postDataJSON().content})
          return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({type:'done',id:'reply',content:'已收到首条消息'})+'\n\n'})
        } else if (pathname.endsWith('/messages')) data = fixture.messages
        else if (pathname.endsWith('/goal-options')) data = { enabled: true, collaboration_mode: savedModes[pathname.split('/')[3]] || 'EXPLICIT_ONLY', allowed_collaboration_modes: ['EXPLICIT_ONLY','ASK_BEFORE_COLLABORATION','AUTONOMOUS'] }
        return route.fulfill({ json: data })
      }
      if (process.env.LIVE_ORIGIN) return route.continue()
      const file = pathname.startsWith('/static/dist/') ? path.join(root, pathname.slice(13)) : path.join(root, 'index.html')
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' })
    })

    await page.goto(origin + '/chat')
    await page.locator('.conv-item').first().click()
    const card = page.getByRole('form',{name:'待你决策'})
    await card.waitFor()
    assert.equal(await card.count(),1)
    assert.equal(await card.locator('input[type=radio]').count(),5)
    assert.equal(await page.locator('.chat-input').count(),0)
    assert.equal(await page.getByText('创建可执行工作',{exact:true}).count(),0)
    assert.equal(await card.getByRole('button',{name:'确认并继续'}).isDisabled(),true)
    for (const [theme,width] of [['light',1280],['dark',1280],['dark',600]]) {
      await page.setViewportSize({width,height:1000})
      await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme)
      await card.scrollIntoViewIfNeeded()
      const bounds=await card.boundingBox()
      assert.ok(bounds.x>=0 && bounds.x+bounds.width<=width+1)
      await page.screenshot({path:`/tmp/cortexa-decision-recovered-${theme}-${width}.png`})
    }
    failQuestion=true
    await page.reload()
    await page.locator('.conv-item').first().click()
    await card.waitFor()
    assert.equal(await card.locator('input[type=radio]').count(),5)
    assert.equal(await card.count(),1)
    assert.equal(await page.locator('.chat-input').count(),0)
    assert.deepEqual(errors,[])
    console.log('PASS saved question inline display, five options, no work cards, refresh recovery, question API outage fallback, responsive themes')
  } finally { await browser.close() }
})().catch(error=>{console.error(error);process.exit(1)})
