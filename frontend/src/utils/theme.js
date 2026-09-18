import { preferenceKey } from './preferences.js'
import { texturePresets, textureImage, validTexture } from './textures.js'
import { glassPresets, glassImage, glassSwatch, glassEdgeAlpha } from './glass.js'
import { solidNotes } from './solidNotes.js'

// A restrained palette inspired by contemporary hardware and interface colors.
// These are app theme choices, not official Apple product color specifications.
const softColors = [
  { name: '石墨黑', value: '#42454A', note: '沉静石墨' },
  { name: '雾银灰', value: '#AEB3BA', note: '冷调银灰' },
  { name: '原色钛', value: '#A69D91', note: '温润岩灰' },
  { name: '星光金', value: '#D8C9AE', note: '柔和香槟' },
  { name: '深海蓝', value: '#34465C', note: '深邃午夜' },
  { name: '经典蓝', value: '#3478D4', note: '清晰明快' },
  { name: '冰川蓝', value: '#91B5CC', note: '轻盈雾蓝' },
  { name: '薄荷绿', value: '#A4C6B5', note: '清新浅绿' },
  { name: '鼠尾草', value: '#8C9D83', note: '自然灰绿' },
  { name: '松针绿', value: '#49695E', note: '沉稳森林' },
  { name: '薰衣草', value: '#B8ACCF', note: '柔雾浅紫' },
  { name: '鸢尾紫', value: '#8072AC', note: '雅致灰紫' },
  { name: '玫瑰粉', value: '#D3A5AD', note: '温柔蔷薇' },
  { name: '珊瑚橙', value: '#D5967C', note: '暖调杏橙' },
]

const vividColors = [
  { name: '电光蓝', value: '#0066FF', note: '鲜亮纯蓝' },
  { name: '天际蓝', value: '#0EA5E9', note: '明澈天蓝' },
  { name: '靛青蓝', value: '#4F46E5', note: '浓郁蓝紫' },
  { name: '电气紫', value: '#9333EA', note: '明艳紫罗兰' },
  { name: '莓果紫', value: '#B517CC', note: '浓艳莓紫' },
  { name: '洋红粉', value: '#D6008F', note: '大胆亮粉' },
  { name: '绯红', value: '#E11D48', note: '鲜明莓红' },
  { name: '烈焰红', value: '#EF2929', note: '热烈正红' },
  { name: '活力橙', value: '#F97316', note: '热烈橘橙' },
  { name: '向日黄', value: '#EAB308', note: '明亮金黄' },
  { name: '青柠绿', value: '#84CC16', note: '清爽黄绿' },
  { name: '翡翠绿', value: '#00A86B', note: '鲜活翠绿' },
  { name: '薄荷青', value: '#00B8A9', note: '清透碧绿' },
  { name: '碧海青', value: '#00A6C8', note: '通透青蓝' },
]

const contrastColors = [
  { name: '蓝橙交响', value: '#2563EB', accent: '#F97316', note: '钴蓝 × 活力橙' },
  { name: '紫柠电波', value: '#7C3AED', accent: '#A3D923', note: '电紫 × 青柠' },
  { name: '莓绿花园', value: '#C02675', accent: '#059669', note: '莓粉 × 翡翠绿' },
  { name: '红蓝竞速', value: '#DC2626', accent: '#2563EB', note: '正红 × 亮蓝' },
  { name: '青橙假日', value: '#0891B2', accent: '#EA580C', note: '湖青 × 橘橙' },
  { name: '紫金暮光', value: '#6D28D9', accent: '#EAB308', note: '深紫 × 金黄' },
  { name: '墨绿桃粉', value: '#166B50', accent: '#F472B6', note: '墨绿 × 桃粉' },
  { name: '海军珊瑚', value: '#243B64', accent: '#F07868', note: '海军蓝 × 珊瑚' },
  { name: '靛蓝琥珀', value: '#4338CA', accent: '#F59E0B', note: '靛蓝 × 琥珀' },
  { name: '洋红冰青', value: '#C218B0', accent: '#06B6D4', note: '洋红 × 冰青' },
  { name: '赤陶碧蓝', value: '#B84A32', accent: '#0284C7', note: '赤陶 × 碧蓝' },
  { name: '森林日光', value: '#237045', accent: '#FACC15', note: '森林绿 × 明黄' },
  { name: '酒红薄荷', value: '#8F2347', accent: '#2DD4BF', note: '酒红 × 薄荷' },
  { name: '石墨霓虹', value: '#343842', accent: '#B4E61D', note: '石墨 × 荧光绿' },
]

