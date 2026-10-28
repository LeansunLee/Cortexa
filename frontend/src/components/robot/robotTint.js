// Theme recoloring for the 2D mascot — color AND material. The pixel art is
// essentially neutral (cool gray/white shell, dark visor), so every pixel is
// remapped along a 3-stop duotone ramp anchored on the theme primary. The
// theme's material (mode) changes HOW that ramp is applied:
//   solid    — plain duotone (default)
//   contrast — the near-white highlights take the accent color instead
//   gradient — the anchor hue slides value→accent from top to bottom
//   glass    — lighter ramp, translucent body (clear) or milky (frosted),
//              plus a themed outer glow via a CSS drop-shadow filter
//   texture  — subtle grain over the duotone, style keyed by texture family
//              (wood/water/sand bands, metal brushing, fabric weave, paper noise)
// The canvas face keeps its own readable palette. Results are cached per
// full material signature with a small eviction window.

const imageCache = new Map()
const artCache = new Map()
const MAX_CACHED_TINTS = 8

export const ROBOT_ART_SRC = (import.meta.env.BASE_URL || '/static/dist/') + 'themes/robot/'
// The PNGs live at stable URLs and browsers heuristically cache them for
// hours — bump the version whenever the art is regenerated so changes land.
export const ROBOT_ART_VERSION = '20261026.2'

export function robotArtUrl(name) {
  return `${ROBOT_ART_SRC}${name}?v=${ROBOT_ART_VERSION}`
}

const channels = color => [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16))
const mix = (a, b, t) => a.map((value, index) => value + (b[index] - value) * t)
const clamp255 = v => Math.max(0, Math.min(255, v))
// Deterministic per-pixel noise (no dependencies — same grain every render).
const hash = (x, y) => {
  let n = (x * 374761393 + y * 668265263) | 0
  n = Math.imul(n ^ (n >>> 13), 1274126177)
  return ((n ^ (n >>> 16)) >>> 0) / 4294967295
}

function loadImage(url) {
  if (!imageCache.has(url)) {
    imageCache.set(url, new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = () => { imageCache.delete(url); reject(new Error(`robot art failed: ${url}`)) }
      img.src = url
    }))
  }
  return imageCache.get(url)
}

// Grain styles for texture themes, keyed by texture family.
const GRAIN_BANDS = new Set(['wood', 'water', 'sand', 'pottery'])
const GRAIN_METAL = new Set(['steel', 'titanium', 'copper'])
const GRAIN_WEAVE = new Set(['linen', 'denim', 'herringbone'])
function grainDelta(texture, x, y) {
  if (GRAIN_METAL.has(texture)) {
    if (texture === 'copper') return hash(x >> 3, y >> 3) > 0.78 ? 6 : -2 + (hash(x, y) - 0.5) * 2
    return ((y % 3) - 1) * 2.6 + (hash(x, y) - 0.5) * 2
  }
  if (GRAIN_WEAVE.has(texture)) return ((x + y) % 4 < 2 ? 3 : -3) + (hash(x, y) - 0.5) * 2
  if (GRAIN_BANDS.has(texture)) return Math.sin(y * 0.22 + Math.sin(x * 0.05) * 2.2) * 5
  return (hash(x, y) - 0.5) * 7
}

function makeProcessor(theme, height) {
  const rgb = channels(theme.value)
  const accent = theme.accent ? channels(theme.accent) : null
  const mode = theme.mode || 'solid'
  const lighter = mode === 'glass'
  const frosted = mode === 'glass' && theme.finish === 'frosted'
  const grainTexture = mode === 'texture' ? (theme.texture || 'wood') : null

  const stopsFor = y => {
    let primary = rgb
    if (mode === 'gradient' && accent) {
      primary = mix(rgb, accent, Math.max(0, Math.min(1, y / (height - 1))))
    }
    return {
      dark: mix(primary, [8, 10, 14], lighter ? 0.6 : 0.72),
      mid: mix(primary, [255, 255, 255], lighter ? 0.58 : 0.45),
      light: (mode === 'contrast' && accent)
        ? mix(accent, [255, 255, 255], 0.62)
        : mix(primary, [255, 255, 255], lighter ? 0.95 : 0.9),
    }
  }
  const alphaScale = mode === 'glass' ? (frosted ? 0.95 : 0.8) : 1

  return (px, i, x, y) => {
    const a = px[i + 3]
    if (!a) return
    // Warm pixels stay warm (future-proofing for blush-like details).
    if (px[i] > px[i + 2] + 18) return
    const l = (0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]) / 255
    const from = l <= 0.5 ? 'dark' : 'mid'
    const to = l <= 0.5 ? 'mid' : 'light'
    const stops = stopsFor(y)
    const t = l <= 0.5 ? l * 2 : (l - 0.5) * 2
    let out = [0, 1, 2].map(c => stops[from][c] + (stops[to][c] - stops[from][c]) * t)
    if (frosted) {
      const gray = 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
      out = mix(out, [gray, gray, gray], 0.25)
    }
    if (grainTexture) {
      const d = grainDelta(grainTexture, x, y) * (0.45 + l * 0.55)
      out = [out[0] + d, out[1] + d, out[2] + d]
    }
    px[i] = clamp255(out[0])
    px[i + 1] = clamp255(out[1])
    px[i + 2] = clamp255(out[2])
    px[i + 3] = a * alphaScale
  }
}

function tintImage(img, process) {
  const canvas = document.createElement('canvas')
  canvas.width = img.naturalWidth
  canvas.height = img.naturalHeight
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  ctx.drawImage(img, 0, 0)
  const frame = ctx.getImageData(0, 0, canvas.width, canvas.height)
  const px = frame.data
  for (let y = 0; y < canvas.height; y++) {
    for (let x = 0; x < canvas.width; x++) process(px, (y * canvas.width + x) * 4, x, y)
  }
  ctx.putImageData(frame, 0, 0)
  return canvas.toDataURL('image/png')
}

// Glass themes get a themed halo on top of the standard contact shadow.
function glowFilter(theme) {
  if (theme.mode !== 'glass') return ''
  const glow = typeof theme.glow === 'number' && Number.isFinite(theme.glow) ? theme.glow : 20
  const [r, g, b] = channels(theme.value)
  const alpha = 0.25 + glow * 0.0035
  const radius = 6 + glow * 0.14
  return `drop-shadow(0 5px 12px rgba(15, 23, 42, .2)) drop-shadow(0 0 ${radius.toFixed(1)}px rgba(${r}, ${g}, ${b}, ${alpha.toFixed(2)}))`
}

// Resolves to { base, glow } for the (already normalized) theme object.
// The pixel art is cached WITHOUT the glow value — dragging the glass glow
// slider only re-computes the filter, never re-tints the canvas.
export function tintedRobotArt(theme) {
  const value = String(theme && theme.value || '').toUpperCase()
  if (!/^#[0-9A-F]{6}$/.test(value)) return Promise.reject(new Error(`bad theme color: ${theme && theme.value}`))
  const normalized = { ...theme, value }
  const key = JSON.stringify([normalized.value, normalized.accent || '', normalized.mode || '', normalized.finish || '', normalized.texture || ''])
  if (!artCache.has(key)) {
    artCache.set(key, loadImage(robotArtUrl('base.png')).then(base => ({
      base: tintImage(base, makeProcessor(normalized, base.naturalHeight)),
    })))
    if (artCache.size > MAX_CACHED_TINTS) artCache.delete(artCache.keys().next().value)
  }
  return artCache.get(key).then(art => ({ ...art, glow: glowFilter(normalized) }))
}
