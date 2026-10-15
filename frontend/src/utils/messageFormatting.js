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

export function renderCitationMarkers(html) {
  return String(html ?? '').replace(new RegExp(`${CITE_TOKEN}(\\d+)${CITE_TOKEN}`, 'g'),
    (m, i) => `<sup class="cite-marker" data-source="${i}" role="button" tabindex="-1">[${Number(i) + 1}]</sup>`)
}