const gradientColors = [
  { name: '极光蓝紫', value: '#2563EB', accent: '#9333EA', note: '湛蓝 → 电紫' },
  { name: '海盐青蓝', value: '#06B6D4', accent: '#2563EB', note: '湖青 → 海蓝' },
  { name: '莓果晚霞', value: '#DB2777', accent: '#7C3AED', note: '莓粉 → 暮紫' },
  { name: '落日余晖', value: '#F97316', accent: '#E11D48', note: '暖橙 → 绯红' },
  { name: '橙金日出', value: '#EAB308', accent: '#EA580C', note: '金黄 → 橘橙' },
  { name: '薄荷森林', value: '#14B8A6', accent: '#15803D', note: '薄荷 → 森绿' },
  { name: '翡翠海湾', value: '#10B981', accent: '#0284C7', note: '翠绿 → 碧蓝' },
  { name: '青柠微风', value: '#84CC16', accent: '#059669', note: '青柠 → 翡翠' },
  { name: '薰衣晨光', value: '#A78BFA', accent: '#EC4899', note: '浅紫 → 桃粉' },
  { name: '玫瑰珊瑚', value: '#F472B6', accent: '#F97316', note: '玫瑰 → 珊瑚橙' },
  { name: '深海星夜', value: '#0F766E', accent: '#4338CA', note: '深青 → 靛蓝' },
  { name: '紫晶星云', value: '#4F46E5', accent: '#C026D3', note: '靛蓝 → 兰紫' },
  { name: '红丝绒', value: '#EF4444', accent: '#9D174D', note: '赤红 → 酒红' },
  { name: '石墨暮蓝', value: '#334155', accent: '#2563EB', note: '石墨 → 宝蓝' },
].map(color => ({ ...color, mode: 'gradient' }))

export const solidCategories = ['经典', '科技', '马卡龙', '莫兰迪', '糖果宝石', '东方美学', '欧式宫廷']
const categorized = (colors, category) => colors.map(color => ({ ...color, category }))
const palette = (category, entries) => entries.map(([name, value]) => ({ name, value, note: category, category }))
const solidColors = [
  ...categorized(softColors.slice(0, 7), '经典'),
  ...palette('经典', [['经典红','#C43C39'],['暖橘','#D97932'],['明黄','#D5AE32'],['常青绿','#358354'],['孔雀青','#268A91'],['经典紫','#8056A3'],['蔷薇粉','#C56891']]),
  ...categorized(vividColors.slice(0, 7), '科技'),
  ...palette('科技', [['离子橙','#FF7A18'],['光子黄','#F3C623'],['荧光绿','#69D52F'],['赛博青','#00D4C8'],['太空银','#B7C3D0'],['碳素黑','#242B36'],['铜芯棕','#A86F42']]),
  ...palette('马卡龙', [['奶油杏','#F0D5B5'],['草莓奶昔','#EABACB'],['蓝莓慕斯','#C5B8E8'],['薄荷奶绿','#B5DECE'],['海盐苏打','#B2D8ED'],['柠檬布丁','#EADD9E'],['蜜桃雪酪','#EFC3B1'],['开心果','#CFDDB4']]),
  ...palette('马卡龙', [['覆盆子糖霜','#DF9FA5'],['香橙奶冻','#EBC299'],['青柚冰沙','#A9D9D9'],['可可奶盖','#C5AD9C'],['香草奶白','#EEE6D6'],['燕麦灰','#C9C5C0']]),
  ...categorized(softColors.slice(7), '莫兰迪'),
  ...palette('莫兰迪', [['陶土红','#A87873'],['芥末黄','#B7AA78'],['雾霭蓝','#8598AB'],['灰湖青','#7E9E9C'],['暖石灰','#B3ADA7'],['烟墨','#595C60'],['榛果棕','#968274']]),
  ...categorized(vividColors.slice(7), '糖果宝石'),
  ...palette('糖果宝石', [['蓝宝石','#2455CE'],['紫晶糖','#8B3DC8'],['玫瑰碧玺','#DE4D95'],['海蓝宝','#60CFE0'],['烟水晶','#966446'],['月光珍珠','#E7E5DF'],['黑曜石','#302D3B']]),
  ...palette('东方美学', [['朱砂','#B83B35'],['黛青','#34545C'],['天青','#7DA6A4'],['藕荷','#B79AA8'],['竹青','#66835B'],['秋香','#B4A264'],['胭脂','#A84261'],['月白','#BECFD4']]),
  ...palette('东方美学', [['赭橙','#C5804B'],['琉璃蓝','#386D9A'],['紫棠','#78516F'],['茶褐','#886E53'],['宣纸白','#E8E0CD'],['松烟墨','#393D3B']]),
  ...palette('欧式宫廷', [['勃艮第红','#762B42'],['皇家蓝','#304C8C'],['翡翠宫墙','#276657'],['古典金','#B29959'],['紫罗兰绒','#765180'],['象牙白','#DED3BD'],['玫瑰铜','#BC8D79'],['墨玉黑','#34433F']]),
  ...palette('欧式宫廷', [['巴洛克橙','#BE733E'],['孔雀珐琅','#38858B'],['洛可可粉','#C48FA6'],['胡桃木','#795B47'],['银器灰','#A9ADB4'],['香槟金','#CBBE93']]),
]

