<template>
  <div class="settings">
    <!-- Theme Color -->
    <div class="card">
      <div class="theme-card-heading">
        <div>
          <div class="card-header">
            <span class="card-title"><Palette :size="18" /> 主题色</span>
          </div>
          <p class="card-desc">{{ themeColors.length }} 种精选配色：纯色、撞色、渐变、玻璃与纹理，也可以调出自己的专属组合。</p>
        </div>
      </div>
      <div class="theme-switchers">
        <div class="theme-group-tabs" role="tablist" aria-label="配色风格">
          <button v-for="group in themeGroups" :key="group.id" type="button"
                  :id="`theme-tab-${group.id}`" role="tab" :aria-selected="activeThemeGroup === group.id"
                  :tabindex="activeThemeGroup === group.id ? 0 : -1" aria-controls="theme-color-panel"
                  :class="['theme-group-tab', { active: activeThemeGroup === group.id }]"
                  @click="activeThemeGroup = group.id" @keydown="switchThemeGroup($event)">
            {{ group.name }} <span>{{ group.colors.length }}</span>
          </button>
        </div>
        <fieldset class="appearance-setting" aria-label="全局外观">
          <div class="appearance-options">
            <button v-for="option in appearanceOptions" :key="option.value" type="button"
                    :class="['appearance-option', { active: appearance === option.value }]"
                    :aria-pressed="appearance === option.value" @click="selectAppearance(option.value)">
              <Sun v-if="option.value === 'light'" :size="16" />
              <Moon v-else-if="option.value === 'dark'" :size="16" />
              <Monitor v-else :size="16" />
              {{ option.label }}
            </button>
          </div>
        </fieldset>
      </div>
      <div v-if="activeThemeGroup === 'solid'" class="texture-categories solid-categories" aria-label="纯色灵感分类">
        <button v-for="category in solidCategories" :key="category" type="button" :aria-pressed="solidCategory === category" @click="solidCategory = category">{{ category }}</button>
      </div>
      <div v-if="activeThemeGroup === 'texture'" class="texture-categories" aria-label="纹理灵感分类">
        <button v-for="category in ['全部', ...textureCategories]" :key="category" type="button" :aria-pressed="textureCategory === category" @click="textureCategory = category">{{ category }}</button>
      </div>
      <div v-if="activeThemeGroup === 'glass'" class="glass-finishes texture-categories" aria-label="玻璃质感">
        <button v-for="finish in glassFinishes" :key="finish.value" type="button" :aria-pressed="glassFinish === finish.value" @click="selectGlassFinish(finish.value)">{{ finish.label }}</button>
      </div>
      <label v-if="activeThemeGroup === 'glass'" class="glass-glow-control">
        <span>边缘泛光强度</span>
        <input type="range" min="0" max="100" step="1" :value="glassGlow" aria-label="边缘泛光强度" @input="selectGlassGlow(Number($event.target.value))" />
        <output>{{ glassGlow }}%</output>
        <small>0% 保留轻微亮边，100% 约等于原 50%。</small>
      </label>
      <div id="theme-color-panel" class="theme-colors" role="tabpanel" :aria-labelledby="`theme-tab-${activeThemeGroup}`">
        <button v-for="color in visibleThemeColors" :key="color.value + (color.accent || '') + (color.texture || '')" type="button"
             :class="['theme-color-item', { active: isSelected(color) }]"
             :aria-pressed="isSelected(color)"
             @click="selectTheme(color)">
          <span class="color-preview" :style="swatchStyle(activeThemeGroup === 'glass' ? { ...color, finish: glassFinish, glow: glassGlow } : color)">
            <Check v-if="isSelected(color)" class="color-check" :size="14" />
          </span>
          <span class="color-name">{{ color.name }}</span>
          <span class="color-note">{{ color.note }}</span>
        </button>
        <button type="button" :class="['theme-color-item', { active: isCustomSelected }]"
             :aria-pressed="isCustomSelected"
             :aria-expanded="isCustomizableGroup ? customPairOpen : undefined"
             @click="isCustomizableGroup ? openCustomPair() : $refs.customColor.click()">
          <span class="color-preview custom-preview"><span class="custom-preview-center"><Palette :size="20" /></span></span>
          <span class="color-name">{{ activeThemeGroup === 'texture' ? '自定义纹理' : activeThemeGroup === 'glass' ? '自定义玻璃' : activeThemeGroup === 'gradient' ? '自定义渐变' : isPairGroup ? '自定义拼色' : '自定义' }}</span>
          <span class="color-note">{{ activeThemeGroup === 'texture' ? '主色 × 材质纹样' : activeThemeGroup === 'glass' ? '选择玻璃颜色' : activeThemeGroup === 'gradient' ? '起色 → 终色' : isPairGroup ? '主色 × 搭配色' : '打开色盘' }}</span>
        </button>
        <input ref="customColor" type="color" :value="tempTheme.value" aria-label="自定义主题色"
               @input="selectTheme({ value: $event.target.value })" class="custom-color-input" tabindex="-1" />
      </div>
      <div v-if="isPairGroup && customPairOpen" class="custom-pair-editor">
        <label class="pair-color-field">{{ activeThemeGroup === 'gradient' ? '起始色' : '主色' }}
          <input type="color" :aria-label="activeThemeGroup === 'gradient' ? '渐变起始色' : '拼色主色'" :value="tempTheme.value" @input="updatePair('value', $event)" />
          <span>{{ tempTheme.value }}</span>
        </label>
        <button type="button" class="btn btn-ghost btn-sm" @click="swapPair">交换两色</button>
        <label class="pair-color-field">{{ activeThemeGroup === 'gradient' ? '结束色' : '搭配色' }}
          <input type="color" :aria-label="activeThemeGroup === 'gradient' ? '渐变结束色' : '拼色搭配色'" :value="tempTheme.accent" @input="updatePair('accent', $event)" />
          <span>{{ tempTheme.accent }}</span>
        </label>
      </div>
      <div v-if="activeThemeGroup === 'texture' && customPairOpen" class="custom-pair-editor">
        <label class="pair-color-field">主色
          <input type="color" aria-label="纹理主色" :value="tempTheme.value" @input="updatePair('value', $event)" />
          <span>{{ tempTheme.value }}</span>
        </label>
        <label class="pair-color-field">纹样
          <SearchSelect
            :model-value="tempTheme.texture"
            aria-label="纹理样式"
            placeholder="选择纹样"
            :options="textureOptions"
            @change="value => tempTheme = { ...tempTheme, texture: value }"
          />
        </label>
      </div>
      <div v-if="activeThemeGroup === 'glass' && customPairOpen" class="custom-pair-editor">
        <label class="pair-color-field">玻璃颜色
          <input type="color" aria-label="自定义玻璃颜色" :value="tempTheme.value" @input="updatePair('value', $event)" />
          <span>{{ tempTheme.value }}</span>
        </label>
      </div>
      <div class="theme-demo" :style="previewVariables" aria-live="polite">
        <div class="theme-demo-info">
          <span class="theme-demo-swatch" :style="swatchStyle(tempTheme)"></span>
        <div><strong>{{ selectedColor?.name || (tempTheme.mode === 'texture' ? '自定义纹理' : tempTheme.mode === 'glass' ? '自定义玻璃' : tempTheme.mode === 'gradient' ? '自定义渐变' : tempTheme.accent ? '自定义拼色' : '自定义颜色') }}</strong><span class="theme-demo-caption">应用效果预览</span></div>
        </div>
        <div class="theme-demo-controls">
          <span class="theme-demo-tag">{{ tempTheme.accent ? '搭配色标签' : '已选中' }}</span>
          <span class="theme-demo-link">主题文字</span>
          <span class="theme-demo-button">主要按钮 <Check :size="14" /></span>
        </div>
      </div>
      <p class="theme-preview-note">{{ tempTheme.mode === 'glass' ? (tempTheme.finish === 'frosted' ? '磨砂玻璃以乳白雾面、细颗粒和柔和漫反射弱化背景细节。' : '液态玻璃保留清晰背景，以锐利亮边和折射高光勾勒轮廓。') : '纹理轻覆于主色按钮。' }} 主题色会从鼠标位置映射到玻璃表面，文字随明暗外观自动调整。</p>
      <div class="theme-actions">
        <span class="theme-hint" role="status">{{ themeSaveError || '已为你的账号自动保存，下次在此浏览器登录时继续使用。' }}</span>
        <button v-if="themeSaveError" class="btn btn-ghost btn-sm" @click="persistTheme">重试保存</button>
      </div>
    </div>

  </div>
