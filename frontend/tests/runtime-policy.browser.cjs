// Built UI with isolated API responses; verifies Workspace controls and permission gating.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const { themeVariables } = await import('../src/utils/theme.js');
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const root = path.resolve(__dirname, '../../src/agentdevstu/web/static/dist');
    const origin = process.env.LIVE_ORIGIN || 'http://runtime-policy.local';
    const errors = [];
    let manage = true;
    let saved = null;
    const defaults = {
      duration: 180, llm_calls: 6, tool_calls: 10, tool_iterations: 5,
      web_calls: 3, agent_calls: 3, agent_depth: 1, context_tokens: 32000,
      output_tokens: 16384, max_steps: 24, max_replans: 1, max_failures: 2,
      max_collaborators: 3,
    };
    const limits = { ...defaults, llm_calls: 12, agent_calls: 5, max_collaborators: 5, output_tokens: 32768 };
    page.on('pageerror', error => errors.push(error.message));
    await page.route(origin + '/**', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname.startsWith('/api/')) {
        let data = [];
        if (url.pathname === '/api/auth/me') data = {
          id: 'u', username: 'u', display_name: '验收', system_permissions: [],
          memberships: [{ workspace_id: 'ws', permissions: manage ? ['workspace.manage'] : [] }],
        };
        else if (url.pathname === '/api/workspaces') data = [{ id: 'ws', name: '测试空间' }];
        else if (url.pathname === '/api/workspaces/ws') data = { id: 'ws', name: '测试空间' };
        else if (url.pathname === '/api/workspaces/ws/runtime-policy') {
          if (request.method() === 'PUT') saved = request.postDataJSON();
          data = {
            version: 1, budget: saved?.budget || null,
            collaboration: saved?.collaboration || null, platform_defaults: defaults, platform_limits: limits,
          };
        }
        return route.fulfill({ json: data });
      }
      if (process.env.LIVE_ORIGIN) return route.continue();
      const file = url.pathname.startsWith('/static/dist/')
        ? path.join(root, url.pathname.slice(13)) : path.join(root, 'index.html');
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
    });
    await page.goto(origin + '/workspaces');
    await page.getByText('Execution Budget').waitFor();
    assert.equal(await page.locator('.budget-field').count(), 13);
    await page.locator('.budget-field').filter({ hasText: 'Max LLM Calls' }).locator('input[type=number]').fill('10');
    await page.locator('.budget-field').filter({ hasText: 'Max Collaborators' }).locator('input[type=number]').fill('5');
    const outputInput = page.locator('.budget-field').filter({ hasText: 'Max Output Tokens' }).locator('input[type=number]');
    await outputInput.fill('163840');
    assert.equal(await outputInput.getAttribute('aria-invalid'), 'true');
    assert.match(await page.locator('.budget-field').filter({ hasText: 'Max Output Tokens' }).innerText(), /0–32768/);
    await page.getByRole('button', { name: /Save Runtime Policy/ }).click();
    assert.equal(saved, null, 'invalid budget must not be submitted');
    await outputInput.fill('16384');
    await page.getByRole('button', { name: '默认协作模式' }).click();
    await page.getByRole('option', { name: /Ask Before Collaboration/ }).click();
    await page.getByRole('button', { name: /Save Runtime Policy/ }).click();
    await page.waitForFunction(() => document.querySelector('.budget-field input')?.value !== '');
    assert.equal(saved.budget.llm_calls, 10);
    assert.equal(saved.budget.max_collaborators, 5);
    assert.equal(saved.collaboration.max_autonomy, 'ASK_BEFORE_COLLABORATION');
    await page.getByRole('checkbox', { name: '累计输出额度不限' }).check();
    assert.equal(await outputInput.isDisabled(), true);
    await page.getByRole('button', { name: /Save Runtime Policy/ }).click();
    assert.equal(saved.budget.output_tokens, null);
    await page.reload();
    await page.getByText('Execution Budget').waitFor();
    assert.equal(await page.getByRole('checkbox', { name: '累计输出额度不限' }).isChecked(), true);
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
      const style = await page.evaluate(() => {
        const get = selector => getComputedStyle(document.querySelector(selector));
        return {
          titleSize: get('.runtime-section-title').fontSize,
          triggerSize: get('.runtime-collaboration-field .search-select-trigger').fontSize,
          triggerBg: get('.runtime-collaboration-field .search-select-trigger').backgroundColor,
          triggerBlur: get('.runtime-collaboration-field .search-select-trigger').backdropFilter,
          cardBg: get('.runtime-card').backgroundColor,
          cardBlur: get('.runtime-card').backdropFilter,
          fieldBorder: get('.budget-field input').borderColor,
          fieldShadow: get('.budget-field input').boxShadow,
        };
      });
      assert.equal(style.titleSize, '14px');
      assert.equal(style.triggerSize, '14px');
      assert.match(style.triggerBg, /\/ 0\.|rgba\([^)]*, 0\./);
      assert.match(style.cardBg, /\/ 0\.|rgba\([^)]*, 0\./);
      assert.match(style.triggerBlur, /blur\(/, JSON.stringify(style));
      assert.match(style.cardBlur, /blur\(/);
      assert.notEqual(style.fieldBorder, 'rgba(0, 0, 0, 0)');
      assert.notEqual(style.fieldShadow, 'none');
      await page.getByRole('button', { name: '默认协作模式' }).click();
      const menu = await page.getByRole('listbox', { name: '默认协作模式' }).evaluate(node => {
        const style = getComputedStyle(node);
        return { background: style.backgroundColor, blur: style.backdropFilter };
      });
      assert.match(menu.background, /\/ 0\.|rgba\([^)]*, 0\./);
      assert.match(menu.blur, /blur\(/);
      await page.keyboard.press('Escape');
    }
    if (process.env.SCREENSHOT_PATH) await page.screenshot({ path: process.env.SCREENSHOT_PATH, fullPage: true });
    manage = false;
    await page.reload();
    assert.equal(await page.locator('.runtime-card').count(), 0);
    assert.deepEqual(errors, []);
    console.log('PASS: Workspace Runtime Policy controls, save payload, permission gating');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
