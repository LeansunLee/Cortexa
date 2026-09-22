const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const dist = path.resolve(__dirname, '../../src/agentdevstu/web/static/dist');
const origin = 'http://settings.local';

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    for (const appearance of ['light', 'dark']) for (const finish of ['clear', 'frosted']) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, colorScheme: appearance });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.addInitScript(({ appearance, finish }) => {
        localStorage.setItem('ui-appearance:user:test-user', appearance);
        localStorage.setItem('theme-color:user:test-user', JSON.stringify({ value: '#0067E0', mode: 'glass', finish }));
      }, { appearance, finish });
      await page.route(origin + '/**', async route => {
        const url = new URL(route.request().url());
        if (url.pathname.startsWith('/api/')) {
          let data = {};
          if (url.pathname === '/api/auth/me') data = {
            id: 'test-user', username: 'tester', display_name: '测试用户',
            system_permissions: ['config.manage'],
            memberships: [{ workspace_id: 'ws', permissions: ['config.manage'] }],
          };
          else if (url.pathname === '/api/workspaces') data = [{ id: 'ws', name: '测试工作空间' }];
          else if (url.pathname === '/api/config') data = {
            providers: { Deepseek: { kind: 'openai', model: 'deepseek-v4-pro', base_url: 'https://api.deepseek.com/v1', api_key: 'sk-test', temperature: 0.2, max_tokens: 4096 } },
            default_provider: 'Deepseek', conversation_debug_enabled: false,
          };
          return route.fulfill({ json: data });
        }
        const file = url.pathname.startsWith('/static/dist/')
          ? path.join(dist, url.pathname.slice('/static/dist/'.length))
          : path.join(dist, 'index.html');
        return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
      });
      await page.goto(origin + '/settings');
      await page.getByRole('heading', { name: 'LLM 供应商配置' }).waitFor();
      await page.getByRole('button', { name: '+ 添加供应商', exact: true }).click();
      const overlay = page.locator('.provider-modal-overlay');
      const modal = page.locator('.provider-modal');
      await modal.getByRole('heading', { name: '添加供应商' }).waitFor();
      assert.equal(await overlay.evaluate(element => element.parentElement === document.body), true);
      assert.equal(await overlay.evaluate(element => getComputedStyle(element).position), 'fixed');
      assert.equal(await overlay.evaluate(element => getComputedStyle(element).inset), '0px');
      const overlayBox = await overlay.boundingBox();
      const modalBox = await modal.boundingBox();
      assert.ok(overlayBox && modalBox && modalBox.x > overlayBox.x && modalBox.y > overlayBox.y);
      const nameInput = modal.getByLabel('名称');
      const inputStyles = await nameInput.evaluate(element => {
        const style = getComputedStyle(element);
        return { color: style.color, background: style.backgroundColor, border: style.borderColor, placeholder: getComputedStyle(element, '::placeholder').color };
      });
      assert.notEqual(inputStyles.color, 'rgba(0, 0, 0, 0)');
      assert.notEqual(inputStyles.background, 'rgba(0, 0, 0, 0)');
      assert.notEqual(inputStyles.border, 'rgba(0, 0, 0, 0)');
      assert.notEqual(inputStyles.placeholder, inputStyles.background);
      await nameInput.focus();
      assert.match(await nameInput.evaluate(element => getComputedStyle(element).boxShadow), /0px 0px 0px 3px/);
      await modal.getByRole('button', { name: '关闭' }).click();
      await page.locator('tr', { hasText: 'Deepseek' }).click();
      const editModal = page.locator('.provider-modal');
      await editModal.getByRole('heading', { name: '编辑供应商' }).waitFor();
      const editableName = editModal.getByLabel('名称');
      assert.equal(await editableName.isEnabled(), true);
      await editableName.fill('Deepseek Renamed');
      assert.equal(await editableName.inputValue(), 'Deepseek Renamed');
      assert.equal(await page.locator('.provider-modal-overlay').evaluate(element => getComputedStyle(element).position), 'fixed');
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('PASS: provider add/edit stays modal and glass inputs remain readable');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
