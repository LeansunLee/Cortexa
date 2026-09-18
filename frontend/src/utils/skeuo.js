// Skeuomorphic material themes: realistic surfaces with physical depth,
// rather than the flat motifs used by the texture group.
export const skeuoPresets = [
  { material: 'wood', name: '核桃木', value: '#4E3524', note: '深胡桃棕基底，咖啡褐与焦糖色木纹纵向流动，温润沉稳' },
  { material: 'bamboo', name: '青玉竹', value: '#4D8B68', note: '低饱和青玉绿基底，细腻竹纤维与若隐若现竹节，温润清雅' },
  { material: 'marble', name: '大理石', value: '#E8E2D8', note: '暖象牙白石材基底，烟灰矿物脉络与柔和云纹，克制现代' },
].map(preset => ({ ...preset, mode: 'skeuo' }))

export const skeuoMaterials = [...new Set(skeuoPresets.map(p => p.material))]
export const validSkeuoMaterial = id => skeuoPresets.some(p => p.material === id)

// Public assets follow Vite's deployment base; Node tests use the same base.
const assetBase = import.meta.env?.BASE_URL || '/static/dist/'
const materialFiles = { wood: 'walnut', bamboo: 'bamboo', marble: 'marble' }

export function skeuoImage(value, material = 'wood') {
  const file = materialFiles[material] || materialFiles.wood
  return 'url("' + assetBase + 'themes/skeuo/' + file + '.jpg")'
}

export function skeuoSwatch(value, material = 'wood') {
  return {
    backgroundColor: value,
    backgroundImage: skeuoImage(value, material),
    backgroundSize: '220px 220px',
    backgroundOrigin: 'border-box',
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,.32), inset 0 -2px 3px rgba(0,0,0,.3), 0 3px 7px rgba(15,23,42,.26)',
  }
}
