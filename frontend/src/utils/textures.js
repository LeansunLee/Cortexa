// Small, seamless vector motifs: decorative interpretations, not material photographs.
export const texturePresets = [
  { texture: 'wood', name: '林间木纹', value: '#52684B', category: '自然', note: '自然 · 流动木理', motif: '<path d="M-8 8C8-4 28 20 56 8M-8 24C8 12 28 36 56 24M-8 40C8 28 28 52 56 40"/>' },
  { texture: 'water', name: '湖面涟漪', value: '#287B87', category: '自然', note: '自然 · 轻柔水波', motif: '<path d="M0 8Q12 0 24 8T48 8M0 24Q12 16 24 24T48 24M0 40Q12 32 24 40T48 40"/>' },
  { texture: 'sand', name: '风过沙丘', value: '#A27A50', category: '自然', note: '自然 · 起伏沙纹', motif: '<path d="M-12 48Q12 0 36 0M0 48Q24 0 48 0M12 48Q36 0 60 0M24 48Q48 0 72 0"/>' },
  { texture: 'steel', name: '拉丝银灰', value: '#687585', category: '金属', note: '金属 · 细密拉丝', motif: '<path d="M0 4H48M0 7H48M0 14H48M0 22H48M0 25H48M0 34H48M0 41H48M0 44H48"/>' },
  { texture: 'copper', name: '锤纹暖铜', value: '#A46545', category: '金属', note: '金属 · 手作锤痕', motif: '<circle cx="12" cy="12" r="8"/><circle cx="36" cy="36" r="8"/><circle cx="36" cy="12" r="5"/><circle cx="12" cy="36" r="5"/>' },
  { texture: 'titanium', name: '钛金微砂', value: '#817464', category: '金属', note: '金属 · 微砂颗粒', motif: '<path d="M4 7h1M17 19h1M35 5h1M43 28h1M8 38h1M29 42h1M26 29h1M45 45h1" stroke-width="2"/>' },
  { texture: 'linen', name: '亚麻经纬', value: '#93816B', category: '布艺', note: '布艺 · 交织纤维', motif: '<path d="M0 6H48M0 18H48M0 30H48M0 42H48M6 0V48M18 0V48M30 0V48M42 0V48"/>' },
  { texture: 'denim', name: '靛蓝斜纹', value: '#3E5E83', category: '布艺', note: '布艺 · 牛仔斜织', motif: '<path d="M-24 24L24-24M-12 36L36-12M0 48L48 0M12 60L60 12M24 72L72 24" stroke-width="3"/>' },
  { texture: 'herringbone', name: '羊毛人字', value: '#766277', category: '布艺', note: '布艺 · 人字织纹', motif: '<path d="M0 0L12 12 24 0 36 12 48 0M0 16L12 28 24 16 36 28 48 16M0 32L12 44 24 32 36 44 48 32"/>' },
  { texture: 'paper', name: '手抄纸笺', value: '#9B805C', category: '人文', note: '人文 · 纸中纤维', motif: '<path d="M3 8l7 2M26 5l-2 5M35 20l8-2M13 25l5 4M4 40l7-2M30 38l4 5M44 8l2 4"/>' },
  { texture: 'lattice', name: '窗棂光影', value: '#805C4D', category: '人文', note: '人文 · 几何窗格', motif: '<path d="M0 0H48V48H0ZM12 0V48M36 0V48M0 12H48M0 36H48M12 12L36 36M36 12L12 36"/>' },
  { texture: 'pottery', name: '陶轮留痕', value: '#AB6552', category: '人文', note: '人文 · 陶作旋纹', motif: '<path d="M0 5Q24 11 48 5M0 17Q24 23 48 17M0 29Q24 35 48 29M0 41Q24 47 48 41"/>' },
  { texture: 'bronze', name: '青铜回纹', value: '#47786B', category: '历史', note: '历史 · 回纹意趣', motif: '<path d="M0 0H48V48H0ZM8 8H40V40H8V16H32V32H16V24H24"/>' },
  { texture: 'arch', name: '石拱旧影', value: '#78716A', category: '历史', note: '历史 · 拱券线条', motif: '<path d="M0 48V24a24 24 0 0 1 48 0v24M8 48V24a16 16 0 0 1 32 0v24M16 48V24a8 8 0 0 1 16 0v24"/>' },
  { texture: 'mosaic', name: '古城镶嵌', value: '#456B94', category: '历史', note: '历史 · 菱形拼花', motif: '<path d="M24 0L48 24 24 48 0 24ZM24 12L36 24 24 36 12 24Z"/>' },
  { texture: 'ink-rain', name: '烟雨墨痕', value: '#53636A', category: '书艺', note: '书艺 · 疏密墨线', motif: '<path d="M4 0C3 12 8 23 5 48M16 0C20 15 13 29 17 48M29 0C25 13 33 31 28 48M41 0C45 16 38 34 43 48"/>' },
  { texture: 'calligraphy', name: '行草余韵', value: '#765B50', category: '书艺', note: '书艺 · 游丝笔意', motif: '<path d="M-4 14C8 3 16 24 29 11S48 8 54 2M-6 36C5 25 15 45 28 32S47 29 54 23" stroke-width="1.5"/>' },
  { texture: 'seal-script', name: '朱印篆纹', value: '#9B4948', category: '书艺', note: '书艺 · 古朴印痕', motif: '<path d="M5 5H43V43H5ZM12 12H24V20H18V28H30V36H36V22H28V12H36"/>' },
  { texture: 'manuscript', name: '旧稿横笺', value: '#8D7657', category: '书艺', note: '书艺 · 稿纸行线', motif: '<path d="M0 10H48M0 22H48M0 34H48M0 46H48M8 0V48"/><path d="M14 16h15M19 28h20M13 40h12" stroke-width="2"/>' },
  { texture: 'music-score', name: '夜曲谱线', value: '#515C78', category: '书艺', note: '书艺 · 五线节拍', motif: '<path d="M0 8H48M0 12H48M0 16H48M0 20H48M0 24H48"/><path d="M15 13v17M31 9v15" stroke-width="1.5"/><circle cx="11" cy="30" r="4"/><circle cx="27" cy="24" r="4"/>' },
  { texture: 'woodcut', name: '木刻刀痕', value: '#704F40', category: '绘艺', note: '绘艺 · 粗粝刻线', motif: '<path d="M-8 10L18-4M-2 23L36-3M-5 42L54 1M9 48L55 16M29 51L55 34" stroke-width="2"/>' },
  { texture: 'watercolor', name: '水彩晕染', value: '#647B91', category: '绘艺', note: '绘艺 · 轻柔色晕', motif: '<path d="M8 15C12 4 28 3 33 12s-3 17-14 17S3 25 8 15ZM31 30c6-7 17-3 15 6s-14 12-19 5 0-7 4-11Z"/>' },
  { texture: 'stipple', name: '铜版点刻', value: '#77685A', category: '绘艺', note: '绘艺 · 细点明暗', motif: '<circle cx="6" cy="7" r="1"/><circle cx="17" cy="11" r="1"/><circle cx="29" cy="5" r="1"/><circle cx="42" cy="14" r="1"/><circle cx="10" cy="25" r="1"/><circle cx="24" cy="22" r="1"/><circle cx="37" cy="29" r="1"/><circle cx="5" cy="41" r="1"/><circle cx="20" cy="37" r="1"/><circle cx="45" cy="43" r="1"/>' },
  { texture: 'stained-glass', name: '彩窗碎影', value: '#536F79', category: '绘艺', note: '绘艺 · 彩窗分格', motif: '<path d="M0 0L17 9 8 27 25 48M17 9L37 3 48 21M8 27L31 25 37 3M31 25L48 39M31 25L25 48"/>' },
  { texture: 'pressed-flower', name: '压花书页', value: '#687859', category: '绘艺', note: '绘艺 · 植物标本', motif: '<path d="M24 48V5M24 15C13 9 8 16 20 22M24 27C36 19 42 28 27 34"/><path d="M24 8c-4-6 4-9 0 0Z"/>' },
].map(preset => ({ ...preset, mode: 'texture' }))

export const textureCategories = [...new Set(texturePresets.map(p => p.category))]
export const validTexture = id => texturePresets.some(p => p.texture === id)
export function textureImage(id, opacity = 0.14) {
  const preset = texturePresets.find(p => p.texture === id) || texturePresets[0]
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48"><g fill="none" stroke="black" stroke-width="1" stroke-opacity="${opacity}">${preset.motif}</g></svg>`
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`
}
