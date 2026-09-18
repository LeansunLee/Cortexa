const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
// Run against Vite: npm run dev -- --host 127.0.0.1
const origin = process.env.TEST_ORIGIN || 'http://127.0.0.1:5173';
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  const errors = [];
  try {
    for (const width of [1440, 390]) for (const appearance of ['light', 'dark', 'system']) {
      const page = await browser.newPage({ viewport: { width, height: 900 }, colorScheme: 'dark' });
      page.on('pageerror', e => { errors.push(e.message); console.error(e.message); });
      let saved = '', docName = '', failSave = false, holdSave, posts = 0;
      await page.route('**/api/knowledge/**', async route => {
        const request = route.request(), url = new URL(request.url());
        let data = {};
        if (request.method() === 'POST') {
          const payload = request.postDataJSON();
          assert.equal(payload.folder_id, 'folder');
          posts++; saved = payload.content; docName = payload.name; data = { id: 'doc', name: docName };
        } else if (request.method() === 'PUT') {
          if (holdSave) await new Promise(resolve => { holdSave = resolve; });
          if (failSave) return route.fulfill({ status: 500, json: { detail: '测试保存失败' } });
          saved = request.postDataJSON().content; data = { name: docName };
        } else if (url.pathname.endsWith('/preview')) data = { name: docName, kind: 'text', status: 'ready', page_count: 1 };
        else data = { content: saved };
        await route.fulfill({ json: data });
      });
      await page.route('**/textdoc-harness', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><body><div id="app"></div><script type="module">
        import {createApp,ref,h} from '/static/dist/node_modules/.vite/deps/vue.js';
        import CreateDialog from '/static/dist/src/components/knowledge/CreateTextDocDialog.vue';
        import Preview from '/static/dist/src/components/knowledge/DocumentPreview.vue';
        import '/static/dist/src/App.vue';
        import '/static/dist/src/styles/components.css';
        import '/static/dist/src/styles/theme-controls.css';
        import {applyTheme,readTheme} from '/static/dist/src/utils/theme.js';
        import {applyAppearance,watchSystemAppearance} from '/static/dist/src/utils/appearance.js';
        applyTheme(readTheme()); applyAppearance('${appearance}'); watchSystemAppearance();
        createApp({setup(){const mode=ref('create');return () => mode.value === 'create' ? h(CreateDialog,{kbId:'kb',folderId:'folder',onCreated:()=>mode.value='preview',onClose:()=>mode.value='closed'}) : mode.value === 'preview' ? h(Preview,{kbId:'kb',docId:'doc',onClose:()=>mode.value='closed'}) : null}}).mount('#app');
      </script></body></html>` }));
      await page.goto(origin + '/textdoc-harness');
      const editor = () => page.locator('.toastui-editor-ww-container [contenteditable=true]');
      await page.getByPlaceholder('例如：笔记.txt 或 说明.md').fill(width === 390 ? '测试.txt' : '测试.md');
      const createBounds = await page.locator('.textdoc-dialog').boundingBox();
      assert.equal(await page.getByRole('button', {name:'创建文档',exact:true}).isDisabled(), true);
      const box = await editor().boundingBox();
      assert.ok(box.height > 150, 'editable area must have usable height');
      // Click the empty body, not only its first line: reproduces the collapsed-container bug.
      await editor().click({ position: { x: 50, y: box.height / 2 } });
      await page.keyboard.insertText('正文输入验证');
      await page.keyboard.press('Enter');
      await page.keyboard.insertText('第二段内容');
      await page.getByRole('button', {name:'创建文档',exact:true}).click();
      await page.getByRole('button', {name:'编辑',exact:true}).waitFor();
      assert.equal(posts, 1); assert.ok(saved.includes('正文输入验证')); assert.ok(saved.includes('第二段内容'));
      await page.getByRole('button', {name:'编辑',exact:true}).click();
      await editor().waitFor();
      const editBounds = await page.locator('.textdoc-dialog').boundingBox();
      assert.deepEqual(editBounds, createBounds, 'create and edit share the same dialog geometry');
      assert.equal(await page.locator('.name-field input').getAttribute('readonly'), '');
      assert.ok((await editor().innerText()).includes('正文输入验证'));
      await editor().click(); await page.keyboard.press('ControlOrMeta+End');
      await page.keyboard.press('Enter'); await page.keyboard.insertText('追加编辑内容');
      failSave = true;
      await page.getByRole('button', {name:'保存',exact:true}).click();
      await page.getByRole('alert').waitFor();
      assert.ok((await editor().innerText()).includes('追加编辑内容'), 'failed save preserves draft');
      failSave = false; holdSave = true;
      await page.getByRole('button', {name:'保存',exact:true}).click();
      await page.waitForFunction(() => document.querySelector('.content-field').inert);
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('.textdoc-dialog').count(), 1, 'saving cannot be dismissed');
      while (typeof holdSave !== 'function') await new Promise(resolve => setTimeout(resolve, 10));
      holdSave(); holdSave = null;
      await page.getByRole('button', {name:'编辑',exact:true}).waitFor();
      assert.ok(saved.includes('追加编辑内容'));
      assert.ok((await page.locator('.markdown-page').innerText()).includes('追加编辑内容'));
      await page.getByRole('button', {name:'编辑',exact:true}).click();
      await editor().waitFor();
      await editor().click(); await page.keyboard.press('ControlOrMeta+End');
      await page.keyboard.insertText('取消内容');
      if (appearance === 'system') {
        await page.emulateMedia({colorScheme:'light'});
        await page.waitForFunction(() => document.documentElement.dataset.theme === 'light');
        assert.ok((await editor().innerText()).includes('取消内容'));
      }
      const footer = await page.locator('.textdoc-footer').boundingBox();
      assert.ok(footer.y + footer.height <= 900);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      if (process.env.SCREENSHOT_DIR) await page.screenshot({ path: process.env.SCREENSHOT_DIR + '/textdoc-' + width + '-' + appearance + '.png' });
      await page.getByRole('button', {name:'取消',exact:true}).click();
      assert.ok(!saved.includes('取消内容'));
      await page.close();
      console.log('PASS', width, appearance, 'create/edit/input/save/retry/cancel/layout');
    }
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
