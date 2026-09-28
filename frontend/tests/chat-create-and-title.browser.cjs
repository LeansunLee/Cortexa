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
    await page.route(origin + '/**', async route => {
      const req = route.request()
      const pathname = new URL(req.url()).pathname
      if (pathname.startsWith('/api/')) {
        let data = []
        if (pathname === '/api/auth/me') data = { id: 'user', display_name: '测试用户', username: 'user', system_permissions: [], memberships: [{ workspace_id: 'ws', permissions: ['agent.use', 'agent.read', 'agent.operate'] }] }
        else if (pathname === '/api/workspaces') data = [{ id: 'ws', name: '测试空间' }]
        else if (pathname === '/api/auth/agents') data = agents
        else if (pathname === '/api/collaboration/agents') data = agents
        else if (pathname === '/api/config') data = { conversation_debug_enabled: false }
        else if (pathname === '/api/me/conversation-debug') data = { allowed: false, enabled: false }
        else if (pathname === '/api/conversations' && req.method() === 'GET') data = conversations
        else if (pathname === '/api/conversations' && req.method() === 'POST') {
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
        } else if (pathname.endsWith('/messages')) data = []
        else if (pathname.endsWith('/goal-options')) data = { enabled: false, collaboration_mode: 'EXPLICIT_ONLY', allowed_collaboration_modes: ['EXPLICIT_ONLY'] }
        return route.fulfill({ json: data })
      }
      if (process.env.LIVE_ORIGIN) return route.continue()
      const file = pathname.startsWith('/static/dist/') ? path.join(root, pathname.slice(13)) : path.join(root, 'index.html')
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' })
    })

    await page.goto(origin + '/chat')
    await page.locator('.conv-item').first().click()
    assert.equal(await page.getByText('运维当前 Agent').count(), 0)
    const headerTitle = page.locator('.chat-header .chat-conv-title')
    await headerTitle.click()
    const titleInput = page.getByRole('textbox', { name: '对话标题' })
    await titleInput.waitFor()
    assert.equal(await titleInput.inputValue(), '最近咋样')
    await titleInput.fill('改过的标题')
    await titleInput.press('Enter')
    await page.getByRole('button', { name: '改过的标题', exact: true }).first().waitFor()
    assert.deepEqual(renamed, [{ id: 'existing', title: '改过的标题' }])

    await page.getByRole('button', { name: '新建对话' }).click()
    await page.locator('.new-chat-agent').first().waitFor()
    assert.equal(await page.locator('.new-chat-agent').count(), 3)
    assert.deepEqual(await page.locator('.new-chat-agent-name').allInnerTexts(), agents.map(agent => agent.name))
    assert.equal(await page.locator('.new-chat-form .search-select').count(), 0)
    assert.equal(await page.locator('.new-chat-form input:not([type="radio"])').count(), 0)
    assert.equal(await page.getByText('运维当前 Agent').count(), 0)
    await page.screenshot({ path: '/tmp/cortexa-new-chat-agents.png' })
    await page.locator('.new-chat-agent').filter({ hasText: '销售 Agent' }).click()
    assert.equal(await page.locator('.new-chat-agent.selected').count(), 1)
    await page.getByRole('button', { name: '创建', exact: true }).click()
    await page.getByRole('button', { name: '销售 Agent', exact: true }).first().waitFor()
    assert.deepEqual(created, [{ agent_id: 'sales' }])
    assert.equal(await headerTitle.innerText(), '销售 Agent')
    await headerTitle.click()
    assert.equal(await titleInput.inputValue(), '')
    await titleInput.fill('暂不保存')
    await titleInput.press('Escape')
    assert.equal(await headerTitle.innerText(), '销售 Agent')
    await headerTitle.click()
    await titleInput.fill('销售分析')
    await titleInput.blur()
    await page.getByRole('button', { name: '销售分析', exact: true }).first().waitFor()
    assert.deepEqual(renamed.at(-1), { id: 'new-1', title: '销售分析' })

    await page.setViewportSize({ width: 600, height: 850 })
    await page.getByRole('button', { name: '新建对话' }).click()
    await page.locator('.new-chat-agent').first().waitFor()
    assert.equal(await page.locator('.new-chat-agent').count(), 3)
    const bounds = await page.locator('.new-chat-form').boundingBox()
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 601)
    await page.screenshot({ path: '/tmp/cortexa-new-chat-agents-narrow.png' })
    assert.deepEqual(errors, [])
    console.log('PASS: usable Agents are visible, title is omitted at creation, and header click renames with Enter/blur/Escape')
  } finally {
    await browser.close()
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
