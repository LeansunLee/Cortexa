export const glassPresets = [
  { name: '冰川蓝', value: '#009EFF', note: '映光 · 冰川蓝' },
  { name: '极光紫', value: '#8B38FF', note: '映光 · 极光紫' },
  { name: '薄荷青', value: '#00C9A7', note: '映光 · 薄荷青' },
  { name: '琥珀金', value: '#FF9F0A', note: '映光 · 琥珀金' },
  { name: '樱花粉', value: '#FF2D75', note: '映光 · 樱花粉' },
  { name: '熔岩红', value: '#FF3344', note: '映光 · 熔岩红' },
  { name: '烟晶灰', value: '#718096', note: '映光 · 烟晶灰' },
  { name: '深海蓝', value: '#0067E0', note: '映光 · 深海蓝' },
  { name: '孔雀青', value: '#00C2D7', note: '映光 · 孔雀青' },
  { name: '青柠绿', value: '#78D600', note: '映光 · 青柠绿' },
  { name: '珊瑚橙', value: '#FF672A', note: '映光 · 珊瑚橙' },
  { name: '葡萄紫', value: '#C13CFF', note: '映光 · 葡萄紫' },
  { name: '暮光靛', value: '#5364FF', note: '映光 · 暮光靛' },
  { name: '月光银', value: '#9DB6CA', note: '映光 · 月光银' },
].map(color => ({ ...color, mode: 'glass' }))

export const glassFinishes = [
  { value: 'clear', label: '液态' },
  { value: 'frosted', label: '磨砂' },
]

export function glassEdgeAlpha(glow = 20) {
  const value = Number(glow)
  const normalized = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 20))
  // 压缩常驻边缘泛光：0% 仍保留约原 10% 的弱亮边，100% 约等于原 50%。
  return String((10 + normalized * 0.4) / 200)
}

const frostedGrain = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='96' height='96' viewBox='0 0 96 96'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.82' numOctaves='4' seed='7'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3CfeComponentTransfer%3E%3CfeFuncA type='table' tableValues='0 .16'/%3E%3C/feComponentTransfer%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.48'/%3E%3C/svg%3E")`

export function glassImage(rgb, reflection = 0.16, finish = 'clear') {
  const frosted = finish === 'frosted'
  const color = rgb.join(',')
  if (frosted) return [
    `radial-gradient(ellipse at 100% 100%, rgba(${color},var(--glass-edge-alpha, .10)) 0%, transparent 72%)`,
    `radial-gradient(ellipse at 0% 0%, rgba(${color},calc(var(--glass-edge-alpha, .10) * .3)) 0%, transparent 48%)`,
    'linear-gradient(175deg, rgba(255,255,255,.20), transparent 24%)',
    frostedGrain,
    'linear-gradient(145deg, light-dark(rgba(255,255,255,.58),rgba(255,255,255,.15)) 0%, light-dark(rgba(244,248,252,.38),rgba(255,255,255,.075)) 58%, light-dark(rgba(235,241,247,.50),rgba(255,255,255,.11)) 100%)',
  ].join(', ')
  // A clear lens has a quiet centre and narrow highlights near its perimeter.
  // Keep the reflection parameter local to this surface (buttons, swatches,
  // navigation) instead of painting a bright conic wash over the whole shape.
  const intensity = Math.max(0, Math.min(1, Number(reflection) || 0))
  return [
    `radial-gradient(110px 58px at 100% 100%, rgba(${color},calc(var(--glass-edge-alpha, .10) * ${(.48 + intensity).toFixed(2)})) 0%, transparent 100%)`,
    `radial-gradient(100px 42px at 0% 0%, rgba(255,255,255,calc(var(--glass-edge-alpha, .10) * ${(.32 + intensity).toFixed(2)})) 0%, transparent 100%)`,
    `linear-gradient(180deg, rgba(255,255,255,calc(var(--glass-edge-alpha, .10) * ${(.24 + intensity).toFixed(2)})) 0%, transparent 16%)`,
    'linear-gradient(150deg, light-dark(rgba(255,255,255,.045),rgba(255,255,255,.025)), transparent 42%, light-dark(rgba(255,255,255,.02),rgba(255,255,255,.015)))',
  ].join(', ')
}

export function glassSwatch(value, finish = 'clear', glow = 20) {
  const rgb = [1, 3, 5].map(index => parseInt(value.slice(index, index + 2), 16))
  const frosted = finish === 'frosted'
  return {
    '--glass-light-color': rgb.join(','),
    '--glass-edge-alpha': glassEdgeAlpha(glow),
    backgroundColor: frosted ? 'light-dark(rgba(240,245,249,.82),rgba(227,235,243,.16))' : 'light-dark(rgba(255,255,255,.10),rgba(255,255,255,.018))',
    backgroundImage: glassImage(rgb, frosted ? 0.22 : 0.20, finish),
    backgroundOrigin: 'border-box',
    backgroundRepeat: 'no-repeat',
    boxShadow: frosted
      ? 'inset 0 1px 0 rgba(255,255,255,.72), inset 0 0 12px rgba(255,255,255,.22), 0 5px 14px rgba(15,23,42,.13)'
      : 'inset 0 1px 0 rgba(255,255,255,.98), inset 1px 0 0 rgba(255,255,255,.58), inset 0 -1px 0 rgba(15,23,42,.18), 0 5px 14px rgba(15,23,42,.16)',
  }
}
