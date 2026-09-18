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
