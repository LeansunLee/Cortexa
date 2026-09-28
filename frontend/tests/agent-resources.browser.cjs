const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs'), path = require('path'), assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..'), dist = path.join(root, 'src/cortexa/web/static/dist');
const origin = process.env.LIVE_ORIGIN || 'http://agent.local';
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    for (const [appearance, width, finish] of [['light',1600], ['dark',1440], ['system',360], ['light',1600,'frosted'], ['dark',900,'clear'], ['system',390,'frosted']]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, colorScheme: 'dark' });
      const errors = [], calls = [];
      const shot = appearance + '-' + width + '-' + (finish || 'solid');
      let failCreation = false;
      page.on('pageerror', e => errors.push(e.message));
      await page.addInitScript(({appearance,finish}) => { localStorage.setItem('ui-appearance:user:user', appearance); if(finish) localStorage.setItem('theme-color:user:user', JSON.stringify({value:'#00838f',mode:'glass',finish})); }, {appearance,finish});
      const permissions = ['agent.read', 'agent.update', 'agent.use', 'agent.operate', 'knowledge.manage', 'knowledge.use', 'memory.manage', 'data.manage'];
      let agent = { id: 'agent', name: '验收 Agent', status: 'active', agent_type: 'llm', avatar: '/static/avatars/bald.svg', tool_ids: ['search'], knowledge_base_ids: ['private'], web_search_enabled: true, tags: [], personality_config: {}, behavior_config: {} };
      const summary = { agent, knowledge_bases: [{ id: 'private', name: '独立资料', status: 'active', agent_id: 'agent' }, { id: 'shared', name: '空间资料', status: 'active' }], knowledge_base_ids: ['private'], tools: [{ id: 'search', name: 'web_search', status: 'active' }, { id: 'tool', name: '业务工具', status: 'active' }], tool_ids: ['search'], capabilities: [{ id: 'cap', name: '库存查询', data_source_name: '业务数据库', status: 'active' }], bindings: [], memories: [] };
      await page.route(origin + '/**', async route => {
        const req = route.request(), u = new URL(req.url()), p = u.pathname, method = req.method();
        if (p.startsWith('/api/')) {
          let data = [];
          if (method !== 'GET') calls.push({ p, method, data: req.postData() ? req.postDataJSON() : null });
          if (method === 'POST' && (p === '/api/knowledge' || p.endsWith('/knowledge-bases'))) {
            if(failCreation) { failCreation = false; return route.fulfill({status:503,json:{detail:'创建失败，请重试'}}); }
            await new Promise(resolve=>setTimeout(resolve,180)); data = {id:'created',name:req.postDataJSON().name,agent_id:'agent',status:'active'};
          }
          else if(p === '/api/agents/tools/web-search') data = {configured:true,provider_name:'SearXNG（自建）'};
          else if (p === '/api/auth/me') data = { id: 'user', username: 'tester', display_name: '验收', system_permissions: [], memberships: [{ workspace_id: 'ws', permissions }] };
          else if (p === '/api/workspaces') data = [{ id: 'ws', name: '验收空间' }];
          else if (p === '/api/agents' || p === '/api/auth/agents') data = [agent];
          else if (p === '/api/agents/agent' && method === 'PUT') { agent = { id: 'agent', ...req.postDataJSON() }; data = agent; }
          else if (p.endsWith('/summary') || p.endsWith('/resources')) data = summary;
          else if (['/api/knowledge/private', '/api/knowledge/shared', '/api/knowledge/created'].includes(p)) data = { id: p.split('/').at(-1), documents: [{ id: 'doc', name: '使用说明.txt', metadata_json: { size: 100 } }], folders: [] };
          else if (method === 'PATCH') data = req.postDataJSON();
          else if (method === 'POST' && p.endsWith('/memories')) data = { id: 'memory', status: 'active', ...req.postDataJSON() };
          else if (method === 'POST' && p.endsWith('/data-bindings')) data = { id: 'binding', ...req.postDataJSON() };
          else if (method === 'PUT' && p.includes('/memories/')) data = { id: 'memory', status: 'active', ...req.postDataJSON() };
          else if (p.includes('/config/')) data = { providers: [] };
          return route.fulfill({ json: data });
        }
        if (process.env.LIVE_ORIGIN) return route.continue();
        const file = p.startsWith('/static/dist/') ? path.join(dist, p.slice('/static/dist/'.length)) : p.startsWith('/static/avatars/') ? path.join(root, 'src/cortexa/web', p) : path.join(dist, 'index.html');
        return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.svg') ? 'image/svg+xml' : 'text/html' });
      });
      summary.capabilities[0].description = '查询合作中门店；支持通用关键词及大区、省、市、区县、门店名称、经销商名称等条件组合筛选。仅返回 SQL 中的真实字段；完整列表优先保留全部门店名称。LongDescriptionWithoutSpaces'.repeat(3);
      const noOverflow = async () => {
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'viewport overflow');
        for (const selector of ['.editor-content:visible','.resource-panel:visible','.my-agents:visible','.agent-search-panel:visible']) {
          for(const element of await page.locator(selector).all()) assert.ok(await element.evaluate(el=>el.scrollWidth<=el.clientWidth+1), selector+' internal overflow');
        }
      };
      const checkDialog = async (management) => {
        const trigger = page.getByRole('button',{name:'创建知识库',exact:true});
        assert.equal(await page.getByRole('textbox',{name:'知识库名称'}).count(),0);
        await trigger.click();
        const dialog = page.getByRole('dialog',{name:'创建独立知识库'});
        await dialog.waitFor();
        const input = dialog.getByRole('textbox',{name:'知识库名称'});
        assert.equal(await input.evaluate(el=>el===document.activeElement),true,'autofocus');
        assert.equal(await dialog.getByRole('button',{name:'创建',exact:true}).isDisabled(),true);
        await input.fill('   ');
        assert.equal(await dialog.getByRole('button',{name:'创建',exact:true}).isDisabled(),true);
        for(let i=0;i<5;i++) { await page.keyboard.press('Tab'); assert.equal(await dialog.evaluate(el=>el.contains(document.activeElement)),true,'modal focus trap'); }
        await page.keyboard.press('Escape');
        await dialog.waitFor({state:'hidden'});
        assert.equal(await trigger.evaluate(el=>el===document.activeElement),true,'focus restored');
        await trigger.click();
        await dialog.getByRole('button',{name:'取消',exact:true}).click();
        await dialog.waitFor({state:'hidden'});
        await trigger.click();
        await input.fill('验收独立知识库');
        const box=await dialog.boundingBox(); assert.ok(box.x>=0 && box.x+box.width<=width,'dialog bounds');
        await page.screenshot({path:'/tmp/agent-dialog-'+shot+'.png'});
        failCreation=true;
        await dialog.getByRole('button',{name:'创建',exact:true}).click();
        await dialog.getByRole('alert').waitFor();
        assert.equal(await input.inputValue(),'验收独立知识库','preserve failed form');
        const before = calls.length;
        await dialog.getByRole('button',{name:'创建',exact:true}).click();
        await page.keyboard.press('Enter');
        await dialog.waitFor({state:'hidden'});
        assert.equal(calls.length,before+1,'single creation');
        assert.equal(calls.at(-1).p, management ? '/api/knowledge' : '/api/agent-operations/agent/knowledge-bases');
        await page.getByRole('button',{name:'验收独立知识库',exact:true}).waitFor();
      };
      await page.goto(origin + '/agents');
      await page.locator('.agent-card').click();
      const nav = label => page.locator('.editor-nav .nav-item').filter({ hasText: label });
      if (width > 1400) {
        const section = await page.locator('.section:visible').boundingBox();
        assert.ok(section.width > 850, 'editor uses wide viewport');
      }
      for (const label of ['基础信息', '人格', '职责', '工作边界', '工作方式', 'Schema', '模型配置', '版本管理']) {
        await nav(label).click();
        await noOverflow();
      }
      await nav('知识库').click();
      assert.deepEqual(await page.locator('.agent-resources h3:visible').allTextContents(), ['独立知识库', '空间知识库']);
      await checkDialog(true);
      await page.getByRole('checkbox', { name: '使用知识库 空间资料' }).check();
      const sharedCard = page.locator('.knowledge-card').filter({ hasText: '空间资料' });
      await sharedCard.getByRole('button', { name: '展开', exact: true }).click();
      await sharedCard.getByRole('button', { name: '使用说明.txt', exact: true }).waitFor();
      await noOverflow();
      await nav('工具').click();
      await page.getByText('业务工具', { exact: true }).click();
      await nav('基础信息').click();
      await page.locator('.editor-actions').getByRole('button', { name: '保存', exact: true }).click();
      await page.getByText('保存成功', { exact: true }).waitFor();
      const saved = calls.find(c => c.method === 'PUT' && c.p === '/api/agents/agent').data;
      assert.deepEqual([...saved.knowledge_base_ids].sort(), ['created', 'private', 'shared']);
      assert.deepEqual(saved.tool_ids, ['search', 'tool']);
      assert.equal(saved.web_search_enabled, true, 'tool selection preserves search setting');
      await nav('工具').click();
      await page.getByRole('switch', { name: '允许智能体搜索公开网页' }).uncheck();
      await nav('记忆').click();
      await nav('工具').click();
      assert.equal(await page.getByRole('switch').isChecked(), false);
      await noOverflow();
      const searchBox=await page.locator('.agent-search-panel').boundingBox(), toolsBox=await page.locator('.tools-panel').boundingBox();
      assert.ok(toolsBox.y-searchBox.y-searchBox.height>=15,'separated tools panels');
      await page.screenshot({ path: '/tmp/agent-management-' + shot + '.png' });
      agent.name = '面向经销商与门店服务的综合业务支持 Agent LongAgentNameWithoutSpaces';
      agent.description = '帮助处理门店、库存、订单与售后问题，结合知识、工具和数据提供建议。LongDescriptionWithoutSpaces'.repeat(2);
      await page.goto(origin + '/my-agents');
      const chat = await page.getByRole('button', { name: '对话', exact: true }).boundingBox();
      const ops = await page.getByRole('button', { name: '运维', exact: true }).boundingBox();
      assert.equal(chat.y, ops.y, 'actions share a row');
      await noOverflow();
      await page.screenshot({path:'/tmp/agent-cards-'+shot+'.png'});
      await page.getByRole('button', { name: '运维', exact: true }).click();
      await checkDialog(false);
      await noOverflow();
      await page.screenshot({path:'/tmp/agent-knowledge-'+shot+'.png'});
      await page.getByRole('checkbox', { name: '使用知识库 空间资料' }).check();
      await page.getByRole('button', { name: '保存知识库绑定', exact: true }).click();
      await page.getByText('知识库绑定已保存', { exact: true }).waitFor();
      assert.deepEqual(calls.at(-1).data, { knowledge_base_ids: ['shared'] });
      await page.getByRole('button', { name: '工具', exact: true }).click();
      await page.getByText('业务工具', { exact: true }).click();
      await page.getByRole('button', { name: '保存工具绑定', exact: true }).click();
      await page.getByText('工具绑定已保存', { exact: true }).waitFor();
      assert.deepEqual(calls.at(-1).data, { tool_ids: ['search', 'tool'] });
      await page.getByRole('button', { name: '数据', exact: true }).click();
      await page.getByRole('button', { name: '选择数据能力', exact: true }).click();
      await page.getByRole('option', { name: '库存查询 · 业务数据库', exact: true }).click();
      await page.getByRole('button', { name: '绑定数据能力', exact: true }).click();
      await page.getByText('数据能力已绑定', { exact: true }).waitFor();
      await noOverflow();
      const unbind = page.getByRole('button', { name: '解绑', exact: true });
      assert.ok(await unbind.evaluate(el => { const r=document.createRange(); r.selectNodeContents(el); return r.getBoundingClientRect().height <= parseFloat(getComputedStyle(el).lineHeight)+1; }), 'unbind stays on one line');
      await page.screenshot({path:'/tmp/agent-data-'+shot+'.png'});
      await unbind.click();
      await page.getByText('数据能力已解绑', { exact: true }).waitFor();
      await page.getByRole('button', { name: '记忆', exact: true }).click();
      await page.getByRole('button', { name: '新增记忆', exact: true }).click();
      await noOverflow();
      await page.screenshot({path:'/tmp/agent-memory-form-'+shot+'.png'});
      await page.getByRole('textbox', { name: '记忆内容' }).fill('验收记忆');
      await page.getByRole('button', { name: '保存记忆', exact: true }).click();
      await page.getByText('记忆已保存', { exact: true }).waitFor();
      await page.getByRole('button', { name: '归档', exact: true }).click();
      await page.getByText('记忆已归档', { exact: true }).waitFor();
      await page.getByRole('checkbox', { name: '显示已归档记忆' }).check();
      await page.getByText('验收记忆', { exact: true }).waitFor();
      await noOverflow();
      assert.deepEqual(errors, []);
      await page.screenshot({ path: '/tmp/agent-resource-' + shot + '.png' });
      console.log('PASS management draft, knowledge dialog, tools, data, memory, buttons, responsive', appearance, width, finish || 'solid');
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
