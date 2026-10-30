import { chromium } from 'playwright'

const BASE = 'http://47.97.82.200:8000'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 1400 } })
// All API setup goes through context.request so the cookie jar is shared (needs the header on non-GET).
await context.request.post(`${BASE}/api/auth/login`, {
  data: { username: 'bugtest_bot', password: 'Bugtest#2026a' },
  headers: { 'x-requested-with': 'Cortexa' },
})
const ws = await (await context.request.get(`${BASE}/api/workspaces`)).json()
await context.addInitScript(id => localStorage.setItem('currentWorkspace', id), ws[0].id)

const page = await context.newPage()
await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' })
await page.waitForSelector('.feature-flags-card', { timeout: 15000 })
const rows = await page.locator('.feature-flags-card .feature-row').count()
console.log('feature rows rendered:', rows)
await page.screenshot({ path: 'settings_flags.png', fullPage: true })

// 切换一个开关并截图 toast 反馈（原生 checkbox 被样式隐藏，点击开关轨道）
await page.locator('.feature-flags-card .switch').nth(3).click()
await page.waitForTimeout(600)
await page.screenshot({ path: 'settings_flags_toggled.png', fullPage: false })
// 切回
await page.locator('.feature-flags-card .switch').nth(3).click()
await page.waitForTimeout(600)
console.log('toggle round-trip done')
await browser.close()
