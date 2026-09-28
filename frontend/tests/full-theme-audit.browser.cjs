// Inspect every router entry with isolated API responses. No server data is changed.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const origin = process.env.LIVE_ORIGIN || 'http://ui-audit.local'
const dist = path.resolve(__dirname, '../../src/cortexa/web/static/dist')
const output = process.env.AUDIT_OUTPUT || '/tmp/cortexa-full-theme-audit'
const permissions = [
  'agent.use', 'agent.read', 'agent.update', 'agent.operate', 'meeting.use', 'workspace.manage',
  'knowledge.manage', 'knowledge.use', 'data.manage', 'config.manage', 'workflows.manage',
  'members.manage', 'users.manage', 'roles.manage', 'audit.read',
]
const routes = [
  '/', '/works', '/works/audit-work', '/chat', '/meetings', '/my-agents',
  '/workspaces', '/agents', '/knowledge', '/data-sources', '/settings',
  '/personalization', '/access', '/model-usage', '/workflows', '/agent-operations/audit-agent',
  '/login', '/change-password',
]

;(async () => {
  const { themeVariables } = await import('../src/utils/theme.js')
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, channel: 'chrome' })
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  let requestedRoute = '/'
  page.on('pageerror', error => errors.push({ route: new URL(page.url()).pathname, message: error.message }))
  await page.route(origin + '/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.startsWith('/api/')) {
      if (url.pathname === '/api/auth/me' && requestedRoute === '/login') return route.fulfill({ status: 401, json: { detail: 'not authenticated' } })
      let data = []
      if (url.pathname === '/api/auth/me') data = {
        id: 'audit-user', username: 'audit', display_name: '界面审查', is_superadmin: true,
        must_change_password: requestedRoute === '/change-password',
        system_permissions: permissions,
        memberships: [{ workspace_id: 'ws', permissions, all_agents: true }],
      }
      else if (url.pathname === '/api/workspaces') data = [{ id: 'ws', name: '审查工作空间' }]
      else if (url.pathname === '/api/config') data = {}
      else if (url.pathname === '/api/me/conversation-debug') data = { allowed: false, enabled: false }
      else if (url.pathname.endsWith('/goal-options')) data = { enabled: true, agent_type: 'llm', collaboration_mode: 'EXPLICIT_ONLY', allowed_collaboration_modes: ['EXPLICIT_ONLY'] }
      else if (url.pathname.endsWith('/runtime-policy')) data = { version: 1, budget: null, collaboration: null, platform_defaults: {}, platform_limits: {}, effective_budget: {}, effective_collaboration_policy: 'EXPLICIT_ONLY', source_trace: {} }
      else if (url.pathname.endsWith('/runtime-budget')) data = { budget: null, effective_budget: {}, workspace_budget: {}, source_trace: {} }
      return route.fulfill({ json: data })
    }
    if (process.env.LIVE_ORIGIN) return route.continue()
    const file = url.pathname.startsWith('/static/dist/')
      ? path.join(dist, url.pathname.slice('/static/dist/'.length)) : path.join(dist, 'index.html')
    return route.fulfill({
      body: fs.readFileSync(file),
      contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html',
    })
  })
  const combinations = [
    ['solid', 'light', { value: '#3478D4' }], ['solid', 'dark', { value: '#3478D4' }],
    ['glass-clear', 'light', { value: '#8B38FF', mode: 'glass', finish: 'clear' }],
    ['glass-clear', 'dark', { value: '#8B38FF', mode: 'glass', finish: 'clear' }],
    ['glass-frosted', 'light', { value: '#8B38FF', mode: 'glass', finish: 'frosted' }],
    ['glass-frosted', 'dark', { value: '#8B38FF', mode: 'glass', finish: 'frosted' }],
    ['contrast', 'light', { value: '#2563EB', accent: '#F97316' }],
    ['gradient', 'dark', { value: '#2563EB', accent: '#9333EA', mode: 'gradient' }],
    ['texture', 'light', { value: '#49695E', mode: 'texture', texture: 'wood' }],
  ]
  const results = []
  try {
    await page.addInitScript(() => localStorage.setItem('currentWorkspace', 'ws'))
    for (const route of routes) {
      requestedRoute = route
      await page.goto(origin + route, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(140)
      for (const [theme, appearance, value] of combinations) {
        await page.evaluate(({ theme, appearance, value, vars }) => {
          const root = document.documentElement
          root.dataset.theme = appearance
          root.style.colorScheme = appearance
          root.dataset.colorTheme = value.mode || (value.accent ? 'contrast' : 'solid')
          if (value.mode === 'glass') root.dataset.glassFinish = value.finish
          else delete root.dataset.glassFinish
          Object.entries(vars).forEach(([key, token]) => root.style.setProperty(key, token))
        }, { theme, appearance, value, vars: themeVariables(value) })
        await page.waitForTimeout(220)
        const result = await page.evaluate(() => {
          const visible = element => { const r = element.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(element).visibility !== 'hidden' }
          const inspect = selector => {
            const element = [...document.querySelectorAll(selector)].find(visible)
            if (!element) return null
            const style = getComputedStyle(element)
            return { background: style.backgroundColor, color: style.color, blur: style.backdropFilter }
          }
          const overflowing = [...document.querySelectorAll('.page-content, .card, .panel, .modal, .dialog')]
            .filter(visible).filter(element => element.scrollWidth > element.clientWidth + 4)
            .slice(0, 5).map(element => ({ className: String(element.className), excess: element.scrollWidth - element.clientWidth }))
          return {
            route: location.pathname, heading: document.querySelector('main h1, main h2, main h3')?.textContent?.trim()?.slice(0, 80) || '',
            bodyWidth: document.body.scrollWidth, viewportWidth: innerWidth,
            card: inspect('.card, .agent-card, .workspace-card, .work-summary, .knowledge-card, .stat-card'),
            panel: inspect('.panel, .work-panel, .capability-panel'),
            workspaceSelect: inspect('.sidebar-workspace .search-select-trigger'),
            dialog: inspect('.modal, .dialog, [role=dialog]'),
            field: inspect('input:not([type=checkbox]), textarea, select'),
            overflow: overflowing,
          }
        })
        results.push({ requestedRoute: route, theme, appearance, ...result })
        if (['solid', 'glass-clear'].includes(theme) && ['/agents', '/workspaces', '/knowledge', '/personalization', '/chat'].includes(route)) {
          const name = (route.slice(1) || 'dashboard') + '-' + theme + '-' + appearance
          await page.screenshot({ path: path.join(output, name + '.png'), fullPage: true })
        }
      }
    }
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ results, errors }, null, 2))
    assert.equal(results.length, routes.length * combinations.length)
    assert.ok(results.every(result => result.route === result.requestedRoute), 'all routes render')
    assert.ok(results.every(result => result.bodyWidth <= result.viewportWidth + 4), 'no horizontal body overflow')
    assert.ok(results.every(result => result.card?.blur === 'none' || !result.card), 'base cards stay solid')
    assert.ok(results.every(result => !result.workspaceSelect || result.theme.startsWith('glass') || result.workspaceSelect.blur === 'none'), 'non-glass selectors do not blur')
    assert.equal(errors.length, 0, 'no page errors')
    console.log(`PASS: ${routes.length} routes × ${combinations.length} theme/appearance combinations; report ${output}/results.json`)
    if (errors.length) console.log('PAGE ERRORS:', JSON.stringify(errors))
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