for (const category of solidCategories) {
  solidColors.filter(color => color.category === category).forEach((color, index) => {
    color.note = solidNotes[category][index]
  })
}

export const themeGroups = [
  { id: 'solid', name: '纯色', colors: solidColors },
  { id: 'contrast', name: '撞色', colors: contrastColors },
  { id: 'gradient', name: '渐变', colors: gradientColors },
  { id: 'glass', name: '玻璃', colors: glassPresets },
  { id: 'texture', name: '纹理', colors: texturePresets },
]
export const themeColors = themeGroups.flatMap(group => group.colors)

const validColor = color => /^#[0-9a-f]{6}$/i.test(color || '')
const channels = color => [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16))
const hex = rgb => '#' + rgb.map(value => Math.round(value).toString(16).padStart(2, '0')).join('')
const luminance = rgb => rgb.map(value => {
  const channel = value / 255
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
}).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0)

export function normalizeTheme(theme) {
  if (validColor(theme)) return { value: theme.toUpperCase() }
  if (theme && validColor(theme.value) && (!theme.accent || validColor(theme.accent))) {
    const value = theme.value.toUpperCase()
    // Retire split themes while preserving each account's chosen primary color.
    if (theme.mode === 'tricolor' || theme.mode === 'texture') {
      return { value, mode: 'texture', texture: validTexture(theme.texture) ? theme.texture : 'wood' }
    }
    if (theme.mode === 'glass') return { value, mode: 'glass', finish: theme.finish === 'frosted' ? 'frosted' : 'clear', ...(typeof theme.glow === 'number' && Number.isFinite(theme.glow) ? { glow: Math.max(0, Math.min(100, Math.round(theme.glow))) } : {}) }
    if (theme.mode === 'skeuo') return { value }
    return { value, ...(theme.accent ? { accent: theme.accent.toUpperCase() } : {}), ...(theme.accent && theme.mode === 'gradient' ? { mode: 'gradient' } : {}) }
  }
  return { value: '#7C3AED' }
}

export function readTheme(storage = localStorage) {
  // Keep legacy single-color values; store pairs atomically in the same key.
  try {
    for (const key of preferenceKey('theme-color', storage) === 'theme-color' ? ['theme-color', 'themeColor'] : [preferenceKey('theme-color', storage)]) {
      const saved = storage.getItem(key)
      if (validColor(saved)) return saved.toUpperCase()
      try {
        const pair = JSON.parse(saved)
        if (pair && validColor(pair.value) && (!pair.accent || validColor(pair.accent))) return normalizeTheme(pair)
      } catch { /* Try the legacy key if the saved value is malformed. */ }
    }
  } catch { /* Storage can be disabled by the browser. */ }
  return '#7C3AED'
}

