<template>
  <div
    ref="root"
    class="search-select"
    :class="{ 'search-select-open': open, 'search-select-disabled': disabled }"
  >
    <button
      ref="trigger"
      type="button"
      class="search-select-trigger"
      :disabled="disabled"
      :aria-expanded="open"
      :aria-label="ariaLabel || placeholder"
      aria-haspopup="listbox"
      @click="toggle"
      @keydown="onTriggerKeydown"
    >
      <span class="search-select-value" :class="{ 'search-select-placeholder': !selected }">{{ selected?.label || placeholder }}</span>
      <ChevronDown :size="16" class="search-select-chevron" />
    </button>
    <Teleport to="body">
      <div
        v-if="open"
        ref="menu"
        class="search-select-menu"
        :style="style"
        role="listbox"
        :aria-label="ariaLabel || placeholder"
        @keydown="onMenuKeydown"
      >
        <label class="search-select-search">
          <Search :size="15" />
          <input ref="input" v-model="query" type="search" :placeholder="searchPlaceholder" />
        </label>
        <div class="search-select-options">
          <button
            v-for="item in filtered"
            :key="String(item.value)"
            type="button"
            role="option"
            class="search-select-option"
            :class="{ 'search-select-option-selected': item.value === modelValue }"
            :aria-selected="item.value === modelValue"
            :disabled="item.disabled"
            @click="choose(item)"
          >
            {{ item.label }}
          </button>
          <p v-if="!filtered.length" class="search-select-empty">没有匹配的选项</p>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, inject, nextTick, onBeforeUnmount, ref, unref, watch } from 'vue'
import { ChevronDown, Search } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { default: '' },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '请选择' },
  searchPlaceholder: { type: String, default: '搜索选项' },
  disabled: Boolean,
  ariaLabel: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'change'])
const pageTabActive = inject('pageTabActive', true)

const root = ref(null)
const trigger = ref(null)
const menu = ref(null)
const input = ref(null)
const open = ref(false)
const query = ref('')
const style = ref({})

const values = computed(() => props.options.map(item => {
  if (item && typeof item === 'object') return { disabled: false, ...item, label: String(item.label ?? item.value ?? '') }
  return { value: item, label: String(item), disabled: false }
}))
const selected = computed(() => values.value.find(item => item.value === props.modelValue))
const filtered = computed(() => {
  const term = query.value.trim().toLowerCase()
  return term ? values.value.filter(item => String(item.label).toLowerCase().includes(term)) : values.value
})

function place() {
  const rect = trigger.value?.getBoundingClientRect()
  if (!rect) return
  const viewportGap = 12
  const availableBelow = window.innerHeight - rect.bottom - viewportGap
  const maxHeight = Math.min(320, Math.max(150, availableBelow))
  const openBelow = availableBelow > 220 || rect.top < availableBelow
  const width = Math.max(rect.width, 200)
  style.value = {
    left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)) + 'px',
    top: (openBelow ? rect.bottom + 6 : Math.max(8, rect.top - maxHeight - 6)) + 'px',
    width: width + 'px',
    maxHeight: maxHeight + 'px',
  }
}
async function show() {
  if (props.disabled) return
  open.value = true
  query.value = ''
  await nextTick()
  place()
  input.value?.focus()
}
function hide() { open.value = false }
function toggle() { open.value ? hide() : show() }
function choose(item) {
  if (item.disabled) return
  emit('update:modelValue', item.value)
  emit('change', item.value)
  hide()
  nextTick(() => trigger.value?.focus())
}
function focusOption(offset = 1) {
  const options = Array.from(menu.value?.querySelectorAll('.search-select-option:not(:disabled)') || [])
  if (!options.length) return
  const active = document.activeElement
  const current = options.indexOf(active)
  options[(current + offset + options.length) % options.length].focus()
}
function onTriggerKeydown(event) {
  if (['Enter', ' ', 'ArrowDown'].includes(event.key)) {
    event.preventDefault()
    show().then(() => focusOption(1))
  }
}
function onMenuKeydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); hide(); nextTick(() => trigger.value?.focus()) }
  if (event.key === 'ArrowDown') { event.preventDefault(); focusOption(1) }
  if (event.key === 'ArrowUp') { event.preventDefault(); focusOption(-1) }
}
function outside(event) {
  if (!root.value?.contains(event.target) && !menu.value?.contains(event.target)) hide()
}
function reposition() { if (open.value) place() }

document.addEventListener('pointerdown', outside)
window.addEventListener('resize', reposition)
window.addEventListener('scroll', reposition, true)
watch(() => props.disabled, value => { if (value) hide() })
watch(() => unref(pageTabActive), value => { if (!value) hide() })
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('resize', reposition)
  window.removeEventListener('scroll', reposition, true)
})
</script>

