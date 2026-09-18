const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');

(async () => {
  const { themeVariables } = await import('../src/utils/theme.js');
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' });
  try {
    const page = await browser.newPage();
    const assets = path.resolve(__dirname, '../../src/agentdevstu/web/static/dist/assets');
    const css = fs.readdirSync(assets).find(name => /^index-.*\.css$/.test(name));
    await page.setContent('<button class="action-primary btn btn-primary">编辑并创建</button>');
    await page.addStyleTag({ path: path.join(assets, css) });

    const themes = [
      ['solid', '#0066FF', 'none'],
      ['contrast', { value: '#2563EB', accent: '#F97316' }, 'none'],
      ['gradient', { value: '#2563EB', accent: '#9333EA', mode: 'gradient' }, 'linear-gradient'],
      ['texture', { value: '#52684B', mode: 'texture', texture: 'wood' }, 'data:image'],
      ['glass-clear', { value: '#009EFF', mode: 'glass', finish: 'clear' }, 'radial-gradient'],
      ['glass-frosted', { value: '#009EFF', mode: 'glass', finish: 'frosted' }, 'radial-gradient'],
    ];

    for (const [name, theme, image] of themes) {
      const variables = themeVariables(theme);
      await page.evaluate(({ variables, name }) => {
        const root = document.documentElement;
        root.dataset.colorTheme = name.startsWith('glass') ? 'glass' : name;
        for (const [key, value] of Object.entries(variables)) root.style.setProperty(key, value);
      }, { variables, name });
      await page.waitForTimeout(350);
      const button = page.getByRole('button', { name: '编辑并创建' });
      const style = await button.evaluate(element => {
        const computed = getComputedStyle(element);
        return { image: computed.backgroundImage, color: computed.color, backdrop: computed.backdropFilter };
      });
      image === 'none' ? assert.equal(style.image, 'none', name) : assert.match(style.image, new RegExp(image), name);
      assert.notEqual(style.color, 'rgba(0, 0, 0, 0)', name);
      if (name === 'glass-clear') assert.match(style.backdrop, /blur\(0px\)/);
      if (name === 'glass-frosted') assert.match(style.backdrop, /blur\(24px\)/);
    }
    console.log('PASS: work candidate primary action follows solid, contrast, gradient, texture, and both glass themes');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