function readableChannels(color) {
  let rgb = channels(color)
  while (luminance(rgb) > 0.175) rgb = rgb.map(value => Math.floor(value * 0.96))
  return rgb
}

export function themeVariables(color) {
  const theme = normalizeTheme(color)
  const rgb = readableChannels(theme.value)
  const accent = readableChannels(theme.accent || theme.value)
  let glassRgb = [...rgb]
  while (luminance(glassRgb) > 0.11) glassRgb = glassRgb.map(value => Math.floor(value * 0.95))
  const glass = theme.mode === 'glass'
  const frosted = glass && theme.finish === 'frosted'
  const reflectionRgb = channels(theme.value)
  const reflection = reflectionRgb.join(',')
  const glassInk = hex(glassRgb)
  const glassGlow = hex(glassRgb.map(value => value + (255 - value) * 0.62))
  const glassControlBackdrop = glass ? frosted ? 'blur(28px) saturate(108%) contrast(101%) brightness(1.02)' : 'blur(14px) saturate(176%) contrast(114%) brightness(1.06)' : 'none'
  const glassSurfaceBackdrop = glass ? frosted ? 'blur(34px) saturate(110%) contrast(101%) brightness(1.01)' : 'blur(18px) saturate(184%) contrast(116%) brightness(1.07)' : 'none'
  const glassMenuBackdrop = glass ? frosted ? 'blur(38px) saturate(110%) contrast(101%) brightness(1.01)' : 'blur(24px) saturate(192%) contrast(118%) brightness(1.08)' : 'none'
  const glassSurfaceBackground = glass ? frosted ? 'light-dark(color-mix(in srgb, var(--surface) 90%, transparent), color-mix(in srgb, var(--surface) 92%, transparent))' : 'light-dark(color-mix(in srgb, var(--surface) 66%, transparent), color-mix(in srgb, var(--surface) 78%, transparent))' : 'var(--surface)'
  const glassSurfaceBackgroundStrong = glass ? frosted ? 'light-dark(color-mix(in srgb, var(--surface) 95%, transparent), color-mix(in srgb, var(--surface) 96%, transparent))' : 'light-dark(color-mix(in srgb, var(--surface) 78%, transparent), color-mix(in srgb, var(--surface) 86%, transparent))' : 'var(--surface)'
  const glassPanelBackground = glass ? frosted ? 'light-dark(color-mix(in srgb, var(--surface) 91%, transparent), color-mix(in srgb, var(--surface) 94%, transparent))' : 'light-dark(color-mix(in srgb, var(--surface) 70%, transparent), color-mix(in srgb, var(--surface) 84%, transparent))' : 'var(--surface)'
  const glassMenuBackground = glass ? frosted ? 'light-dark(color-mix(in srgb, var(--surface) 94%, transparent), color-mix(in srgb, var(--surface) 96%, transparent))' : 'light-dark(color-mix(in srgb, var(--surface) 72%, transparent), color-mix(in srgb, var(--surface) 88%, transparent))' : 'var(--surface)'
  const glassSearchBackground = glass ? frosted ? 'light-dark(color-mix(in srgb, var(--surface) 97%, transparent), color-mix(in srgb, var(--surface) 98%, transparent))' : 'light-dark(color-mix(in srgb, var(--surface) 82%, transparent), color-mix(in srgb, var(--surface) 90%, transparent))' : 'var(--surface2)'
  const liquidRefractionGradient = [
    'radial-gradient(ellipse at 8% -12%, rgba(255,255,255,.78) 0%, rgba(255,255,255,.22) 23%, transparent 48%)',
    'radial-gradient(ellipse at 102% 110%, rgba(' + reflection + ',.34) 0%, transparent 60%)',
    'conic-gradient(from 218deg at 9% 3%, rgba(255,255,255,.54), transparent 17%, rgba(' + reflection + ',.18) 30%, transparent 47%, rgba(255,255,255,.30) 71%, transparent 100%)',
    'linear-gradient(116deg, rgba(255,255,255,.46) 0%, rgba(255,255,255,.08) 15%, transparent 34%, rgba(' + reflection + ',.12) 64%, rgba(255,255,255,.28) 100%)',
    'linear-gradient(92deg, transparent 0%, rgba(255,255,255,.34) 48%, transparent 54%)',
  ].join(', ')
  const frostedRefractionGradient = [
    'radial-gradient(ellipse at 0% 0%, rgba(255,255,255,.26) 0%, transparent 54%)',
    'radial-gradient(ellipse at 100% 100%, rgba(' + reflection + ',.10) 0%, transparent 68%)',
    'linear-gradient(145deg, rgba(255,255,255,.18), rgba(255,255,255,.08) 42%, rgba(255,255,255,.14))',
  ].join(', ')
  const glassSurfaceGradient = glass ? (frosted ? frostedRefractionGradient : liquidRefractionGradient) + ', ' + glassImage(reflectionRgb, frosted ? 0.12 : 0.34, theme.finish) : 'none'
  const glassPanelGradient = glass ? [
    frosted
      ? 'linear-gradient(180deg, light-dark(rgba(255,255,255,calc(var(--glass-edge-alpha) * .34)),rgba(255,255,255,calc(var(--glass-edge-alpha) * .22))) 0%, transparent 12%)'
      : 'linear-gradient(180deg, light-dark(rgba(255,255,255,calc(var(--glass-edge-alpha) * .42)),rgba(255,255,255,calc(var(--glass-edge-alpha) * .26))) 0%, transparent 10%)',
    frosted
      ? 'linear-gradient(90deg, rgba(255,255,255,calc(var(--glass-edge-alpha) * .12)) 0%, transparent 7%, transparent 93%, rgba(255,255,255,calc(var(--glass-edge-alpha) * .10)) 100%)'
      : 'linear-gradient(90deg, rgba(255,255,255,calc(var(--glass-edge-alpha) * .16)) 0%, transparent 6%, transparent 94%, rgba(255,255,255,calc(var(--glass-edge-alpha) * .12)) 100%)',
    'radial-gradient(ellipse at 96% 4%, rgba(' + reflection + ',calc(var(--glass-edge-alpha) * ' + (frosted ? '.10' : '.14') + ')) 0%, transparent 16%)',
    frosted
      ? 'linear-gradient(145deg, rgba(255,255,255,calc(var(--glass-edge-alpha) * .07)) 0%, transparent 24%, rgba(255,255,255,calc(var(--glass-edge-alpha) * .05)) 100%)'
      : 'linear-gradient(145deg, rgba(255,255,255,calc(var(--glass-edge-alpha) * .08)) 0%, transparent 22%, rgba(255,255,255,calc(var(--glass-edge-alpha) * .04)) 100%)',
  ].join(', ') : 'none'
  const glassMenuGradient = glass ? (frosted ? frostedRefractionGradient : liquidRefractionGradient) + ', ' + glassImage(reflectionRgb, frosted ? 0.16 : 0.44, theme.finish) : 'none'
  return {
    '--glass-finish': glass ? theme.finish || 'clear' : 'none',
    '--glass-rgb': reflection,
    '--glass-control-backdrop': glassControlBackdrop,
    '--glass-surface-backdrop': glassSurfaceBackdrop,
    '--glass-menu-backdrop': glassMenuBackdrop,
    '--glass-surface-background': glassSurfaceBackground,
    '--glass-surface-background-strong': glassSurfaceBackgroundStrong,
    '--glass-panel-background': glassPanelBackground,
    '--glass-menu-background': glassMenuBackground,
    '--glass-search-background': glassSearchBackground,
    '--glass-surface-gradient': glassSurfaceGradient,
    '--glass-panel-gradient': glassPanelGradient,
    '--glass-menu-gradient': glassMenuGradient,
    '--glass-selection-background': glass ? frosted ? 'color-mix(in srgb, var(--surface) 78%, var(--primary-light))' : 'color-mix(in srgb, var(--surface) 58%, var(--primary-light))' : 'var(--primary-light)',
    '--glass-edge-shadow': glass ? frosted ? 'inset 0 1px 0 rgba(255,255,255,calc(var(--glass-edge-alpha) * 1.16)), inset 0 -1px 0 rgba(255,255,255,calc(var(--glass-edge-alpha) * .24)), inset 0 0 18px rgba(255,255,255,calc(var(--glass-edge-alpha) * .24)), 0 18px 42px rgba(15,23,42,.16)' : 'inset 0 1px 0 rgba(255,255,255,calc(var(--glass-edge-alpha) * 1.96)), inset 1px 0 0 rgba(255,255,255,calc(var(--glass-edge-alpha) * 1.08)), inset -1px 0 0 rgba(255,255,255,calc(var(--glass-edge-alpha) * .44)), inset 0 -1px 0 rgba(15,23,42,calc(var(--glass-edge-alpha) * .40)), 0 20px 52px rgba(15,23,42,.22)' : 'none',
    '--glass-light-color': reflectionRgb.join(','),
    '--glass-edge-alpha': glassEdgeAlpha(theme.glow ?? 20),
    '--glass-edge-border': glass ? `rgba(${reflection}, calc(var(--glass-edge-alpha) * ${frosted ? '.42' : '.80'}))` : 'var(--border)',
    '--glass-edge-border-soft': glass ? `rgba(${reflection}, calc(var(--glass-edge-alpha) * ${frosted ? '.24' : '.44'}))` : 'var(--border)',
    '--warning': 'light-dark(#92400E, #FBBF24)',
    '--warning-bg': 'light-dark(#FFFBEB, rgba(245,158,11,.14))',
    '--info': 'light-dark(#1E40AF, #93C5FD)',
    '--info-bg': 'light-dark(#EFF6FF, rgba(59,130,246,.14))',
    '--primary-bg': `rgba(${rgb.join(',')},0.08)`,
    '--navigation-icon': `light-dark(${hex(accent)}, ${hex(accent.map(value => value + (255 - value) * .60))})`,
    '--theme-button-background': glass ? frosted ? 'light-dark(rgba(240,245,249,0.76),rgba(227,235,243,0.15))' : 'light-dark(rgba(255,255,255,0.08),rgba(255,255,255,0.018))' : hex(rgb),
    '--theme-button-hover-background': glass ? frosted ? 'light-dark(rgba(244,248,251,0.84),rgba(235,241,247,0.20))' : 'light-dark(rgba(255,255,255,0.14),rgba(255,255,255,0.035))' : hex(rgb.map(value => value * 0.85)),
    '--theme-button-border': glass ? frosted ? 'light-dark(rgba(255,255,255,0.82),rgba(255,255,255,0.32))' : 'light-dark(rgba(255,255,255,0.96),rgba(255,255,255,0.45))' : 'transparent',
    '--theme-button-shadow': glass ? frosted ? 'inset 0 1px 0 rgba(255,255,255,.68), inset 0 0 12px rgba(255,255,255,.18), 0 5px 14px rgba(15,23,42,.13)' : 'inset 0 1px 0 rgba(255,255,255,.98), inset 1px 0 0 rgba(255,255,255,.58), inset 0 -1px 0 rgba(15,23,42,.20), 0 5px 14px rgba(15,23,42,.16)' : 'none',
    '--theme-button-active-shadow': glass ? 'inset 0 3px 6px rgba(0,0,0,.45), inset 0 -1px 0 rgba(255,255,255,.16)' : 'var(--theme-button-shadow)',
    '--theme-backdrop': glassControlBackdrop,
    '--theme-gradient': glass ? glassImage(reflectionRgb, frosted ? 0.15 : 0.20, theme.finish) : theme.mode === 'texture' ? textureImage(theme.texture) : theme.mode === 'gradient' ? `linear-gradient(135deg, ${hex(rgb)}, ${hex(accent)})` : 'none',
    '--theme-gradient-hover': glass ? glassImage(reflectionRgb, frosted ? 0.28 : 0.38, theme.finish) : theme.mode === 'texture' ? textureImage(theme.texture, 0.20) : theme.mode === 'gradient' ? `linear-gradient(135deg, ${hex(rgb.map(c => c * .85))}, ${hex(accent.map(c => c * .85))})` : 'none',
    '--navigation-background': glass ? `${glassImage(reflectionRgb, frosted ? 0.11 : 0.14, theme.finish)}, linear-gradient(${frosted ? 'light-dark(rgba(240,245,249,.70),rgba(227,235,243,.12))' : 'light-dark(rgba(255,255,255,.07),rgba(255,255,255,.015))'},${frosted ? 'light-dark(rgba(240,245,249,.70),rgba(227,235,243,.12))' : 'light-dark(rgba(255,255,255,.07),rgba(255,255,255,.015))'})` : theme.mode === 'gradient' ? `linear-gradient(135deg, rgba(${rgb.join(',')},0.10), rgba(${accent.join(',')},0.10))` : `rgba(${accent.join(',')},0.08)`,
    '--navigation-color': glass ? `light-dark(${glassInk}, ${glassGlow})` : `light-dark(${hex(accent)}, ${hex(accent.map(value => value + (255 - value) * .60))})`,
    '--theme-tag-background': glass ? `${glassImage(reflectionRgb, frosted ? 0.09 : 0.11, theme.finish)}, linear-gradient(${frosted ? 'light-dark(rgba(240,245,249,.68),rgba(227,235,243,.11))' : 'light-dark(rgba(255,255,255,.06),rgba(255,255,255,.012))'},${frosted ? 'light-dark(rgba(240,245,249,.68),rgba(227,235,243,.11))' : 'light-dark(rgba(255,255,255,.06),rgba(255,255,255,.012))'})` : `rgba(${accent.join(',')},0.08)`,
    '--primary': glass ? `light-dark(${hex(rgb)}, ${hex(rgb.map(value => value + (255 - value) * .35))})` : glass ? `light-dark(${glassInk}, ${glassGlow})` : `light-dark(${hex(rgb)}, ${hex(rgb.map(value => value + (255 - value) * .60))})`,
    '--primary-hover': hex(rgb.map(value => value * 0.85)),
    '--primary-light': glass ? `light-dark(rgba(${glassRgb.join(',')},0.08), rgba(${glassRgb.join(',')},0.22))` : `rgba(${rgb.join(',')},0.08)`,
    '--primary-text': glass ? 'light-dark(#17212B, #FFFFFF)' : '#FFFFFF',
    '--accent': glass ? `light-dark(${hex(rgb)}, ${hex(rgb.map(value => value + (255 - value) * .35))})` : glass ? `light-dark(${glassInk}, ${glassGlow})` : `light-dark(${hex(accent)}, ${hex(accent.map(value => value + (255 - value) * .60))})`,
    '--accent-light': glass ? `light-dark(rgba(${glassRgb.join(',')},0.08), rgba(${glassRgb.join(',')},0.22))` : `rgba(${accent.join(',')},0.08)`,
  }
}