<style>
@import "../../../src/agentdevstu/web/static/css/glass-select.css";
.search-select { position: relative; min-width: 0; }
.search-select-trigger { width: 100%; min-height: 38px; display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 10px 8px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); color: var(--text); font: inherit; text-align: left; cursor: pointer; box-shadow: 0 1px 2px color-mix(in srgb, var(--text) 6%, transparent); transition: border-color .16s ease, box-shadow .16s ease, background-color .16s ease, transform .16s ease; }
.search-select-value { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.search-select-placeholder { color: var(--text3); }
.search-select-chevron { color: var(--text3); flex: none; transition: transform .16s ease; }
.search-select-trigger:hover:not(:disabled), .search-select-open .search-select-trigger { border-color: color-mix(in srgb, var(--primary) 55%, var(--border)); background: var(--surface2); }
.search-select-open .search-select-trigger { box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 18%, transparent); }
.search-select-open .search-select-chevron { transform: rotate(180deg); }
.search-select-disabled { opacity: .5; }
.search-select-menu { position: fixed; z-index: 5000; display: flex; flex-direction: column; overflow: hidden; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); color: var(--text); box-shadow: 0 16px 38px color-mix(in srgb, var(--text) 18%, transparent); backdrop-filter: var(--theme-backdrop, none); -webkit-backdrop-filter: var(--theme-backdrop, none); }
.search-select-search { display: flex; align-items: center; gap: 8px; margin: 8px; padding: 0 9px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface2); color: var(--text3); }
.search-select-search input { width: 100%; min-width: 0; padding: 7px 0; border: 0 !important; outline: 0; background: transparent !important; color: var(--text); font: inherit; font-size: 13px; }
.search-select-menu .search-select-search input:focus,
.search-select-menu .search-select-search input:focus-visible { outline: none !important; box-shadow: none !important; border-color: transparent !important; }
.search-select-options { overflow: auto; padding: 4px 6px 6px; }
.search-select-option { display: block; width: 100%; padding: 9px 10px; border: 0; border-radius: 7px; background: transparent; color: var(--text); font: inherit; font-size: 13px; text-align: left; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.search-select-option:hover:not(:disabled), .search-select-option:focus-visible, .search-select-option-selected { background: var(--primary-light); color: var(--navigation-color); outline: none; }
.search-select-option-selected { font-weight: 600; }
.search-select-option:disabled { opacity: .45; cursor: not-allowed; }
.search-select-empty { margin: 0; padding: 18px 10px; color: var(--text3); font-size: 13px; text-align: center; }
:root[data-color-theme=texture] .search-select-trigger, :root[data-color-theme=texture] .search-select-menu { background-color: var(--surface); background-image: var(--theme-gradient); background-repeat: repeat; background-size: 180px 180px; border-color: color-mix(in srgb, var(--primary) 22%, var(--border)); }
:root[data-color-theme=texture] .search-select-search { background: color-mix(in srgb, var(--surface2) 86%, transparent); }
:root[data-color-theme=skeuo] .search-select-trigger, :root[data-color-theme=skeuo] .search-select-menu { background-color: light-dark(#F6EDDE, #402F20); border-color: light-dark(#D8C6AC, #241A10); box-shadow: inset 0 2px 4px var(--skeuo-shadow, rgba(61,42,24,.26)), inset 0 -1px 0 var(--skeuo-highlight, rgba(255,255,255,.5)); }
:root[data-color-theme=skeuo] .search-select-menu { box-shadow: inset 0 1px 0 var(--skeuo-highlight, rgba(255,255,255,.4)), 0 8px 20px var(--skeuo-shadow, rgba(61,42,24,.26)); }

:root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-trigger { background: var(--surface2); color: var(--text); border-color: color-mix(in srgb, var(--border) 82%, #ffffff 18%); box-shadow: 0 1px 2px rgba(0,0,0,.28); }
:root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-trigger:hover:not(:disabled), :root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-open .search-select-trigger { background: color-mix(in srgb, var(--surface2) 88%, #ffffff 12%); border-color: color-mix(in srgb, var(--primary) 48%, var(--border)); box-shadow: 0 6px 18px rgba(0,0,0,.24); }
:root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-open .search-select-trigger { box-shadow: 0 0 0 1px color-mix(in srgb, var(--primary) 46%, transparent), 0 10px 26px rgba(0,0,0,.32); }
:root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-menu { background: color-mix(in srgb, var(--surface) 94%, #ffffff 6%); color: var(--text); border-color: color-mix(in srgb, var(--border) 82%, #ffffff 18%); box-shadow: 0 22px 54px rgba(0,0,0,.42); }
:root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-search { background: color-mix(in srgb, var(--surface2) 90%, #ffffff 10%); color: var(--text2); border-color: color-mix(in srgb, var(--border) 86%, #ffffff 14%); box-shadow: inset 0 1px 0 rgba(255,255,255,.04); }
:root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-placeholder, :root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-chevron, :root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-empty { color: var(--text3); }
:root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-option { color: var(--text); }
:root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-option:hover:not(:disabled), :root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-option:focus-visible, :root[data-theme=dark]:not([data-color-theme=glass]):not([data-color-theme=texture]):not([data-color-theme=skeuo]) .search-select-option-selected { background: color-mix(in srgb, var(--primary) 22%, var(--surface2)); color: var(--text); outline: none; }

@media (max-width: 640px) { .search-select-trigger { min-height: 40px; } .search-select-menu { max-width: calc(100vw - 16px) !important; } }
</style>
