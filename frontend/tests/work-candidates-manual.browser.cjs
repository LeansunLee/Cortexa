// Exercise the built chat UI with isolated API responses; no real work is created.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

;(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' })
  try {
    const page = await browser.newPage({ viewport: { width: 1360, height: 900 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    const origin = process.env.LIVE_ORIGIN || 'http://work-candidates.local'
    const root = path.resolve(__dirname, '../../src/cortexa/web/static/dist')
    const suggestions = Array.from({ length: 4 }, (_, index) => ({
      id: `candidate-${index + 1}`, message_id: 'assistant-1', status: 'candidate',
      title: `建议工作 ${index + 1}`, goal: `执行目标 ${index + 1}`, priority: 'P2',
    }))
    let candidates = suggestions
    let failCandidates = false
    const messages = [{ id: 'assistant-1', role: 'assistant', content: '可以推进以下工作。', metadata_json: { work_extracted: true } }]
    const created = []
    await page.route(origin + '/**', async route => {
      const req = route.request()
      const url = new URL(req.url())
      const pathname = url.pathname
      if (pathname.startsWith('/api/')) {
        let data = []
        if (pathname === '/api/auth/me') data = { id: 'test', display_name: '测试用户', username: 'test', system_permissions: [], memberships: [{ workspace_id: 'ws', permissions: ['agent.use', 'agent.read'] }] }
        else if (pathname === '/api/workspaces') data = [{ id: 'ws', name: '测试空间' }]
        else if (pathname === '/api/auth/agents' || pathname === '/api/collaboration/agents') data = [{ id: 'agent', name: 'Peter', agent_type: 'llm', status: 'active' }]
        else if (pathname === '/api/config') data = { conversation_debug_enabled: false }
        else if (pathname === '/api/me/conversation-debug') data = { allowed: false, enabled: false }
        else if (pathname === '/api/conversations') data = [{ id: 'conv', agent_id: 'agent', agent_name: 'Peter', title: '制定10月销售计划' }]
        else if (pathname === '/api/conversations/conv/messages') data = messages
        else if (pathname === '/api/conversations/conv/goal-options') data = { enabled: false }
        else if (pathname === '/api/conversations/conv/work-candidates') {
          if (failCandidates) return route.fulfill({ status: 503, json: { detail: 'unavailable' } })
          data = candidates
        } else if (pathname === '/api/works/members') data = [{ id: 'test', name: '测试用户' }, { id: 'owner', name: '执行人' }]
        else if (pathname === '/api/works/assignee-recommendations') data = []
        else if (pathname === '/api/works' && req.method() === 'POST') {
          created.push(req.postDataJSON())
          return route.fulfill({ status: 201, json: { id: `created-${created.length}`, ...created.at(-1), status: 'pending' } })
        }
        return route.fulfill({ json: data })
      }
      if (process.env.LIVE_ORIGIN) return route.continue()
      const file = pathname.startsWith('/static/dist/') ? path.join(root, pathname.slice(13)) : path.join(root, 'index.html')
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' })
    })

    await page.goto(origin + '/chat')
    await page.locator('.conv-item').first().click()
    await page.getByRole('heading', { name: '发现 4 项可执行工作' }).waitFor()
    assert.equal(await page.locator('.candidate-grid > article').count(), 5)
    const manual = page.locator('.manual-card')
    const candidateSize = await page.locator('.candidate-grid > article').first().boundingBox()
    const manualSize = await manual.boundingBox()
    assert.ok(Math.abs(candidateSize.height - manualSize.height) <= 1, 'manual card matches suggestion height')
    await manual.scrollIntoViewIfNeeded()
    await page.screenshot({ path: '/tmp/cortexa-manual-work-desktop.png' })
    await manual.getByRole('button', { name: '新建工作' }).click()
    const dialog = page.getByRole('dialog', { name: '新建工作' })
    await dialog.waitFor()
    await dialog.getByLabel('标题').fill('自己补充的工作')
    await dialog.getByLabel('执行目标').fill('完成手动创建流程')
    await dialog.getByRole('button', { name: '负责人', exact: true }).click()
    await page.getByRole('option', { name: '执行人' }).click()
    await dialog.getByRole('button', { name: '创建并派发' }).click()
    await dialog.waitFor({ state: 'hidden' })
    assert.equal(created.length, 1)
    assert.equal(created[0].title, '自己补充的工作')
    assert.equal(created[0].assignee_id, 'owner')
    assert.equal(await manual.getByRole('button', { name: '新建工作' }).count(), 1)
    assert.equal(await page.locator('.candidate-grid > article').count(), 5)
    await manual.getByRole('button', { name: '新建工作' }).click()
    await dialog.waitFor()
    assert.equal(await dialog.getByLabel('标题').inputValue(), '')
    await dialog.getByRole('button', { name: '关闭' }).click()

    await page.setViewportSize({ width: 600, height: 900 })
    const mobileCard = await manual.boundingBox()
    assert.ok(mobileCard.x >= 0 && mobileCard.x + mobileCard.width <= 601, 'manual card fits narrow viewport')
    await manual.scrollIntoViewIfNeeded()
    await page.screenshot({ path: '/tmp/cortexa-manual-work-narrow.png' })

    candidates = []
    await page.reload()
    await page.locator('.conv-item').first().click()
    await page.getByRole('heading', { name: '创建可执行工作' }).waitFor()
    assert.equal(await page.locator('.candidate-grid > article').count(), 1)
    await manual.getByRole('button', { name: '新建工作' }).click()
    await dialog.waitFor()
    await dialog.getByRole('button', { name: '关闭' }).click()

    messages.push({ id: 'assistant-2', role: 'assistant', content: '下一轮也可以安排工作。', metadata_json: { work_extracted: true } })
    await page.reload()
    await page.locator('.conv-item').first().click()
    await page.getByText('下一轮也可以安排工作。').waitFor()
    assert.equal(await page.locator('.manual-card').count(), 2, 'each assistant reply offers manual creation')
    messages.pop()

    failCandidates = true
    await page.reload()
    await page.locator('.conv-item').first().click()
    await page.getByText('工作建议暂不可用').waitFor()
    await manual.getByRole('button', { name: '新建工作' }).click()
    await dialog.waitFor()
    await dialog.getByRole('button', { name: '关闭' }).click()
    assert.deepEqual(errors, [])
    console.log('PASS: manual work card appears on each reply, with or without suggestions, after save, and when suggestions are unavailable')
  } finally {
    await browser.close()
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
