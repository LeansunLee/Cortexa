export function avatarUrl(value) {
  if (typeof value !== 'string' || !/^\/static\/avatars\/[^/?#]+\.svg(?:[?#]|$)/.test(value)) return value
  const url = new URL(value, 'http://avatar.local')
  url.searchParams.set('v', 'portraits-20260922-1')
  return url.pathname + url.search + url.hash
}
