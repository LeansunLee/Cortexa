export function syncDrafts(text, previous, agents) {
  const mentions = [...text.matchAll(/@([^\s@]+)/g)]
  const found = []
  for (let i = 0; i < mentions.length; i++) {
    const mention = mentions[i]
    const agent = agents.find(a => a.name === mention[1])
    if (!agent || found.some(d => d.agent_id === agent.id)) continue
    const suggested = ''
    const old = previous.find(d => d.agent_id === agent.id)
    found.push(old ? { ...old, agent_type: agent.agent_type || 'llm' } : {
      agent_id: agent.id, name: agent.name, agent_type: agent.agent_type || 'llm', task: suggested,
      constraints: [], expected_output: '给出专业分析和建议', supplemental_prompt: null,
      depends_on: [], dirty: false, suggested, basedOn: text,
    })
  }
  const order = new Map(previous.map((draft, index) => [draft.agent_id, index]))
  return found.sort((a, b) => (order.get(a.agent_id) ?? previous.length) - (order.get(b.agent_id) ?? previous.length))
}
export function draftPayload(drafts, input = '') {
  return drafts.map(({ agent_id, task, constraints, expected_output, supplemental_prompt, depends_on }) => ({ agent_id, task: task.trim(), constraints, expected_output, supplemental_prompt, depends_on }))
}

export function moveDraftOrder(drafts, id, direction) {
  const index = drafts.findIndex(d => d.agent_id === id)
  const next = index + direction
  if (index < 0 || next < 0 || next >= drafts.length) return drafts
  const ordered = [...drafts]
  ;[ordered[index], ordered[next]] = [ordered[next], ordered[index]]
  const positions = new Map(ordered.map((d, i) => [d.agent_id, i]))
  const invalid = ordered.find((d, i) => d.depends_on.some(dep => !positions.has(dep) || positions.get(dep) >= i))
  if (invalid) throw new Error(`${invalid.name} 需要等待前置任务，不能移到它前面。`)
  return ordered
}
