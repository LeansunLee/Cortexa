import test from 'node:test'
import assert from 'node:assert/strict'
import { restoreRejectedSend, filterAvailableConversations, sendErrorMessage } from '../src/utils/chatRecovery.js'

test('rejected sends restore task edits and remove only the unsent optimistic bubble', () => {
  const attempt = {id:7, text:'@数据部', drafts:[{agent_id:'a', task:'查询8月', context_mode:'manual', context_text:'上海'}]}
  const session = {messages:[{id:'saved',role:'user',content:'@数据部'}, {_attemptId:7,role:'user',content:'@数据部'}],input:'',collaborationDrafts:[]}
  restoreRejectedSend(session,attempt)
  assert.deepEqual(session.messages.map(m=>m.id),['saved'])
  assert.equal(session.input,attempt.text)
  assert.deepEqual(session.collaborationDrafts,attempt.drafts)
  session.collaborationDrafts[0].task='更新任务'
  assert.equal(attempt.drafts[0].task,'查询8月')
  session.messages.push({_attemptId:8,role:'user'})
  restoreRejectedSend(session,{...attempt,id:8})
  assert.equal(session.messages.length,1)
})

test('late list responses cannot resurrect locally deleted conversations', () => {
  assert.deepEqual(filterAvailableConversations([{id:'deleted'},{id:'live'}],new Set(['deleted'])),[{id:'live'}])
})

test('404 and validation failures provide actionable server details', () => {
  assert.match(sendErrorMessage(404),/新建对话/)
  assert.match(sendErrorMessage(422,[{msg:'协作任务不能为空'}]),/协作任务不能为空/)
  assert.match(sendErrorMessage(403,'无权使用该 Agent'),/无权使用/)
})
