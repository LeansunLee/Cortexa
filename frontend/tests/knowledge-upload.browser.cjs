const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs'), path = require('path'), assert = require('assert/strict');
const root = path.resolve(__dirname, '../..'), dist = path.join(root, 'src/cortexa/web/static/dist');
const origin = process.env.LIVE_ORIGIN || 'http://knowledge.local';
(async () => {
  const { themeGroups } = await import(path.join(root, 'frontend/src/utils/theme.js'));
  const modes = [themeGroups[0].colors[0], themeGroups[1].colors[0], themeGroups[2].colors[0], themeGroups[4].colors[0], { value:'#aa6a00', mode:'glass', finish:'clear' }, { value:'#aa6a00', mode:'glass', finish:'frosted' }];
  const browser = await chromium.launch({ headless:true, channel:'chrome' });
  try {
    for (const [id, theme] of modes.entries()) for (const appearance of ['light', 'dark']) await check(theme, appearance, 1440, id);
    await check(modes[4], 'system', 390, 'mobile');
    async function check(theme, appearance, width, id) {
      const page = await browser.newPage({ viewport:{ width, height:900 }, colorScheme:appearance === 'light' ? 'light' : 'dark' });
      const errors = [], pending = [];
      const folders = [{id:'a',name:'测试',parent_id:null},{id:'b',name:'二号文件夹',parent_id:null}];
      page.on('pageerror', error => errors.push(error.message));
      await page.addInitScript(({ theme, appearance }) => {
        localStorage.setItem('theme-color:user:user', JSON.stringify(theme));
        localStorage.setItem('ui-appearance:user:user', appearance);
        // Exercise the production Axios callback with deterministic transport events.
        const open = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url, ...rest) {
          if (String(url).endsWith('/upload')) window.testUpload = this;
          return open.call(this, method, url, ...rest);
        };
      }, { theme, appearance });
      await page.route(origin + '/**', async route => {
        const u = new URL(route.request().url());
        if (u.pathname.startsWith('/api/')) {
          let data = {};
          if (u.pathname === '/api/auth/me') data = { id:'user', username:'tester', display_name:'验证账号', system_permissions:['knowledge.manage','knowledge.use'], memberships:[{workspace_id:'ws',permissions:['knowledge.manage','knowledge.use']}] };
          else if (u.pathname === '/api/workspaces') data = [{id:'ws',name:'测试空间'}];
          else if (u.pathname === '/api/knowledge') data = [{id:'kb',name:'上传进度验证',status:'active',document_count:0}];
          else if (u.pathname === '/api/knowledge/kb') data = {id:'kb',name:'上传进度验证',documents:[],folders};
          else if (u.pathname.endsWith('/folders')) data = folders;
          else if (u.pathname.endsWith('/upload')) {
            const response = await new Promise(resolve => pending.push(resolve));
            return route.fulfill(response);
          }
          return route.fulfill({json:data});
        }
        if (process.env.LIVE_ORIGIN) return route.continue();
        const file = u.pathname.startsWith('/static/dist/') ? path.join(dist,u.pathname.slice('/static/dist/'.length)) : path.join(dist,'index.html');
        if (!fs.existsSync(file)) return route.fulfill({status:404,body:''});
        return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});
      });
      const waitFor = async fn => {
        for (let i=0;i<100;i++) { if (await fn()) return; await page.waitForTimeout(50); }
        assert.fail('Timed out waiting for upload state');
      };
      const progress = async loaded => {
        await page.evaluate(loaded => window.testUpload.upload.dispatchEvent(new ProgressEvent('progress',{lengthComputable:true,loaded,total:100})),loaded);
      };
      await page.goto(origin+'/knowledge');
      await page.getByRole('button',{name:'展开',exact:true}).click();
      const expandTree = page.getByRole('button',{name:'展开资源管理器',exact:true});
      if (await expandTree.isVisible()) await expandTree.click();
      await page.locator('.explorer-title').getByText('总文件夹数',{exact:true}).waitFor();
      assert.equal(await page.locator('.explorer-heading .tree-count').innerText(),'2');
      const counts = await page.locator('.explorer-heading .tree-count, .tree-root span:last-child, .tree-file-count').evaluateAll(nodes => nodes.map(e => {
        const s = getComputedStyle(e), r = e.getBoundingClientRect();
        return {width:r.width,center:r.x+r.width/2,justify:s.justifyContent,align:s.alignItems};
      }));
      assert.equal(counts.length,4);
      for (const count of counts) {
        assert.equal(count.width,24);
        assert.equal(count.justify,'center');
        assert.equal(count.align,'center');
        assert.ok(Math.abs(count.center-counts[0].center)<1,'folder counts share a centered column');
      }
      const panel = page.locator('.upload-box'), bar = page.getByRole('progressbar',{name:'整体上传进度'});
      assert.equal(await panel.isVisible(),false,'idle upload panel occupies no space');
      const chooserPromise = page.waitForEvent('filechooser');
      await page.locator('.upload-action').click();
      await (await chooserPromise).setFiles([
        {name:'上传进度验证.txt',mimeType:'text/plain',buffer:Buffer.from('first')},
        {name:'失败重试验证.txt',mimeType:'text/plain',buffer:Buffer.from('other')}
      ]);
      await waitFor(()=>pending.length===1);
      await bar.waitFor({state:'visible'});
      assert.equal(await page.locator('.upload-action').isDisabled(),true);
      await progress(40);
      await waitFor(async()=>await bar.getAttribute('aria-valuenow')==='20');
      assert.equal(await panel.getByText('40%',{exact:true}).isVisible(),true);
      assert.equal(await panel.getByText('等待上传',{exact:true}).isVisible(),true);
      await progress(100);
      await panel.getByText('服务器处理中…',{exact:true}).waitFor();
      assert.ok(Number(await bar.getAttribute('aria-valuenow'))<100,'processing is not complete');
      const box = await panel.boundingBox();
      assert.ok(box.width>0 && box.height>0 && box.x>=0 && box.x+box.width<=width+1,'visible progress fits viewport');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      const fill = await bar.locator('i').evaluate(e=>{const s=getComputedStyle(e);return {width:e.getBoundingClientRect().width,color:s.backgroundColor,image:s.backgroundImage}});
      assert.ok(fill.width>0 && (fill.color!=='rgba(0, 0, 0, 0)' || fill.image!=='none'),'progress fill is painted');
      await page.screenshot({path:'/tmp/knowledge-upload-'+id+'-'+appearance+'.png'});
      pending.shift()({json:{id:'first'}});
      await waitFor(()=>pending.length===1);
      pending.shift()({status:500,json:{detail:'测试上传失败'}});
      await panel.getByRole('button',{name:'重试',exact:true}).waitFor();
      assert.ok((await panel.innerText()).includes('1 成功 / 1 失败 / 共 2 个'));
      assert.equal(await panel.getByText('测试上传失败',{exact:true}).isVisible(),true);
      await panel.getByRole('button',{name:'重试',exact:true}).click();
      await waitFor(()=>pending.length===1);
      pending.shift()({json:{id:'second'}});
      await panel.getByRole('button',{name:'收起结果',exact:true}).waitFor();
      assert.equal(await bar.getAttribute('aria-valuenow'),'100');
      assert.ok((await panel.innerText()).includes('2 成功 / 0 失败 / 共 2 个'));
      assert.equal(await page.locator('.upload-action').isEnabled(),true);
      await panel.getByRole('button',{name:'收起结果',exact:true}).click();
      assert.equal(await panel.isVisible(),false);
      assert.deepEqual(errors,[]);
      console.log('PASS upload visibility / progress / processing / queue / retry / collapse',id,appearance,width,origin);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
