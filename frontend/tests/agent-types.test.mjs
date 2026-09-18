import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { ref, computed, watch, nextTick } from 'vue'

const source = await readFile(new URL('../src/views/Agents.vue', import.meta.url), 'utf8')
const code = source.slice(source.indexOf('const allSectionGroups ='), source.indexOf('const statusText ='))
test('type switching exposes applicable sections and restores LLM configuration', async () => {
  const editingAgent = ref({ agent_type: 'llm', personality: '严谨' })
  const currentSection = ref('personality')
  const groups = new Function('ref', 'computed', 'watch', 'editingAgent', 'currentSection', code + '\nreturn sectionGroups')(ref, computed, watch, editingAgent, currentSection)
  const ids = () => groups.value.flatMap(group => group.items.map(item => item.id))
  assert.ok(ids().includes('personality'))
  assert.ok(!ids().includes('proxy'))
  editingAgent.value.agent_type = 'proxy'
  await nextTick()
  assert.deepEqual(ids(), ['basic', 'proxy', 'schema', 'versions'])
  assert.equal(currentSection.value, 'basic')
  currentSection.value = 'proxy'
  editingAgent.value.agent_type = 'llm'
  await nextTick()
  assert.equal(currentSection.value, 'basic')
  assert.ok(ids().includes('model'))
  assert.equal(editingAgent.value.personality, '严谨')
})