export function swatchStyle(color) {
  if (color.mode === 'glass') return glassSwatch(color.value, color.finish, color.glow)
  if (color.mode === 'texture') return {
    backgroundColor: color.value, backgroundImage: textureImage(color.texture, 0.28),
    backgroundSize: '48px 48px', backgroundOrigin: 'border-box', backgroundRepeat: 'repeat',
  }
  const background = color.accent
    ? color.mode === 'gradient'
      ? `linear-gradient(135deg, ${color.value}, ${color.accent})`
      : `linear-gradient(135deg, ${color.value} 50%, ${color.accent} 50%)`
    : color.value
  // Include the translucent border in the gradient area so it cannot tile at the edges.
  return { background, backgroundOrigin: 'border-box', backgroundRepeat: 'no-repeat' }
}

export function applyTheme(color) {
  const theme = normalizeTheme(color)
  if (document.documentElement.dataset) {
    document.documentElement.dataset.colorTheme = theme.mode || 'solid'
    if (theme.mode === 'glass') document.documentElement.dataset.glassFinish = theme.finish || 'clear'
    else delete document.documentElement.dataset.glassFinish
  }
  Object.entries(themeVariables(theme)).forEach(([key, value]) => document.documentElement.style.setProperty(key, value))
}

export function saveTheme(color) {
  if (!validColor(color) && !(color && validColor(color.value) && (!color.accent || validColor(color.accent)))) return
  const theme = normalizeTheme(color)
  const saved = theme.accent || ['texture', 'glass', 'skeuo'].includes(theme.mode) ? theme : theme.value
  localStorage.setItem(preferenceKey('theme-color'), typeof saved === 'string' ? saved : JSON.stringify(saved))
  if (preferenceKey('theme-color') === 'theme-color') localStorage.removeItem('themeColor')
  applyTheme(saved)
  window.dispatchEvent(new CustomEvent('theme-change', { detail: saved }))
}