</template>
<script setup>
import { Palette, Check, Sun, Moon, Monitor } from "lucide-vue-next"
import { ref, computed, watch } from "vue"
import { themeGroups, themeColors, solidCategories, readTheme, saveTheme, themeVariables, swatchStyle, normalizeTheme } from "../utils/theme"
import { texturePresets, textureCategories } from "../utils/textures"
import { glassFinishes } from "../utils/glass"
import { appearanceOptions, readAppearance, saveAppearance } from "../utils/appearance"
const tempTheme = ref(normalizeTheme(readTheme()))
const appearance = ref(readAppearance())
const selectAppearance = value => {
  appearance.value = value
  try {
    saveAppearance(value)
    themeSaveError.value = ''
  } catch {
    themeSaveError.value = '外观设置未能保存，请允许浏览器存储后重试。'
  }
}
const customPairOpen = ref(false)
const themeSaveError = ref('')
const activeThemeGroup = ref(['texture', 'glass', 'gradient'].includes(tempTheme.value.mode) ? tempTheme.value.mode : tempTheme.value.accent ? 'contrast' : 'solid')
const solidCategory = ref(themeGroups[0].colors.find(color => color.value === tempTheme.value.value)?.category || '经典')
const isPairGroup = computed(() => ['contrast', 'gradient'].includes(activeThemeGroup.value))
const isCustomizableGroup = computed(() => isPairGroup.value || ['texture', 'glass'].includes(activeThemeGroup.value))
const textureCategory = ref('全部')
const glassFinish = ref(tempTheme.value.finish === 'frosted' ? 'frosted' : 'clear')
const glassGlow = ref(tempTheme.value.glow ?? 20)
const selectGlassGlow = glow => {
  glassGlow.value = glow
  tempTheme.value = normalizeTheme({ value: tempTheme.value.value, mode: 'glass', finish: glassFinish.value, glow })
}
watch(activeThemeGroup, () => { customPairOpen.value = false })
const visibleThemeColors = computed(() => themeGroups.find(group => group.id === activeThemeGroup.value).colors.filter(color => activeThemeGroup.value === 'solid' ? color.category === solidCategory.value : activeThemeGroup.value !== 'texture' || textureCategory.value === '全部' || color.category === textureCategory.value))
const textureOptions = computed(() => texturePresets.map(texture => ({ value: texture.texture, label: texture.category + ' · ' + texture.name })))
const switchThemeGroup = (event) => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const index = themeGroups.findIndex(group => group.id === activeThemeGroup.value)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? themeGroups.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + themeGroups.length) % themeGroups.length
  activeThemeGroup.value = themeGroups[next].id
  document.getElementById(`theme-tab-${activeThemeGroup.value}`)?.focus()
}
const isSelected = color => color.value === tempTheme.value.value && (color.accent || '') === (tempTheme.value.accent || '') && (color.mode || '') === (tempTheme.value.mode || '') && (color.texture || '') === (tempTheme.value.texture || '')
const selectedColor = computed(() => themeColors.find(isSelected))
const isCustomSelected = computed(() => !selectedColor.value && (['texture', 'glass'].includes(activeThemeGroup.value) ? tempTheme.value.mode === activeThemeGroup.value : isPairGroup.value ? !!tempTheme.value.accent && (tempTheme.value.mode || 'contrast') === activeThemeGroup.value : !tempTheme.value.accent && !tempTheme.value.mode))
const selectTheme = color => { customPairOpen.value = false; tempTheme.value = normalizeTheme(color.mode === 'glass' ? { ...color, finish: glassFinish.value, ...(glassGlow.value !== 20 ? { glow: glassGlow.value } : {}) } : color) }
const selectGlassFinish = finish => {
  glassFinish.value = finish
  if (tempTheme.value.mode === 'glass') tempTheme.value = normalizeTheme({ ...tempTheme.value, finish })
}
const openCustomPair = () => {
  customPairOpen.value = !customPairOpen.value
  if (customPairOpen.value) tempTheme.value = normalizeTheme(activeThemeGroup.value === 'texture'
    ? { value: tempTheme.value.value, mode: 'texture', texture: tempTheme.value.texture || 'wood' }
    : activeThemeGroup.value === 'glass'
      ? { value: tempTheme.value.value, mode: 'glass', finish: glassFinish.value, ...(glassGlow.value !== 20 ? { glow: glassGlow.value } : {}) }
      : { value: tempTheme.value.value, accent: tempTheme.value.accent || '#F97316', mode: activeThemeGroup.value === 'gradient' ? 'gradient' : undefined })
}
const updatePair = (key, event) => { tempTheme.value = { ...tempTheme.value, [key]: event.target.value.toUpperCase() } }
const swapPair = () => { tempTheme.value = { ...tempTheme.value, value: tempTheme.value.accent, accent: tempTheme.value.value } }
const previewVariables = computed(() => themeVariables(tempTheme.value))

