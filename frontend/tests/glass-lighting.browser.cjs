const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const { themeVariables } = await import('../src/utils/theme.js');
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 800 } });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const assets = path.resolve(__dirname, '../../src/agentdevstu/web/static/dist/assets');
    const css = fs.readFileSync(path.join(assets, fs.readdirSync(assets).find(n => /^index-.*\.css$/.test(n))), 'utf8');
    await page.setContent(`<style>${css}</style><style>
      #left,#right,#disabled{position:absolute;top:100px;width:100px;height:40px}
      #left{left:200px}#right{left:340px}#disabled{left:480px}
      #card{position:absolute;left:200px;top:300px;width:480px;height:280px;padding:24px;box-sizing:border-box}
    </style><button id="left" class="btn btn-primary">按钮一</button>
    <button id="right" class="btn btn-primary">按钮二</button>
    <button id="disabled" class="btn btn-primary" disabled>禁用</button>
    <section id="card" class="card"><h2>玻璃卡片</h2><p>光源只从最近的边缘进入。</p></section>`);
    const source = fs.readFileSync(path.resolve(__dirname, '../src/utils/glassLighting.js'), 'utf8');
    await page.addScriptTag({ content: source.replaceAll('export function', 'function') + '\nwindow.disposeLighting = installGlassLighting();' });
    const inline = id => page.locator('#' + id).evaluate(e => e.style.backgroundImage);
    async function move(x, y) {
      await page.mouse.move(x, y);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    }
    for (const finish of ['clear', 'frosted']) for (const appearance of ['light', 'dark']) {
      await page.evaluate(({ finish, appearance, vars }) => {
        const root = document.documentElement;
        Object.assign(root.dataset, { colorTheme: 'glass', glassFinish: finish, theme: appearance });
        root.style.colorScheme = appearance;
        Object.entries(vars).forEach(([k, v]) => root.style.setProperty(k, v));
        window.dispatchEvent(new Event('theme-change'));
      }, { finish, appearance, vars: themeVariables({ value: '#8B38FF', mode: 'glass', finish, glow: 0 }) });
      const setback = finish === 'clear' ? 28 : 36;
      await move(320, 120);
      assert.ok((await inline('left')).includes(`at ${100 + setback}px 20px`));
      assert.ok((await inline('right')).includes(`at ${-setback}px 20px`));
      assert.equal(await inline('disabled'), '');
      for (const [x, y, expected] of [[225, 108, `25px ${-setback}px`], [295, 120, `${100 + setback}px 20px`], [230, 136, `30px ${40 + setback}px`], [204, 120, `${-setback}px 20px`]]) {
        await move(x, y);
        assert.ok((await inline('left')).includes('at ' + expected));
      }
      await move(440, 440); // Card centre: top wins an equal top/bottom distance.
      const card = await inline('card');
      const positions = [...card.matchAll(/at (-?[\d.]+)px (-?[\d.]+)px/g)];
      assert.ok(positions.length >= 2);
      assert.ok(positions.every(([, x, y]) => Number(x) === 240 && Number(y) === -setback));
      assert.ok((await page.locator('#card').evaluate(e => getComputedStyle(e).backgroundImage)).includes(`at 240px ${-setback}px`));
      assert.equal(await inline('left'), ''); // Distant controls do not light up.
      await page.screenshot({ path: `/tmp/flow-light-${finish}-${appearance}.png` });
      await page.evaluate(() => window.dispatchEvent(new Event('appearance-change')));
      assert.equal(await inline('card'), '');
      await page.evaluate(() => document.dispatchEvent(new PointerEvent('pointermove', { clientX: 440, clientY: 440, pointerType: 'touch' })));
      assert.equal(await inline('card'), '');
    }
    // Normal motion travels around the outside; reduced motion above snaps immediately.
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await move(230, 108);
    const startImage = await inline('left');
    await move(270, 136);
    const earlyImage = await inline('left');
    assert.notEqual(startImage, earlyImage);
    const samples = await page.locator('#left').evaluate(e => new Promise(resolve => {
      const values = [];
      const sample = () => {
        values.push(e.style.backgroundImage);
        if (values.length < 65) requestAnimationFrame(sample);
        else resolve(values);
      };
      requestAnimationFrame(sample);
    }));
    assert.ok(new Set(samples).size > 3, 'light must flow through intermediate positions');
    for (const value of samples) {
      const [, x, y] = value.match(/at (-?[\d.]+)px (-?[\d.]+)px/);
      assert.ok(Number(x) < 0 || Number(x) > 100 || Number(y) < 0 || Number(y) > 40);
    }
    assert.equal(samples.at(-1), samples.at(-2), 'animation settles when the mouse stops');
    await page.evaluate(() => window.dispatchEvent(new Event('appearance-change')));
    await page.locator('#card').evaluate(e => e.style.setProperty('background-image', 'linear-gradient(red, blue)', 'important'));
    await move(440, 440);
    await page.evaluate(() => window.disposeLighting());
    assert.equal(await inline('card'), 'linear-gradient(red, blue)');
    assert.equal(await page.locator('#card').evaluate(e => e.style.getPropertyPriority('background-image')), 'important');
    console.log('PASS: both glass finishes × both appearances; interior edges, card centre, adjacent controls, distance, disabled/touch and cleanup');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
