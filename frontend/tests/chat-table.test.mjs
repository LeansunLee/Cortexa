import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { highlightKeyContent } from '../src/utils/chatHighlights.js'

const source = await readFile(new URL('../src/views/Chat.vue', import.meta.url), 'utf8')
const functions = source.slice(source.indexOf('const formatMessage ='), source.indexOf('const formatMessageTime ='))
const render = new Function('highlightKeyContent', functions + '\nreturn formatMessage;')(highlightKeyContent)

test('spaces in lists never split product names into table columns', () => {
  const html = render('- 产品定位：  V4巡航旗舰\n- 在售车型：黑旗600 Pro 32,800元\n- 核心配置：电子离合（Ultra EC）')
  assert.ok(!html.includes('<table'))
  assert.ok(html.includes('黑旗600 Pro 32,800元'))
  assert.ok(html.includes('电子离合（Ultra EC）'))
})

test('explicit Markdown tables retain cell text', () => {
  const html = render('| 车型 | 参考价 |\n| --- | --- |\n| 黑旗600 Pro | 32,800元 |')
  assert.ok(html.includes('<table'))
  assert.ok(html.includes('黑旗600 Pro'))
})
