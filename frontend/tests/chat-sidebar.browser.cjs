// Built UI with isolated API responses; verifies grouping and the shared action menu.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 720 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const origin = 'http://chat-sidebar.local';
    const root = path.resolve(__dirname, '../../src/agentdevstu/web/static/dist');
    const conversations = [
      { id: 'p1', agent_id: 'peter', agent_name: 'Peter', agent_avatar: '/static/avatars/ceo.svg', title: '第一轮', created_at: '2026-09-27T10:37:00' },
      { id: 'p2', agent_id: 'peter', agent_name: 'Peter', agent_avatar: '/static/avatars/ceo.svg', title: '第二轮', created_at: '2026-09-27T10:30:00' },
      { id: 's1', agent_id: 'sales', agent_name: '销售部', agent_avatar: '/static/avatars/sales.svg', title: '销售计划', created_at: '2026-09-27T09:00:00' },
    ];
    let renamed = null;
    let deleted = null;
    let messageLoads = 0;
    await page.route(origin + '/**', async route => {
      const req = route.request();
      const url = new URL(req.url());
      if (url.pathname.startsWith('/api/')) {
        let data = [];
        if (url.pathname === '/api/auth/me') data = { id: 'test', display_name: '测试用户', username: 'test', system_permissions: [], memberships: [{ workspace_id: 'ws', permissions: ['agent.use', 'agent.read'] }] };
        else if (url.pathname === '/api/workspaces') data = [{ id: 'ws', name: '测试空间' }];
        else if (url.pathname === '/api/auth/agents' || url.pathname === '/api/collaboration/agents') data = [{ id: 'peter', name: 'Peter' }, { id: 'sales', name: '销售部' }];
        else if (url.pathname === '/api/config') data = { conversation_debug_enabled: false };
        else if (url.pathname === '/api/me/conversation-debug') data = { allowed: false, enabled: false };
        else if (url.pathname === '/api/conversations') data = conversations;
        else if (url.pathname.endsWith('/messages')) { messageLoads++; data = []; }
        else if (url.pathname === '/api/conversations/p1' && req.method() === 'PATCH') {
          renamed = req.postDataJSON().title;
          conversations[0].title = renamed;
          data = conversations[0];
        } else if (url.pathname === '/api/conversations/p1' && req.method() === 'DELETE') {
          deleted = 'p1';
          conversations.splice(0, 1);
          data = {};
        }
        return route.fulfill({ json: data });
      }
      const file = url.pathname.startsWith('/static/dist/') ? path.join(root, url.pathname.slice(13)) : path.join(root, 'index.html');
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
    });
    await page.goto(origin + '/chat');
    await page.locator('.conv-group-heading').first().waitFor();
    assert.deepEqual(await page.locator('.conv-group-name').allInnerTexts(), ['Peter', '销售部']);
    assert.deepEqual(await page.locator('.conv-group-count').allInnerTexts(), ['2', '1']);
    assert.equal(await page.locator('.conv-group-avatar .agent-avatar-inline').count(), 2);
    assert.equal(await page.locator('.conv-item .conv-avatar, .conv-item .conv-meta').count(), 0);
    assert.equal(await page.locator('.conv-item').first().locator('.conv-title-text').innerText(), '第一轮');
    assert.equal(await page.locator('.conv-item').first().locator('.conv-more').evaluate(el => getComputedStyle(el).opacity), '0');
    if (process.env.CHAT_SIDEBAR_SCREENSHOT) await page.screenshot({ path: process.env.CHAT_SIDEBAR_SCREENSHOT });
    await page.locator('.conv-group-heading').first().click();
    assert.equal(await page.locator('.conv-item:visible').count(), 1);
    await page.locator('.sidebar-search input').fill('第一轮');
    assert.equal(await page.locator('.conv-item:visible').count(), 1);
    assert.equal(await page.locator('.conv-group-name').first().innerText(), 'Peter');
    await page.locator('.sidebar-search input').fill('');
    await page.locator('.conv-group-heading').first().click();
    await page.locator('.conv-item').first().hover();
    assert.equal(await page.locator('.conv-item').first().locator('.conv-more').evaluate(el => getComputedStyle(el).opacity), '1');
    await page.locator('.conv-item').first().locator('.conv-more').click();
    assert.equal(await page.getByRole('menuitem').count(), 2);
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('menuitem').count(), 0);
    await page.locator('.conv-item').first().hover();
    await page.locator('.conv-item').first().locator('.conv-more').click();
    await page.getByRole('menuitem', { name: '重命名' }).click();
    await page.locator('.conv-rename-input').fill('新的标题');
    await page.locator('.conv-rename-input').press('Enter');
    assert.equal(renamed, '新的标题');
    await page.setViewportSize({ width: 600, height: 700 });
    page.once('dialog', dialog => dialog.accept());
    await page.locator('.conv-item').first().hover();
    await page.locator('.conv-item').first().locator('.conv-more').click();
    const menuBounds = await page.locator('.conv-action-menu').boundingBox();
    assert.ok(menuBounds.x >= 0 && menuBounds.x + menuBounds.width <= 600);
    await page.getByRole('menuitem', { name: '删除' }).click();
    await page.waitForFunction(() => document.querySelectorAll('.conv-group-count')[0]?.textContent === '1');
    assert.equal(deleted, 'p1');
    await page.locator('.conv-item').first().click();
    await page.locator('.conv-item').first().click();
    assert.equal(messageLoads, 2, 'reopening an already open conversation refreshes saved messages');
    assert.deepEqual(errors, []);
    console.log('PASS: Agent groups, counts, collapse/search, rename/delete menu');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
