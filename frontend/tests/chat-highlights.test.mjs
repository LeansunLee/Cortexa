import test from 'node:test'
import assert from 'node:assert/strict'
import { highlightKeyContent } from '../src/utils/chatHighlights.js'

test('highlights important table cells without coloring column headings', () => {
  const html = '<table><tr><th><strong class="hl">关键指标</strong></th></tr><tr><td class="col-text">建议<strong class="hl">优先执行</strong></td></tr></table>'
  const result = highlightKeyContent(html)
  assert.ok(result.includes('<th><strong class="hl">关键指标</strong></th>'))
  assert.ok(result.includes('<strong class="hl hl-key">优先执行</strong>'))
})

test('prioritizes conclusions while keeping headings and labels neutral', () => {
  const html = '<h2><strong class="hl">重要标题</strong></h2><p><strong class="hl">背景信息</strong></p><p>核心结论：<strong class="hl">优先改善服务</strong></p><p><strong class="hl">建议：</strong>继续观察</p>'
  const result = highlightKeyContent(html)
  assert.equal((result.match(/hl-key/g) || []).length, 1)
  assert.ok(result.includes('class="hl hl-key">优先改善服务'))
})

test('limits emphasis and preserves unformatted content', () => {
  const html = Array.from({ length: 10 }, () => '<li>建议<strong class="hl">控制投入规模</strong></li>').join('')
  assert.equal((highlightKeyContent(html).match(/hl-key/g) || []).length, 3)
  assert.equal(highlightKeyContent('<p>普通正文</p>'), '<p>普通正文</p>')
  assert.equal(highlightKeyContent('<p><strong class="hl">尚未完成'), '<p><strong class="hl">尚未完成')
})
