const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));

    const originalSql = 'SELECT name FROM dealers';
    const generatedSql = 'SELECT :keyword AS keyword, :minimum AS minimum, :ratio AS ratio, :active AS active';
    const generatedSchema = {
      type: 'object',
      properties: {
        keyword: { type: 'string', description: '关键词' },
        minimum: { type: 'integer', description: '最低数量' },
        ratio: { type: 'number', description: '比例' },
        active: { type: 'boolean', description: '启用' }
      },
      required: ['minimum'],
      additionalProperties: false
    };
    const description = '查询合作中门店；支持通用关键词及大区、省、市、区县、门店名称、经销商名称等条件组合筛选。仅返回 SQL 中的真实字段。';
    const root = process.env.FRONTEND_DIST_DIR || path.resolve(__dirname, '../../src/agentdevstu/web/static/dist');
    let originalTests = [];
    let draftTests = [];
    let rewrites = [];
    let saved;

    await page.route('http://data.local/**', async route => {
      const url = new URL(route.request().url());
      if (url.pathname.startsWith('/api/')) {
        let data = [];
        if (url.pathname === '/api/data/capabilities/test-sql') {
          originalTests.push(route.request().postDataJSON());
          return route.fulfill({ json: { success: true, columns: ['name'], rows: [['门店A']], row_count: 1, duration_ms: 8, truncated: false } });
        } else if (url.pathname === '/api/data/capabilities/parameterize-sql') {
          rewrites.push(route.request().postDataJSON());
          return route.fulfill({ json: { query_template: generatedSql, input_schema: generatedSchema, explanation: '添加四种筛选参数' } });
        } else if (url.pathname === '/api/data/capabilities/test-draft') {
          draftTests.push(route.request().postDataJSON());
          return route.fulfill({ json: { success: true, columns: ['名称', '数量'], rows: draftTests.length === 1 ? [] : [['示例经销商', 8]], row_count: draftTests.length === 1 ? 0 : 1, duration_ms: 12, truncated: false } });
        } else if (url.pathname === '/api/data/capabilities/2' && route.request().method() === 'PUT') {
          saved = route.request().postDataJSON();
          return route.fulfill({ json: { id: '2', ...saved } });
        } else if (url.pathname === '/api/auth/me') {
          data = { id: 'admin', display_name: '管理员', username: 'admin', system_permissions: [], memberships: [{ workspace_id: 'ws', permissions: ['data.manage'] }] };
        } else if (url.pathname === '/api/workspaces') {
          data = [{ id: 'ws', name: '测试空间' }];
        } else if (url.pathname === '/api/data/sources') {
          data = [{ id: 'source', name: '奔达DMS', type: 'postgres', status: 'active', config: {} }];
        } else if (url.pathname === '/api/data/capabilities') {
          data = [
            { id: '1', name: '车型', type: 'predefined_query', data_source_id: 'source', status: 'active', description: '在售产品和车型' },
            { id: '2', name: '门店', original_sql: originalSql, query_template: 'SELECT name FROM dealers WHERE (:keyword IS NULL OR name = :keyword)', input_schema: { type: 'object', properties: { keyword: { type: 'string', description: '关键词' } }, required: [], additionalProperties: false }, output_schema: {}, row_limit: 1000, timeout_seconds: 30, type: 'predefined_query', data_source_id: 'source', status: 'active', description }
          ];
        }
        return route.fulfill({ json: data });
      }
      const file = url.pathname.startsWith('/static/dist/') ? path.join(root, url.pathname.slice(13)) : path.join(root, 'index.html');
      return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
    });

    await page.goto('http://data.local/data-sources');
    await page.getByRole('button', { name: '数据能力', exact: true }).click();
    await page.getByText('门店', { exact: true }).waitFor();
    assert.equal(await page.locator('.card-description').count(), 0);
    assert.equal(await page.getByText(description, { exact: true }).count(), 0);

    for (const color of ['light', 'dark']) {
      await page.emulateMedia({ colorScheme: color });
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: 1000 });
        const card = page.locator('.card').filter({ has: page.getByText('门店', { exact: true }) });
        assert.equal(await card.getByText(description, { exact: true }).count(), 0);
        await card.getByRole('button', { name: '编辑', exact: true }).click();
        const dialog = page.getByRole('dialog', { name: '编辑数据能力' });
        await dialog.waitFor();
        const prompt = dialog.locator('.form-group').filter({ has: page.locator('label').getByText('补充提示词', { exact: true }) }).locator('textarea');
        assert.equal(await prompt.inputValue(), description);
        await page.screenshot({ path: `/tmp/agentdevstu-generalization/editor-${color}-${width}.png` });
        await dialog.getByRole('button', { name: '关闭编辑数据能力弹窗' }).click();
        await page.screenshot({ path: `/tmp/agentdevstu-generalization/list-${color}-${width}.png` });
      }
    }
    assert.deepEqual(errors, []);
    console.log('Data tool list hides prompts; editor retains configuration; light/dark desktop/mobile passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
