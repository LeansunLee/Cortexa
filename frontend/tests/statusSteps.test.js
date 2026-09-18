import test from 'node:test'
import assert from 'node:assert/strict'
import { appendStatusStep, stepOutcome } from '../src/utils/statusSteps.js'

test('completed search never spins even while answer is streaming', () => {
  const steps = []
  appendStatusStep(steps, { status: 'tool_call', tool: 'web_search' }, '搜索中')
  assert.equal(stepOutcome(steps[0], 0, steps), 'running')
  appendStatusStep(steps, { status: 'tool_result', tool: 'web_search' }, '查询完成')
  assert.equal(steps.length, 1)
  assert.equal(stepOutcome(steps[0], 0, steps), 'done')
})
test('matching completion replaces start and older sequential steps stop spinning', () => {
  const steps = [{ status: 'retrieval_plan' }]
  appendStatusStep(steps, { status: 'memory_start' }, '检索中')
  appendStatusStep(steps, { status: 'memory_done' }, '找到记忆')
  assert.equal(steps.length, 2)
  assert.equal(stepOutcome(steps[0], 0, steps), 'done')
  assert.equal(stepOutcome(steps[1], 1, steps), 'done')
})
test('failures survive emoji cleaning and completed history', () => {
  const steps = []
  appendStatusStep(steps, { status: 'tool_result', message: '⚠️ 查询完成' }, '查询完成')
  assert.equal(stepOutcome(steps[0], 0, steps, false), 'error')
  assert.equal(stepOutcome({status:'proxy_failed'}, 0, [], false), 'error')
})
test('background stream updates its own session only', () => {
  const foreground = [{ status: 'tool_call' }]
  const background = [{ status: 'tool_call' }]
  appendStatusStep(background, {status:'tool_result'}, '完成')
  assert.equal(foreground[0].status, 'tool_call')
  assert.equal(background[0].status, 'tool_result')
})
