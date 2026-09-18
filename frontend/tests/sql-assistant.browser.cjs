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

    await page.locator('.card').filter({ has: page.getByText('门店', { exact: true }) }).getByRole('button', { name: '编辑', exact: true }).click();
    await page.getByRole('dialog', { name: '编辑数据能力' }).waitFor();
    await page.mouse.click(10, 10);
    await page.getByRole('dialog', { name: '编辑数据能力' }).waitFor();
    assert.equal(await page.getByLabel('原始 SQL').inputValue(), originalSql);

    await page.getByRole('button', { name: '测试', exact: true }).click();
    await page.getByText('原始 SQL 可正常执行，返回 1 行', { exact: false }).waitFor();
    assert.deepEqual(originalTests[0], { data_source_id: 'source', query_template: originalSql });

    await page.getByRole('button', { name: 'AI 改写', exact: true }).click();
    await page.getByLabel('AI 改写 SQL 草稿').waitFor();
    assert.equal(rewrites[0].query_template, originalSql);
    assert.equal(rewrites[0].description, description);
    assert.equal(await page.getByLabel('AI 改写 SQL 草稿').inputValue(), generatedSql);

    await page.getByRole('button', { name: '试运行 SQL', exact: true }).click();
    await page.getByRole('alert').getByText('请填写必填参数：minimum', { exact: true }).waitFor();
    assert.equal(draftTests.length, 0);

    await page.getByLabel('测试参数 minimum', { exact: true }).fill('3');
    await page.getByLabel('测试参数 ratio', { exact: true }).fill('0.5');
    await page.getByLabel('测试参数 active', { exact: true }).selectOption('false');
    await page.getByRole('button', { name: '试运行 SQL', exact: true }).click();
    await page.getByText('查询成功，暂无符合条件的数据。', { exact: true }).waitFor();
    assert.deepEqual(draftTests[0].params, { keyword: null, minimum: 3, ratio: 0.5, active: false });
    assert.equal(draftTests[0].query_template, generatedSql);

    await page.getByLabel('测试参数 keyword', { exact: true }).fill('经销商');
    assert.equal(await page.getByText('查询成功，暂无符合条件的数据。', { exact: true }).count(), 0);
    await page.getByRole('button', { name: '试运行 SQL', exact: true }).click();
    await page.getByRole('cell', { name: '示例经销商', exact: true }).waitFor();

    fs.mkdirSync('/tmp/sql-assistant-qa', { recursive: true });
    await page.screenshot({ path: '/tmp/sql-assistant-qa/tested.png', fullPage: true });

    await page.getByLabel('AI 改写 SQL 草稿').fill('SELECT 1');
    await page.getByText('SQL 占位符与 Schema 字段不一致，请修正后再试运行或应用。', { exact: true }).waitFor();
    assert(await page.getByRole('button', { name: '应用 SQL 和 Schema', exact: true }).isDisabled());
    assert.equal(await page.getByRole('cell', { name: '示例经销商', exact: true }).count(), 0);

    await page.getByLabel('AI 改写 SQL 草稿').fill(generatedSql);
    await page.getByRole('button', { name: '应用 SQL 和 Schema', exact: true }).click();
    assert.equal(await page.getByLabel('改写 SQL').inputValue(), generatedSql);
    assert.deepEqual(JSON.parse(await page.getByLabel('输入 Schema (JSON)', { exact: true }).inputValue()), generatedSchema);
    await page.getByText('SQL 和输入 Schema 已同时填入表单；点击保存后生效。', { exact: true }).waitFor();

    await page.getByRole('dialog', { name: '编辑数据能力' }).getByRole('button', { name: '保存', exact: true }).click();
    await page.locator('.modal').waitFor({ state: 'detached' });
    assert.equal(saved.original_sql, originalSql);
    assert.equal(saved.query_template, generatedSql);
    assert.deepEqual(saved.input_schema, generatedSchema);
    assert.deepEqual(errors, []);
    console.log('PASS: original SQL test, AI rewrite, typed dynamic params, exact draft preview, atomic apply, modal persistence, save payload');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
