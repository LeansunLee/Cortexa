const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const dist = process.env.DIST_ROOT || path.resolve(__dirname, '../../src/cortexa/web/static/dist');
const origin = process.env.LIVE_ORIGIN || 'http://operations.local';

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    for (const permitted of [true, false]) {
      const page = await browser.newPage();
      page.setDefaultTimeout(5000);
      const errors = [], calls = [];
      page.on('pageerror', error => errors.push(error.message));
      const agent = { id: 'route-test-agent', name: '路由验收 Agent', status: 'active', agent_type: 'llm' };
      const permissions = ['agent.use', ...(permitted ? ['agent.operate'] : [])];
      const summary = { agent, knowledge_bases: [], knowledge_base_ids: [], tools: [], tool_ids: [], capabilities: [], bindings: [], memories: [] };
      await page.route(origin + '/**', async route => {
        const pathname = new URL(route.request().url()).pathname;
        if (pathname.startsWith('/api/')) {
          calls.push(pathname);
          assert.equal(route.request().method(), 'GET', 'navigation must not change business data');
          let data = [];
          if (pathname === '/api/auth/me') data = { id: 'route-test-user', username: 'test', display_name: '验收', system_permissions: [], memberships: [{ workspace_id: 'ws', permissions }] };
          else if (pathname === '/api/workspaces') data = [{ id: 'ws', name: '验收空间' }];
          else if (pathname === '/api/auth/agents') data = [agent];
          else if (pathname.endsWith('/summary')) data = summary;
          else if (pathname === '/api/memories' || pathname.endsWith('/memory-issues')) data = { items: [], next_cursor: null };
          else if (pathname.endsWith('/memory-summary') || pathname.endsWith('/memory-config')) data = {};
          return route.fulfill({ json: data });
        }
        if (process.env.LIVE_ORIGIN) return route.continue();
        const file = pathname.startsWith('/static/dist/') ? path.join(dist, pathname.slice('/static/dist/'.length)) : path.join(dist, 'index.html');
        return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
      });
      const operationsPath = '/agent-operations/' + agent.id;
      await page.goto(origin + '/my-agents');
      await page.getByText(agent.name, { exact: true }).waitFor();
      const entry = page.getByRole('button', { name: '运维', exact: true });
      if (permitted) {
        await entry.click();
        const operations = page.locator('.agent-operations');
        await operations.getByRole('navigation', { name: '资源类型' }).waitFor();
        assert.equal(new URL(page.url()).pathname, operationsPath);
        for (const name of ['工具', '数据', '记忆', '知识库']) {
          await operations.getByRole('navigation', { name: '资源类型' }).getByRole('button', { name, exact: true }).click();
        }
        await page.reload();
        await operations.getByText(agent.name, { exact: true }).waitFor();
        await page.goto(origin + operationsPath);
        await operations.getByText(agent.name, { exact: true }).waitFor();
        assert.ok(calls.includes('/api' + operationsPath + '/summary'));
        assert.equal(await operations.getByRole('alert').count(), 0);
      } else {
        assert.equal(await entry.count(), 0);
        await page.goto(origin + operationsPath);
        await page.waitForURL(origin + '/');
        assert.ok(!calls.some(p => p.startsWith('/api/agent-operations/')));
      }
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('PASS: operations entry, resource tabs, reload, direct link and permission guard (mocked APIs)');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
