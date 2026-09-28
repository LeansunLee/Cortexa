const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const root = path.resolve(__dirname, '../../src/agentdevstu/web/static/dist');
    const origin = process.env.LIVE_ORIGIN || 'http://debug.local';
    let allowed = true;
    let enabled = false;
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route(origin + '/**', async route => {
      const request = route.request();
      const url = new URL(request.url());
      let data = [];
      if (url.pathname.startsWith('/api/')) {
        if (url.pathname === '/api/auth/me') data = {
          id: 'u', username: 'u', display_name: '验收', system_permissions: [],
          memberships: [{ workspace_id: 'ws', permissions: ['agent.use', ...(allowed ? ['conversation.debug'] : [])] }],
        };
        else if (url.pathname === '/api/workspaces') data = [{ id: 'ws', name: '测试空间' }];
        else if (url.pathname === '/api/conversations') data = [{ id: 'conv', agent_id: 'main', agent_name: '助手', title: '调试验收' }];
        else if (url.pathname === '/api/conversations/conv/messages') data = [
          { id: 'u1', role: 'user', content: '分析销售' },
          { id: 'a1', role: 'assistant', content: '已获得部分结果', metadata_json: { debug_trace: [
            { seq: 1, stage: 'runtime_goal', title: 'Effective Runtime Policy', timestamp: '2026-09-25T00:00:00Z', detail: {
              policy_source: { budget: { output_tokens: { source: 'Workspace' } }, collaboration: { source: 'Workspace' } },
              limits: { duration: 180, llm_calls: 6, output_tokens: 1000 }, collaboration_mode: 'AUTONOMOUS',
              budget_phase: 'FINALIZING', consumed_budget: { output_tokens: 750 }, remaining_budget: { output_tokens: 250 },
              finalization_reserve: { output_tokens: 250, llm_calls: 1 },
            } },
            { seq: 2, stage: 'runtime_goal', title: 'Goal stopped', timestamp: '2026-09-25T00:01:00Z', detail: {
              budget_phase: 'EXHAUSTED', consumed_budget: { output_tokens: 1000 }, remaining_budget: { output_tokens: 0 },
              finalization_reserve: { output_tokens: 250, llm_calls: 1 },
              budget_failure: { resource: 'output_tokens', current: 1000, limit: 1000, runtime: 'CHILD', agent_id: 'sales', phase: 'EXHAUSTED' },
            } },
          ] } },
        ];
        else if (url.pathname === '/api/conversations/conv/goal-options') data = { enabled: true };
        else if (url.pathname === '/api/auth/agents' || url.pathname === '/api/collaboration/agents') data = [{ id: 'main', name: '助手', agent_type: 'llm' }];
        else if (url.pathname === '/api/me/conversation-debug') {
          if (request.method() === 'PUT') enabled = request.postDataJSON().enabled;
          data = { allowed, enabled: allowed && enabled };
        }
        return route.fulfill({ json: data });
      }
      if (process.env.LIVE_ORIGIN) return route.continue();
      const file = url.pathname.startsWith('/static/dist/') ? path.join(root, url.pathname.slice(13)) : path.join(root, 'index.html');
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
    });
    await page.goto(origin + '/personalization');
    const toggle = page.locator('.debug-preference input[type="checkbox"]');
    await toggle.waitFor();
    assert.equal(await toggle.isChecked(), false);
    await toggle.check();
    assert.equal(enabled, true);
    await page.goto(origin + '/chat');
    await page.getByText('调试验收', { exact: true }).first().click();
    await page.getByRole('button', { name: /调试/ }).waitFor();
    await page.getByRole('button', { name: /调试/ }).click();
    await page.locator('.runtime-budget-title').waitFor();
    await page.getByText('Finalization Reserve').waitFor();
    await page.getByText('Budget Failure').waitFor();
    allowed = false;
    await page.reload();
    await page.getByText('调试验收', { exact: true }).first().click();
    assert.equal(await page.locator('.debug-toggle').count(), 0);
    await page.goto(origin + '/personalization');
    assert.equal(await page.locator('.debug-preference').count(), 0);
    assert.deepEqual(errors, []);
    console.log('PASS: personal debug preference and permission revocation (mocked APIs)');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
