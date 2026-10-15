export function inlineFormat(text) {
  const safe = String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return safe
    .replace(/\*\*(.*?)\*\*/g, '<strong class="hl">$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
}

// Citation markers: raw source URLs in assistant text become [n] markers,
// where n is the source's 1-based index in the message's sources list.
const CITE_TOKEN = '\u0001'

function sourceUrlIndex(url, sources) {
  const norm = (u) => String(u).replace(/\/+$/, '')
  const i = (sources || []).findIndex(s => s.type === 'web' && s.url && norm(s.url) === norm(url))
  return i < 0 ? null : i
}

export function applyCitationMarkers(content, sources) {
  const text = String(content ?? '')
  if (!text || !(sources || []).some(s => s.type === 'web' && s.url)) return text
  let out = text.replace(/\[([^\]]*)\]\((https?:\/\/[^)\s]+)\)/g, (m, label, url) => {
    const i = sourceUrlIndex(url, sources)
    return i === null ? m : `${CITE_TOKEN}${i}${CITE_TOKEN}`
  })
  out = out.replace(/(?<![\w"'=])(https?:\/\/[^\s<>"'）)\]}，。；！？、]+)/g, (m) => {
    const i = sourceUrlIndex(m, sources)
    return i === null ? m : `${CITE_TOKEN}${i}${CITE_TOKEN}`
  })
  return out
}

const GLOBE_SVG = '<svg class="cite-pill-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg>'
const escapeHtmlAttr = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

// Inline citation pills embedded in the answer text; each opens the source in a new tab.
export function renderCitationMarkers(html, sources) {
  return String(html ?? '').replace(new RegExp(`${CITE_TOKEN}(\\d+)${CITE_TOKEN}`, 'g'), (m, i) => {
    const src = (sources || [])[Number(i)]
    if (!src) return m
    const name = escapeHtmlAttr(src.name || src.url)
    return `<a class="cite-pill" href="${escapeHtmlAttr(src.url)}" target="_blank" rel="noopener" data-src-index="${Number(i)}">${GLOBE_SVG}<span class="cite-pill-name">${name}</span></a>`
  })
}
