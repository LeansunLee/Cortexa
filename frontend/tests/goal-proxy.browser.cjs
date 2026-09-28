// Built UI with isolated API responses. It verifies configuration and wire payloads.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const origin = process.env.LIVE_ORIGIN || 'http://proxy.local';
    const root = path.resolve(__dirname, '../../src/agentdevstu/web/static/dist');
    const permissions = ['agent.use', 'agent.read', 'agent.update', 'agent.create'];
    const main = { id: 'main', name: '主Agent', agent_type: 'llm', status: 'active', collaboration: {} };
    const proxy = {
      id: 'proxy', name: '外部查询代理', agent_type: 'proxy', status: 'active', tags: [],
      description: '严格参数查询', collaboration: { allow_incoming: true, discoverable: true },
      proxy_config: { endpoint: 'https://example.test/run', method: 'POST', goal_contract: {
        enabled: true, input_budget: 4000, response_bytes: 128000,
        fields: { city: ['explicit'], query: ['goal_task'] },
      } },
      input_schema: { type: 'object', properties: { city: { type: 'string' }, query: { type: 'string' } }, required: ['city', 'query'] },
      output_schema: {}, knowledge_base_ids: [], tool_ids: [], temperature: 0.2, max_tokens: 4096,
    };
    let sentGoal;
    let messages = [];
    await page.route(origin + '/**', async route => {
      const request = route.request();
      const url = new URL(request.url());
      let data = [];
      if (url.pathname.startsWith('/api/')) {
        if (url.pathname === '/api/auth/me') data = { id: 'u', username: 'u', display_name: '验收', system_permissions: [], memberships: [{ workspace_id: 'ws', permissions }] };
        else if (url.pathname === '/api/workspaces') data = [{ id: 'ws', name: '测试空间' }];
        else if (url.pathname === '/api/auth/agents' || url.pathname === '/api/collaboration/agents') data = [main, proxy];
        else if (url.pathname === '/api/agents') data = [proxy];
        else if (url.pathname === '/api/agents/proxy') data = proxy;
        else if (url.pathname === '/api/agents/models/available') data = { providers: [] };
        else if (url.pathname === '/api/agents/tools/web-search') data = { configured: false };
        else if (url.pathname === '/api/config') data = { conversation_debug_enabled: false };
        else if (url.pathname === '/api/me/conversation-debug') data = { allowed: false, enabled: false };
        else if (url.pathname === '/api/conversations') data = [{ id: 'conv', agent_id: 'main', agent_name: '主Agent', title: 'Proxy 验收' }];
        else if (url.pathname.endsWith('/messages')) data = messages;
        else if (url.pathname.endsWith('/goal-options')) data = { enabled: true, agent_type: 'llm' };
        else if (url.pathname.endsWith('/message-route')) data = { use_goal: true };
        else if (url.pathname.endsWith('/goals/stream')) {
          sentGoal = request.postDataJSON();
          const done = { type: 'done', id: 'a', goal_id: 'g', status: 'COMPLETE', revision: 3, content: '完成', collaborations: [] };
          messages = [{ id: 'u', role: 'user', content: sentGoal.content, metadata_json: { goal_id: 'g' } },
            { id: 'a', role: 'assistant', content: '完成', metadata_json: { goal_id: 'g', goal_status: 'COMPLETE' } }];
          return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify(done)}\n\n` });
        } else if (url.pathname.endsWith('/goals/g')) data = { goal_id: 'g', status: 'COMPLETE', revision: 3 };
        return route.fulfill({ json: data });
      }
      if (process.env.LIVE_ORIGIN) return route.continue();
      const file = url.pathname.startsWith('/static/dist/') ? path.join(root, url.pathname.slice(13)) : path.join(root, 'index.html');
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
    });

    await page.goto(origin + '/agents');
    await page.getByText('外部查询代理', { exact: true }).first().click();
    await page.getByText('Proxy 配置', { exact: true }).click();
    await page.getByText('目标模式输入契约', { exact: true }).waitFor();
    assert.ok(await page.getByText('完整对话、记忆和主 Agent 提示词不会进入请求', { exact: false }).isVisible());
    assert.equal(await page.locator('.goal-proxy-contract input[type="number"]').inputValue(), '4000');
    assert.ok(await page.getByText('city · 允许来源', { exact: true }).isVisible());

    await page.goto(origin + '/chat');
    await page.getByText('Proxy 验收', { exact: true }).first().click();
    const input = page.locator('.chat-input');
    await input.fill('@外部查询代理 查询销售');
    await page.getByText('显式参数', { exact: true }).click();
    await page.getByLabel('外部查询代理显式参数 JSON').fill('{bad json');
    await page.locator('.chat-send').click();
    await page.getByText('代理参数无效', { exact: false }).waitFor();
    assert.equal(sentGoal, undefined);
    await page.getByLabel('外部查询代理显式参数 JSON').fill('{"city":"杭州","history":"不应发送"}');
    await page.locator('.chat-send').click();
    await page.getByText('完成', { exact: true }).first().waitFor();
    assert.deepEqual(sentGoal.participants, [{ agent_id: 'proxy', inputs: { city: '杭州', history: '不应发送' } }]);
    assert.deepEqual(errors, []);
    console.log('PASS: Proxy contract UI, optional task, explicit JSON validation and Goal participant payload (mocked APIs)');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
