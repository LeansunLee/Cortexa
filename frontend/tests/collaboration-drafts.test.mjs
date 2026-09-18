import test from 'node:test'
import assert from 'node:assert/strict'
import { syncDrafts, draftPayload, moveDraftOrder } from '../src/utils/collaborationDrafts.js'
const agents = [{id:'a',name:'数据部',agent_type:'proxy'}, {id:'b',name:'市场部',agent_type:'llm'}]
test('typed mentions create independent tasks and preserve edited tasks', () => {
  let cards = syncDrafts('@数据部 查8月销量，@市场部 制定推广计划', [], agents)
  assert.equal(cards.length, 2)
  assert.equal(cards[0].task, '')
  cards[0] = {...cards[0], task:'只查询浙江', dirty:true, supplemental_prompt:'本轮格式'}
  cards = syncDrafts('@数据部 查9月销量，@市场部 制定目标', cards, agents)
  assert.equal(cards[0].task, '只查询浙江')
  assert.equal(cards[1].task, '')
  assert.equal(draftPayload(cards)[0].supplemental_prompt, '本轮格式')
})
test('removed dependencies stay explicit for validation; duplicate mentions do not duplicate tasks', () => {
  let cards = syncDrafts('@数据部 查数据 @市场部 分析', [], agents)
  cards[1].depends_on = ['a']
  cards = syncDrafts('@市场部 分析', cards, agents)
  assert.deepEqual(cards[0].depends_on, ['a'])
  assert.equal(syncDrafts('@数据部 查数据 @数据部 汇总', [], agents).length, 1)
})

test('left/right ordering survives further typing and controls submitted order', () => {
  let cards = syncDrafts('@数据部 查询 @市场部 分析', [], agents)
  cards = moveDraftOrder(cards, 'b', -1)
  assert.deepEqual(cards.map(d=>d.agent_id), ['b','a'])
  cards = syncDrafts('@数据部 查询8月 @市场部 分析增长', cards, agents)
  assert.deepEqual(draftPayload(cards).map(d=>d.agent_id), ['b','a'])
  cards[1].depends_on = ['b']
  assert.throws(()=>moveDraftOrder(cards,'a',-1), /前置任务/)
  assert.deepEqual(cards.map(d=>d.agent_id), ['b','a'])
})
test('main input is never copied into an empty collaboration task', () => {
  const cards = syncDrafts('分析8月交付 @数据部 ', [], agents)
  assert.equal(draftPayload(cards, '分析8月交付 @数据部 ')[0].task, '')
})
