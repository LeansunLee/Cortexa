const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs'), path = require('path'), assert = require('assert/strict');
const root = path.resolve(__dirname, '../..'), dist = path.join(root, 'src/cortexa/web/static/dist');
const origin = process.env.LIVE_ORIGIN || 'http://knowledge.local';
(async () => {
  const { themeGroups } = await import(path.join(root, 'frontend/src/utils/theme.js'));
  const modes = [themeGroups[0].colors[0], themeGroups[1].colors[0], themeGroups[2].colors[0], themeGroups[4].colors[0], { value:'#aa6a00', mode:'glass', finish:'clear' }, { value:'#aa6a00', mode:'glass', finish:'frosted' }];
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  try {
    for (const [i, theme] of modes.entries()) for (const appearance of ['light','dark']) {
      const width = 1440;
      await check(theme, appearance, width, i);
    }
    await check(modes[4], 'system', 390, 'mobile');
    await check(modes[4], 'light', 900, 'tablet');
    async function check(theme, appearance, width, id) {
      const page = await browser.newPage({viewport:{width,height:900},colorScheme:appearance==='light'?'light':'dark'});
      const errors = [], calls = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.addInitScript(({theme,appearance})=>{
        localStorage.setItem('theme-color:user:user',JSON.stringify(theme));
        localStorage.setItem('ui-appearance:user:user',appearance);
      },{theme,appearance});
      const folders = [{id:'a',name:'二号文件夹',parent_id:null},{id:'b',name:'三级',parent_id:'a'},{id:'c',name:'四级',parent_id:'b'},{id:'d',name:'测试',parent_id:null}];
      const doc = {id:'doc',name:'酒与禅.png',folder_id:null,content:'资料摘要',metadata_json:{size:100},created_by:'user'};
      await page.route(origin+'/**',async route=>{
        const u = new URL(route.request().url()), method = route.request().method();
        if(u.pathname.startsWith('/api/')) {
          let data={};
          if(u.pathname==='/api/auth/me') data={id:'user',username:'tester',display_name:'验证账号',system_permissions:['knowledge.manage','knowledge.use'],memberships:[{workspace_id:'ws',permissions:['knowledge.manage','knowledge.use']}]};
          else if(u.pathname==='/api/workspaces') data=[{id:'ws',name:'测试空间'}];
          else if(u.pathname==='/api/knowledge') data=[{id:'kb',name:'知识库控件验证',status:'active',document_count:1}];
          else if(method==='POST' && u.pathname.endsWith('/folders')) {calls.push(route.request().postDataJSON());data={id:'new',...calls.at(-1)};}
          else if(method==='POST' && u.pathname.endsWith('/documents/move')) {calls.push(route.request().postDataJSON());}
          else if(u.pathname==='/api/knowledge/kb') data={id:'kb',name:'知识库控件验证',documents:[doc],folders};
          else if(u.pathname.endsWith('/folders')) data=folders;
          return route.fulfill({json:data});
        }
        if(process.env.LIVE_ORIGIN) return route.continue();
        const file=u.pathname.startsWith('/static/dist/')?path.join(dist,u.pathname.slice('/static/dist/'.length)):path.join(dist,'index.html');
        if(!fs.existsSync(file))return route.fulfill({status:404,body:''});
        return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});
      });
      await page.goto(origin+'/knowledge');
      await page.getByRole('button',{name:'展开',exact:true}).click();
      const primary = page.getByRole('button',{name:'创建知识库',exact:true});
      const style = loc => loc.evaluate(e=>{const s=getComputedStyle(e);return [s.backgroundColor,s.backgroundImage,s.color,s.borderRadius]});
      await page.mouse.move(width-1,899); await page.waitForTimeout(200);
      const sharedStyle = await style(primary);
      assert.deepEqual(await style(page.locator('.upload-action')),sharedStyle,'upload matches shared theme');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'no horizontal overflow');
      await page.getByRole('button',{name:'新建文件夹',exact:true}).click();
      const dialog=page.getByRole('dialog',{name:'新建文件夹',exact:true});
      const dialogBox=await dialog.boundingBox();
      assert.ok(dialogBox.x>=0 && dialogBox.x+dialogBox.width<=width,'dialog fits viewport');
      await dialog.getByRole('textbox',{name:'名称',exact:true}).fill('验收文件夹');
      await page.getByRole('button',{name:'父级文件夹',exact:true}).click();
      assert.equal(await dialog.locator('select').count(),0);
      await page.getByPlaceholder('搜索文件夹名称或路径').fill('四级');
      const option=page.getByRole('option',{name:'二号文件夹 / 三级 / 四级',exact:true});
      assert.equal(await page.getByRole('option').count(),1);
      await page.screenshot({path:'/tmp/knowledge-controls-'+id+'-'+appearance+'.png'});
      const menuBox=await page.locator('.search-select-menu').boundingBox();
      assert.ok(menuBox.x>=0 && menuBox.x+menuBox.width<=width+1 && menuBox.y>=0 && menuBox.y+menuBox.height<=901,'menu fits viewport');
      await option.click();
      await page.getByRole('button',{name:'父级文件夹',exact:true}).press('Enter');
      await page.keyboard.press('Escape');
      assert.equal(await dialog.isVisible(),true,'escape only closes picker');
      assert.equal(await page.getByRole('listbox').count(),0);
      await page.mouse.move(width-1,899); await page.waitForTimeout(200);
      assert.deepEqual(await style(dialog.getByRole('button',{name:'保存',exact:true})),sharedStyle);
      await dialog.getByRole('button',{name:'保存',exact:true}).click();
      await dialog.waitFor({state:'hidden'});
      assert.deepEqual(calls.at(-1),{name:'验收文件夹',parent_id:'c'});
      await page.getByRole('button',{name:'更多文件操作 酒与禅.png',exact:true}).click();
      await page.getByRole('button',{name:'移动到',exact:true}).click();
      const move=page.getByRole('dialog',{name:'移动文件',exact:true});
      assert.equal(await move.getByRole('textbox').getAttribute('readonly'),'');
      await page.getByRole('button',{name:'目标位置',exact:true}).click();
      await page.getByRole('option',{name:'二号文件夹 / 三级 / 四级',exact:true}).click();
      await move.getByRole('button',{name:'保存',exact:true}).click();
      await move.waitFor({state:'hidden'});
      assert.deepEqual(calls.at(-1),{document_ids:['doc'],folder_id:'c'});
      // A folder cannot move into itself or its own descendants.
      await page.locator('.folder-row').filter({hasText:'二号文件夹'}).getByRole('button',{name:'更多文件夹操作'}).click();
      await page.getByRole('button',{name:'移动到',exact:true}).click();
      await page.getByRole('button',{name:'目标位置',exact:true}).click();
      assert.deepEqual(await page.getByRole('option').allTextContents(),['根目录','测试']);
      await page.keyboard.press('Escape');
      await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click();
      await page.getByRole('button',{name:'摘要',exact:true}).click();
      await page.mouse.move(width-1,899); await page.waitForTimeout(200);
      assert.deepEqual(await style(page.getByRole('dialog').getByRole('button',{name:'编辑',exact:true})),sharedStyle);
      assert.deepEqual(errors,[]);
      console.log('PASS knowledge theme / searchable folder / create / move / subtree exclusion',id,appearance,width,origin);
      await page.close();
    }
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
