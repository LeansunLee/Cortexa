// Status events are sequential; only the newest unfinished step is running.
export function stepOutcome(step, index, steps, running = true) {
  const status = step.status || ''
  if (step.success === false || step.error || /error|fail/.test(status) ||
      /^(⚠|❌)/u.test(step.message || '') || /查询失败|查询出错/.test(step.message || '')) return 'error'
  if (step._done || /done|completed|skipped/.test(status) || status === 'tool_result') return 'done'
  return running && index === steps.length - 1 ? 'running' : 'done'
}

export function appendStatusStep(steps, event, message) {
  const step = { ...event, message, icon: event.status, detail: event.tool_desc || event.result_preview || '' }
  // Preserve failure information before presentation removes emoji.
  step.error = stepOutcome(event, 0, [event]) === 'error'
  const startStatus = event.status === 'tool_result' ? 'tool_call' : event.status?.replace(/_(done|failed|error)$/, '_start')
  const previous = steps.findLastIndex(s => s.status === startStatus && !s._done &&
    (!event.tool || !s.tool || s.tool === event.tool))
  if (startStatus !== event.status && previous >= 0) {
    steps[previous] = { ...steps[previous], ...step, _done: true }
  } else {
    steps.push(step)
  }
}