const persistTheme = () => {
  try {
    saveTheme(tempTheme.value)
    saveAppearance(appearance.value)
    themeSaveError.value = ''
  } catch {
    themeSaveError.value = '主题色未能保存，请允许浏览器存储后重试。'
  }
}
watch(tempTheme, persistTheme)

</script>
<style scoped>
.settings { padding: 0; max-width: 900px; }
.settings h1 { font-size: 24px; font-weight: 700; margin: 0; }
.subtitle { color: var(--text3); margin: 4px 0 24px; font-size: 14px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card-title { font-size: 16px; font-weight: 600; }
.card-desc { font-size: 13px; color: var(--text3); margin: 0 0 16px; }
.theme-card-heading { display: flex; align-items: flex-start; gap: 24px; }
.theme-card-heading > div { min-width: 0; }
.theme-switchers { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.appearance-setting { flex: 0 0 auto; border: 0; margin: 0; padding: 0; }
.appearance-options { display: flex; gap: 4px; padding: 4px; border-radius: 10px; background: var(--surface2); }
.appearance-option { display: inline-flex; align-items: center; gap: 6px; min-height: 34px; padding: 6px 10px; border: 0; border-radius: 7px; background: transparent; color: var(--text2); cursor: pointer; font-size: 12px; }
.appearance-option:hover { color: var(--text); }
.appearance-option.active { color: var(--primary); background: var(--surface); box-shadow: var(--shadow); font-weight: 600; }
.appearance-option:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.theme-group-tabs { display: inline-flex; flex-wrap: wrap; gap: 4px; padding: 4px; border-radius: 10px; background: var(--surface2); }
.theme-group-tab { display: flex; align-items: center; gap: 8px; padding: 7px 16px; border: 0; border-radius: 7px; font: inherit; font-size: 13px; color: var(--text2); background: transparent; cursor: pointer; }
.theme-group-tab span { font-size: 11px; opacity: .7; }
.theme-group-tab.active { background: var(--surface); color: var(--primary); font-weight: 600; box-shadow: 0 1px 4px #0000000a; }
.theme-group-tab:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.theme-colors { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; position: relative; }
.theme-color-item {
  display: flex; flex-direction: column; align-items: center; gap: 7px;
  cursor: pointer; padding: 12px 6px; border-radius: 12px; min-width: 0;
  border: 1px solid var(--border); background: var(--surface); font: inherit;
  transition: background .18s, border-color .18s;
}
.theme-color-item:hover { background: var(--surface2); border-color: var(--text3); }
.theme-color-item:focus-visible { outline: 2px solid var(--primary); outline-offset: 3px; }
.theme-color-item.active { border-color: var(--primary); background: var(--primary-light); }
.color-preview { position: relative; display: flex; align-items: center; justify-content: center; width: 44px; height: 44px; border-radius: 50%; border: 1px solid #0000000a; box-shadow: 0 2px 4px #00000008; }
.color-check { position: absolute; right: -4px; bottom: -4px; padding: 3px; box-sizing: content-box; border-radius: 50%; background: var(--primary); color: white; border: 2px solid var(--surface); }
.color-name { font-size: 12px; font-weight: 600; color: var(--text); }
.color-note { font-size: 10px; color: var(--text2); }
.custom-preview { background: conic-gradient(#D79BA8, #D9B888, #BCD09D, #90C4BC, #92B1D5, #B4A0CD, #D79BA8); }
.custom-preview-center { display: flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 50%; background: var(--surface); color: var(--text2); }
.custom-color-input { position: absolute; bottom: 0; right: 0; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.custom-pair-editor { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; padding: 16px; margin-top: 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface2); }
.pair-color-field { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text2); }
.pair-color-field input { width: 42px; height: 34px; padding: 2px; border: 1px solid var(--border); border-radius: 6px; cursor: pointer; background: var(--surface); }
.pair-color-field span { font-size: 11px; font-variant-numeric: tabular-nums; }
.theme-demo { margin-top: 20px; padding: 16px; border: 1px solid var(--border); border-radius: 12px; display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; }
.theme-demo-info, .theme-demo-controls { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.theme-demo-swatch { width: 42px; height: 42px; border: 1px solid #00000012; border-radius: 12px; }
.theme-demo-info strong { font-size: 13px; }
.theme-demo-caption { display: block; font-size: 11px; color: var(--text2); margin-top: 4px; }
.theme-demo-tag { background: var(--theme-tag-background, var(--accent-light)); color: var(--navigation-color, var(--accent)); padding: 5px 9px; border-radius: 6px; font-size: 12px; }
.theme-demo-link { color: var(--primary); font-size: 12px; }
.theme-demo-button { display: inline-flex; align-items: center; gap: 8px; background: var(--primary); color: var(--primary-text, white); border-radius: 8px; padding: 9px 12px; font-size: 12px; }
.theme-preview-note { margin: 10px 0 0; font-size: 11px; color: var(--text2); }
@media (max-width: 600px) { .settings { padding: 0; } .theme-colors { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; } .theme-actions { flex-wrap: wrap; } }

.texture-categories { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.glass-glow-control { display:flex; align-items:center; flex-wrap:wrap; gap:12px; margin:0 0 18px; color:var(--text2); font-size:12px; }
.glass-glow-control input { width:200px; max-width:100%; accent-color:var(--primary); cursor:pointer; }
.glass-glow-control output { min-width:36px; font-variant-numeric:tabular-nums; }
.glass-glow-control small { color:var(--text3); }
.texture-categories button { border:1px solid var(--border); border-radius:20px; padding:5px 12px; background:var(--surface); color:var(--text2); cursor:pointer; font:inherit; font-size:12px; }
.texture-categories button[aria-pressed="true"] { background:var(--primary-light); border-color:var(--primary); color:var(--text); }
.texture-categories button:focus-visible { outline:2px solid var(--primary); outline-offset:2px; }
.pair-color-field select { max-width:100%; padding:8px; background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:6px; }
.theme-demo-button:hover { background-color:var(--theme-button-hover-background, var(--primary-hover)); background-image:var(--theme-gradient-hover); }
.theme-actions { display:flex; gap:12px; margin-top:12px; align-items:center; }
.theme-hint { color:var(--text3); font-size:12px; }
.theme-demo-button { background-color:var(--theme-button-background, var(--primary)); background-image:var(--theme-gradient); border:1px solid var(--theme-button-border, transparent); box-shadow:var(--theme-button-shadow, none); backdrop-filter:var(--theme-backdrop, none); }
</style>
