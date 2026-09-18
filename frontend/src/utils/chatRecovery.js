export function restoreRejectedSend(session, attempt) {
  session.messages = session.messages.filter(message => message._attemptId !== attempt.id)
  session.input = attempt.text
  session.collaborationDrafts = JSON.parse(JSON.stringify(attempt.drafts))
}

export function filterAvailableConversations(rows, removed) {
  return rows.filter(row => !removed.has(row.id))
}

export function sendErrorMessage(status, detail) {
  if (status === 404) return '该对话已删除或无法访问。输入和协作任务已保留，可新建对话继续。'
  const explanation = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg).filter(Boolean).join('；') : ''
  return explanation ? `发送失败：${explanation}` : `发送失败：HTTP ${status}`
}
