export function highlightKeyContent(html) {
  const candidates = []
  const important = /结论|核心|关键|重点|建议|务必|必须|注意|风险|优先|推荐|summary|important|recommendation/i
  for (const block of html.matchAll(/<(p|li|td)\b[^>]*>([\s\S]*?)<\/\1>/g)) {
    for (const emphasis of block[2].matchAll(/<strong class="hl">([^<>]+)<\/strong>/g)) {
      const text = emphasis[1].trim()
      if (text.length < 2 || text.length > 48 || /[：:]$/.test(text)) continue
      candidates.push({ offset: block.index + block[0].indexOf(block[2]) + emphasis.index, length: text.length, priority: important.test(block[2]) ? 1 : 0 })
    }
  }
  const selected = new Set()
  let characters = 0
  for (const candidate of candidates.sort((left, right) => right.priority - left.priority || left.offset - right.offset)) {
    if (selected.size >= 3 || characters + candidate.length > 96) continue
    if (!candidate.priority && selected.size > 0) continue
    selected.add(candidate.offset)
    characters += candidate.length
  }
  return html.replace(/<strong class="hl">/g, (match, offset) => selected.has(offset) ? '<strong class="hl hl-key">' : match)
}
