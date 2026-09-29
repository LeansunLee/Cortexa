import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'

test('debug panel renders historical trace details safely', async () => {
  const dir = await mkdtemp(new URL('../.debug-test-', import.meta.url).pathname)
  try {
    const source = await readFile(new URL('../src/components/ConversationDebugPanel.vue', import.meta.url), 'utf8')
    const { descriptor } = parse(source)
    const code = compileScript(descriptor, { id: 'debug-panel', inlineTemplate: true }).content
    await writeFile(`${dir}/panel.mjs`, code)
    const { default: Panel } = await import(`${dir}/panel.mjs`)
    const rounds = [{
      id: 'round-1', label: '第 1 轮 · 查询政策', createdAt: '2026-09-10T08:00:00Z', isLive: false,
      entries: [{ seq: 1, stage: 'knowledge', status: 'success', title: '知识库检索完成', summary: '命中 1 份文档', detail: { content: '<script>alert(1)</script>' } }],
    }]
    const html = await renderToString(createSSRApp(Panel, { rounds }))
    assert.ok(html.includes('知识库检索完成'))
    assert.ok(html.includes('命中 1 份文档'))
    assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt;'))
    assert.ok(!html.includes('<script>alert(1)</script>'))
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})

test('debug panel presents branch decisions and model/collaboration contexts', async () => {
  const dir = await mkdtemp(new URL('../.debug-test-', import.meta.url).pathname)
  try {
    const source = await readFile(new URL('../src/components/ConversationDebugPanel.vue', import.meta.url), 'utf8')
    const { descriptor } = parse(source)
    const code = compileScript(descriptor, { id: 'debug-panel-branches', inlineTemplate: true }).content
    await writeFile(`${dir}/panel.mjs`, code)
    const { default: Panel } = await import(`${dir}/panel.mjs`)
    const rounds = [{ id: 'round-2', label: '第二轮', createdAt: '2026-09-29T08:00:00Z', entries: [
      { seq: 1, stage: 'goal', title: 'Goal 影子解析', status: 'success', detail: { execution: 'LEGACY_UNCHANGED', route: { route: 'retrieval' } } },
      { seq: 2, stage: 'retrieval', title: '制定检索计划', status: 'success', summary: '需要查知识库', detail: { knowledge: true, memory: false, web: false, has_collaboration: false } },
      { seq: 3, stage: 'knowledge', title: '知识库检索完成', status: 'success', summary: '命中 1 份文档', detail: {} },
      { seq: 4, stage: 'collaboration', title: '准备向 数据分析 Agent 传递上下文', status: 'running', summary: '分配了数据核对任务', detail: { source_agent: { name: 'Peter' }, target_agent: { name: '数据分析 Agent' }, task: '核对销量', background_context: { recent_messages: 2 } } },
      { seq: 5, stage: 'context', title: '主 Agent 上下文组装完成', status: 'success', summary: '摘要 + 最近 4 条', detail: { messages_sent_to_model: [{ role: 'system', content: '你是销售助理' }, { role: 'user', content: '研究十月销售计划' }] } },
    ] }]
    const html = await renderToString(createSSRApp(Panel, { rounds }))
    assert.ok(html.includes('执行分支'))
    assert.ok(html.includes('检索策略'))
    assert.ok(html.includes('知识库检索完成'))
    assert.ok(html.includes('上下文快照'))
    assert.ok(html.includes('主 Agent → 模型'))
    assert.ok(html.includes('研究十月销售计划'))
    assert.ok(html.includes('Peter → 数据分析 Agent'))
    assert.ok(html.includes('核对销量'))
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})
