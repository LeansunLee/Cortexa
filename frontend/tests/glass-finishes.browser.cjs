const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const origin = process.env.LIVE_ORIGIN || 'http://glass-finishes.local';
const dist = path.resolve(__dirname, '../../src/cortexa/web/static/dist');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route(origin + '/**', async route => {
      const url = new URL(route.request().url());
      if (url.pathname.startsWith('/api/')) {
        const data = url.pathname === '/api/auth/me'
          ? { id: 'u', username: 'u', display_name: '验收', system_permissions: [], memberships: [{ workspace_id: 'ws', permissions: [] }] }
          : url.pathname === '/api/workspaces' ? [{ id: 'ws', name: '测试空间' }] : [];
        return route.fulfill({ json: data });
      }
      if (process.env.LIVE_ORIGIN) return route.continue();
      const file = url.pathname.startsWith('/static/dist/')
        ? path.join(dist, url.pathname.slice('/static/dist/'.length)) : path.join(dist, 'index.html');
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
    });
    await page.goto(origin + '/personalization');
    await page.getByRole('tab', { name: '玻璃 14' }).click();
    await page.getByRole('button', { name: '冰川蓝' }).click();
    const styles = [];
    for (const [finish, name] of [['clear', '液态'], ['frosted', '磨砂']]) {
      await page.getByRole('button', { name, exact: true }).click();
      await page.waitForTimeout(220);
      assert.equal(await page.evaluate(() => document.documentElement.dataset.glassFinish), finish);
      styles.push(await page.locator('.theme-demo-button').evaluate(node => {
        const style = getComputedStyle(node);
        return { background: style.backgroundColor, blur: style.backdropFilter };
      }));
      assert.match(styles.at(-1).background, /\/ 0\.|rgba\([^)]*, 0\./);
      assert.match(styles.at(-1).blur, /blur\(/);
    }
    assert.notEqual(styles[0].background, styles[1].background);
    assert.notEqual(styles[0].blur, styles[1].blur);
    assert.deepEqual(errors, []);
    console.log('PASS: liquid and frosted glass keep distinct transparency and backdrop blur');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
