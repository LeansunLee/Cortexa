const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const { themeVariables, themeGroups, solidCategories, normalizeTheme } = await import('../src/utils/theme.js');
  assert.equal(themeGroups[0].colors.length, 98);
  for (const category of solidCategories) {
    const colors = themeGroups[0].colors.filter(c => c.category === category);
    assert.equal(colors.length,14);
    assert.equal(new Set(colors.map(c=>c.value)).size,14);
  }
  assert.equal(new Set(themeGroups[0].colors.map(c => c.category)).size, solidCategories.length);
  assert.equal(normalizeTheme({value:'#123456',mode:'glass',glow:200}).glow,100);
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1100,height:900}});
    await page.setContent(`<main style="padding:24px"><h1>通用控件主题检查</h1>
      <section class="card"><h2>操作与输入</h2><button class="btn btn-primary">主要按钮</button> <button class="chat-send">发送</button> <button class="login-submit">登录</button> <button class="btn btn-danger">删除</button> <button class="btn btn-primary" disabled>禁用</button>
      <p><input aria-label="名称" placeholder="输入名称"> <select aria-label="分类"><option>分类一</option></select> <textarea placeholder="说明"></textarea></p>
      <p><input type="checkbox" checked aria-label="勾选"> 勾选 <input type="radio" checked aria-label="单选"> 单选 <input type="range" aria-label="滑块" value="75"></p>
      <label class="capability-switch"><input type="checkbox" checked><span class="capability-switch-track">开关</span></label></section>
      <section class="card"><h2>导航与数据</h2><div class="tabs"><button class="tab active">选中导航</button><button class="tab">其他</button></div><span class="tag">主题标签</span> <span class="badge badge-success">成功</span><p><a href="#" class="work-card">可交互卡片</a></p>
      <table style="width:100%"><thead><tr><th>名称</th><th>状态</th></tr></thead><tbody><tr aria-selected="true"><td>选中行</td><td>已选</td></tr><tr><td>普通行</td><td>正常</td></tr></tbody></table><div class="pagination"><button>上一页</button><button aria-current="page">1</button><button>下一页</button></div><div class="upload-progress-fill" style="height:6px;width:70%"></div></section></main>`);
    const assets=path.resolve(__dirname,'../../src/agentdevstu/web/static/dist/assets');
    await page.addStyleTag({path:path.join(assets,fs.readdirSync(assets).find(f=>/^index-.*\.css$/.test(f)))});
    const modes=[['solid',themeGroups[0].colors[0]],['contrast',themeGroups[1].colors[0]],['gradient',themeGroups[2].colors[0]],['texture',themeGroups[4].colors[0]],['glass-clear',{value:'#8B38FF',mode:'glass',finish:'clear',glow:100}],['glass-frosted',{value:'#8B38FF',mode:'glass',finish:'frosted',glow:100}]];
    for (const appearance of ['light','dark']) for (const [name,theme] of modes) {
      await page.evaluate(({appearance,theme,vars})=>{const root=document.documentElement;root.dataset.theme=appearance;root.style.colorScheme=appearance;root.dataset.colorTheme=theme.mode||'solid';Object.entries(vars).forEach(([k,v])=>root.style.setProperty(k,v));}, {appearance,theme,vars:themeVariables(theme)});
      await page.mouse.move(0,0); await page.waitForTimeout(180);
      const styles=await page.evaluate(()=>{
        const style=s=>getComputedStyle(document.querySelector(s));
        return {primary:style('.btn-primary').backgroundImage,send:style('.chat-send').backgroundImage,login:style('.login-submit').backgroundImage,primaryColor:style('.btn-primary').color,sendColor:style('.chat-send').color,loginColor:style('.login-submit').color,range:style('input[type=range]').backgroundColor,check:style('input[type=checkbox]').accentColor,input:style('input').backgroundColor,surface:getComputedStyle(document.documentElement).getPropertyValue('--surface').trim(),card:style('.card').backgroundColor,tag:style('.tag').backgroundImage,nav:style('.tab.active').backgroundImage};
      });
      assert.equal(styles.primary,styles.send,name); assert.equal(styles.primary,styles.login,name);
      assert.equal(styles.primaryColor,styles.sendColor); assert.equal(styles.primaryColor,styles.loginColor);
      assert.notEqual(styles.check,'auto'); assert.equal(styles.input,styles.card);
      if (name.startsWith('glass')) { assert.match(styles.primary,/at 100% 100%/); assert.match(styles.primary,/at 0% 0%/); assert.match(styles.primary,/0\.15/); assert.match(styles.tag,/radial-gradient/); assert.match(styles.nav,/radial-gradient/); }
      await page.getByLabel('名称',{exact:true}).focus();
      assert.equal(await page.getByLabel('名称',{exact:true}).evaluate(e=>getComputedStyle(e).outlineStyle),'solid');
      if (name.startsWith('glass')) await page.screenshot({path:`/tmp/ui-${name}-${appearance}.png`});
    }
    console.log('PASS: 12 theme/appearance combinations; primary aliases, inputs, focus, checkbox, slider, navigation, tags, cards, table; glass corner ratio');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
