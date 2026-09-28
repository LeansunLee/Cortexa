const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const assets = path.resolve(__dirname, '../../src/cortexa/web/static/dist/assets');
  const cssFiles = fs.readdirSync(assets).filter(f => f.endsWith('.css'));
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const sample = `
      <div class="card" id="ds-card">数据源卡片</div>
      <span class="type-badge type-postgres">PG</span><span class="type-mysql">MySQL</span><span class="type-api">API</span>
      <span class="status-badge status-active">active</span><span class="status-badge status-error">err</span>
      <div class="test-result-block">result</div><div class="schema-row schema-header">head</div>
      <div class="panel">Access 面板</div><div class="dialog">Access 弹窗</div>
      <span class="status active">启用</span><span class="notice success">成功提示</span>
      <span class="kb-status">已启用</span><span class="kb-status disabled">停用</span>
      <span class="validity-label">有效</span><span class="validity-label expired">过期</span>
      <span class="priority P0">P0</span><span class="in_progress">处理中</span><span class="review">评审</span><span class="completed">完成</span>
      <div class="notice">工作提示</div>
      <span class="status-badge status-preparing">准备</span><span class="status-badge status-running">运行</span>
      <div class="msg-agent">agent 消息</div><div class="msg-host">host 消息</div>
      <div class="login-page"><div class="login-error">err</div><div class="login-notice">ok</div></div>`;
    await page.setContent(`<html><head></head><body>${sample}</body></html>`);
    for (const f of cssFiles) {
      let css = fs.readFileSync(path.join(assets, f), 'utf8');
      css = css.replace(/\[data-v-[\w-]+\]/g, '');
      await page.addStyleTag({ content: css });
    }
    const read = () => page.evaluate(() => {
      const bg = s => getComputedStyle(document.querySelector(s)).backgroundColor;
      const color = s => getComputedStyle(document.querySelector(s)).color;
      return {
        card: bg('.card'), panel: bg('.panel'), dialog: bg('.dialog'),
        resultBlock: bg('.test-result-block'), schemaHead: bg('.schema-header'),
        surface2: getComputedStyle(document.documentElement).getPropertyValue('--surface2').trim(),
        loginPage: bg('.login-page'),
        pgBadge: [bg('.type-postgres'), color('.type-postgres')],
        mysqlBadge: [bg('.type-mysql'), color('.type-mysql')],
        statusActive: [bg('.status-active'), color('.status-active')],
        statusError: [bg('.status-error'), color('.status-error')],
        noticeSuccess: [bg('.access .notice, .notice.success') || bg('.notice.success'), color('.notice.success')],
        kbStatus: [bg('.kb-status'), color('.kb-status')],
        kbStatusOff: [bg('.kb-status.disabled'), color('.kb-status.disabled')],
        validityExpired: color('.validity-label.expired'),
        p0: [bg('.P0'), color('.P0')],
        inProgress: [bg('.in_progress'), color('.in_progress')],
        completed: [bg('.completed'), color('.completed')],
        preparing: [bg('.status-preparing'), color('.status-preparing')],
        running: [bg('.status-running'), color('.status-running')],
        msgAgent: bg('.msg-agent'), msgHost: bg('.msg-host'),
        surface: getComputedStyle(document.documentElement).getPropertyValue('--surface').trim(),
      };
    });
    const parseRgb = v => {
      v = v.trim();
      if (v.startsWith('#')) {
        const h = v.slice(1);
        const f = h.length <= 3 ? h.split('').map(c => c + c).join('') : h.slice(0, 6).padEnd(6, '0');
        return [0, 2, 4].map(i => parseInt(f.slice(i, i + 2), 16));
      }
      return (v.match(/\d+\.?\d*/g) || []).map(Number);
    };
    for (const appearance of ['light', 'dark']) {
      await page.evaluate(a => {
        const root = document.documentElement;
        root.dataset.theme = a; root.style.colorScheme = a;
      }, appearance);
      await page.waitForTimeout(120);
      const s = await read();
      if (appearance === 'light') {
        // 语义变量在浅色下渲染为对应的浅色 token 值
        const eq = (a, b) => { const [x] = [parseRgb(a)], [y] = [parseRgb(b)]; return x[0] === y[0] && x[1] === y[1] && x[2] === y[2]; };
        assert.ok(eq(s.card, s.surface), 'card follows surface');
        assert.ok(eq(s.panel, s.surface), 'panel follows surface');
        assert.ok(eq(s.dialog, s.surface), 'dialog follows surface');
      } else {
        const rgb = parseRgb(s.surface);
        // 深色下所有卡片类容器背景 = 深色 surface（不再是白色）
        for (const [k, v] of [['card', s.card], ['panel', s.panel], ['dialog', s.dialog]]) {
          const got = parseRgb(v);
          assert.equal(got[0], rgb[0], `${k} follows dark surface`);
          assert.equal(got[1], rgb[1], `${k} follows dark surface`);
          assert.equal(got[2], rgb[2], `${k} follows dark surface`);
        }
        assert.notEqual(parseRgb(s.loginPage)[0], 255, 'login page dark bg');
        // 徽章文字在深色下为提亮色（亮度高于浅色值）
        const lum = c => { const [r, g, b] = parseRgb(c); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
        assert.ok(lum(s.statusActive[1]) > lum('#065f46'), 'status-active text lifted');
        assert.ok(lum(s.kbStatus[1]) > lum('#15803d'), 'kb-status text lifted');
        assert.ok(lum(s.p0[1]) > lum('#b54708'), 'P0 text lifted');
        assert.ok(lum(s.inProgress[1]) > lum('#4f46e5'), 'in_progress text lifted');
        assert.ok(lum(s.preparing[1]) > lum('#92400E'), 'preparing text lifted');
        assert.ok(lum(s.running[1]) > lum('#1E40AF'), 'running text lifted');
        assert.ok(lum(s.validityExpired) > lum('#d97706'), 'expired label lifted');
        assert.ok(lum(s.completed[1]) > lum('#027a48'), 'completed text lifted');
        // 消息气泡不再使用浅色实底
        for (const [k, v] of [['resultBlock', s.resultBlock], ['schemaHead', s.schemaHead]]) {
          const s2 = parseRgb(s.surface2);
          const got = parseRgb(v);
          assert.equal(got[0], s2[0], `${k} follows dark surface2`);
        }
        assert.ok(parseRgb(s.msgAgent)[2] < 255, 'msg-agent dark bg');
        assert.ok(parseRgb(s.msgHost)[2] < 255, 'msg-host dark bg');
      }
      console.log(`PASS ${appearance}:`, JSON.stringify({
        card: s.card, dialog: s.dialog, statusActive: s.statusActive, kbStatus: s.kbStatus, p0: s.p0, running: s.running,
      }));
    }
    console.log('PASS: fixed card/badge surfaces follow semantic tokens in light & dark');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
