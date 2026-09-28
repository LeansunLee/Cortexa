const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const origin = process.env.LIVE_ORIGIN || 'http://agent-checkbox.local';
const dist = path.resolve(__dirname, '../../src/agentdevstu/web/static/dist');

(async () => {
  const { themeVariables } = await import('../src/utils/theme.js');
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    let savedBudget = null;
    const workspaceBudget = {
      duration: 180, llm_calls: 6, tool_calls: 10, tool_iterations: 5, web_calls: 3,
      agent_calls: 3, agent_depth: 1, context_tokens: 64000, output_tokens: 16384,
      max_steps: 24, max_replans: 1, max_failures: 2, max_collaborators: 3,
    };
    page.on('pageerror', error => errors.push(error.message));
    await page.route(origin + '/**', async route => {
      const url = new URL(route.request().url());
      if (url.pathname.startsWith('/api/')) {
        let data = [];
        if (url.pathname === '/api/auth/me') data = {
          id: 'u', username: 'u', display_name: '验收', system_permissions: [],
          memberships: [{ workspace_id: 'ws', permissions: ['agent.read', 'agent.update'] }],
        };
        else if (url.pathname === '/api/workspaces') data = [{ id: 'ws', name: '验收空间' }];
        else if (url.pathname === '/api/agents') data = [{
          id: 'agent-1', name: '测试 Agent', status: 'active', agent_type: 'llm',
          current_version: 1, tags: [], collaboration: { allow_incoming: true, discoverable: true },
        }];
        else if (url.pathname === '/api/agents/models/available') data = { providers: [], models: [] };
        else if (url.pathname === '/api/agents/agent-1/runtime-budget') {
          if (route.request().method() === 'PUT') savedBudget = route.request().postDataJSON().budget;
          data = { budget: savedBudget, workspace_budget: workspaceBudget, effective_budget: { ...workspaceBudget, ...(savedBudget || {}) } };
        }
        return route.fulfill({ json: data });
      }
      if (process.env.LIVE_ORIGIN) return route.continue();
      const file = url.pathname.startsWith('/static/dist/')
        ? path.join(dist, url.pathname.slice('/static/dist/'.length)) : path.join(dist, 'index.html');
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
    });
    await page.goto(origin + '/agents');
    await page.locator('.agent-card').first().click();
    await page.locator('.nav-item').filter({ hasText: '模型配置' }).click();
    await page.getByRole('button', { name: '目标协作权限' }).click();
    await page.getByRole('option', { name: /Ask Before Collaboration/ }).click();
    assert.match(await page.getByRole('button', { name: '目标协作权限' }).innerText(), /Ask Before Collaboration/);
    await page.getByRole('heading', { name: /Runtime Budget/ }).waitFor();
    const context = page.locator('.agent-budget-field').filter({ hasText: 'Max Context Tokens' });
    assert.equal(await context.locator('input[type="number"]').inputValue(), '64000');
    await context.locator('input[type="checkbox"]').check();
    await context.locator('input[type="number"]').fill('48000');
    const saved = page.waitForResponse(response => response.url().endsWith('/runtime-budget') && response.request().method() === 'PUT');
    await page.getByRole('button', { name: /Save Runtime Budget/ }).click();
    await saved;
    assert.deepEqual(savedBudget, { context_tokens: 48000 });
    for (const finish of ['clear', 'frosted']) {
      const theme = { value: '#8B38FF', mode: 'glass', finish, glow: 20 };
      await page.evaluate(({ finish, vars }) => {
        const root = document.documentElement;
        root.dataset.colorTheme = 'glass';
        root.dataset.glassFinish = finish;
        root.dataset.theme = 'light';
        root.style.colorScheme = 'light';
        for (const [key, value] of Object.entries(vars)) root.style.setProperty(key, value);
      }, { finish, vars: themeVariables(theme) });
      await page.waitForTimeout(220);
      const material = await page.evaluate(() => {
        const card = getComputedStyle(document.querySelector('.agent-budget-card'));
        const select = getComputedStyle(document.querySelector('.collaboration-autonomy-select .search-select-trigger'));
        return { cardBg: card.backgroundColor, cardBlur: card.backdropFilter, selectBg: select.backgroundColor, selectBlur: select.backdropFilter };
      });
      assert.match(material.cardBg, /\/ 0\.|rgba\([^)]*, 0\./);
      assert.match(material.cardBlur, /blur\(/);
      assert.match(material.selectBg, /\/ 0\.|rgba\([^)]*, 0\./, JSON.stringify(material));
      assert.match(material.selectBlur, /blur\(/);
    }
    const checkboxes = page.locator('.section .form-group input[type="checkbox"]');
    assert.equal(await checkboxes.count(), 2);
    for (const box of await checkboxes.all()) {
      const bounds = await box.boundingBox();
      assert.ok(bounds.width >= 14 && bounds.width <= 20, `checkbox width: ${bounds.width}`);
      assert.ok(bounds.height >= 14 && bounds.height <= 20, `checkbox height: ${bounds.height}`);
      const label = await box.locator('..').boundingBox();
      assert.ok(bounds.x - label.x < 8, 'checkbox remains beside its label');
    }
    await checkboxes.first().uncheck();
    assert.equal(await checkboxes.first().isChecked(), false);
    if (process.env.SCREENSHOT_PATH) await page.screenshot({ path: process.env.SCREENSHOT_PATH, fullPage: true });
    assert.deepEqual(errors, []);
    console.log('PASS: Agent budget override saves; collaboration checkboxes remain compact and operable');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
