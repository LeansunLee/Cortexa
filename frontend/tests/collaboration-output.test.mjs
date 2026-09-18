import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'

test('expanded collaboration renders full output beyond summary and escapes markup', async () => {
  const dir = await mkdtemp(new URL('../.collab-test-', import.meta.url).pathname)
  try {
    const source = (await readFile(new URL('../src/components/AgentCollaborationCard.vue', import.meta.url), 'utf8')).replace('const isExpanded = ref(false)', 'const isExpanded = ref(true)')
    const { descriptor } = parse(source)
    const code = compileScript(descriptor, { id: 'collab', inlineTemplate: true }).content.replace("import { avatarUrl } from '../utils/avatar'", 'const avatarUrl = value => value').replace("import { collaborationApi } from '../api/index.js'", 'const collaborationApi = {}')
    await writeFile(`${dir}/card.mjs`, code)
    const { default: Card } = await import(`${dir}/card.mjs`)
    const result = '原文'.repeat(1000) + '结尾标记<script>alert(1)</script>'
    const app = createSSRApp(Card, { collabs: [{ agent_name: '测试代理', status: 'success', summary: result.slice(0, 200), result }] })
    app.component('AppIcon', { render: () => null })
    const html = await renderToString(app)
    assert.ok(html.includes('完整输出'))
    assert.ok(html.includes('原文'.repeat(1000)))
    assert.ok(html.includes('结尾标记&lt;script&gt;'))
    assert.ok(!html.includes('<script>alert'))
    const reason = '自动整理背景失败，本任务未执行。请重试。'
    const failedApp = createSSRApp(Card, { collabs: [{ agent_name: '品牌部', status: 'failed', summary: reason, result: reason, background: { mode: 'auto', status: 'failed', reason, facts: [] } }] })
    failedApp.component('AppIcon', { render: () => null })
    const failedHtml = await renderToString(failedApp)
    assert.equal(failedHtml.split(reason).length - 1, 1)
    assert.ok(failedHtml.includes('未执行'))
    assert.ok(failedHtml.includes('背景 · 自动'))
    assert.ok(!failedHtml.includes('背景详情'))
    assert.ok(!failedHtml.includes('完整输出'))
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})
