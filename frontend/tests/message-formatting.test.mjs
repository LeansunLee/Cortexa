import assert from 'node:assert/strict'
import test from 'node:test'
import { inlineFormat } from '../src/utils/messageFormatting.js'

test('message formatting escapes HTML before adding formatting tags', () => {
  assert.equal(inlineFormat('<img src=x onerror=alert(1)>'), '&lt;img src=x onerror=alert(1)&gt;')
  assert.equal(inlineFormat('**<script>alert(1)</script>**'),
    '<strong class="hl">&lt;script&gt;alert(1)&lt;/script&gt;</strong>')
  assert.equal(inlineFormat('a & b'), 'a &amp; b')
})
