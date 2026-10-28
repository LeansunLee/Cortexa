<template>
  <div ref="root" class="ref-picker">
    <div v-if="projects.length || works.length" class="ref-chips">
      <span v-for="p in projects" :key="p.id" class="ref-chip">
        <FileText :size="12" aria-hidden="true" />
        <span class="ref-chip-title">{{ p.title }}</span>
        <button type="button" :disabled="disabled" :aria-label="`移除项目${p.title}`" @click="setProjects(projects.filter(x => x.id !== p.id))"><X :size="12" /></button>
      </span>
      <span v-for="w in works" :key="w.id" class="ref-chip">
        <ClipboardList :size="12" aria-hidden="true" />
        <span class="ref-chip-title">{{ w.title }}</span>
        <button type="button" :disabled="disabled" :aria-label="`移除工作${w.title}`" @click="setWorks(works.filter(x => x.id !== w.id))"><X :size="12" /></button>
      </span>
    </div>
    <div v-if="open || query !== null" class="ref-menu" role="dialog" aria-label="添加附件与引用">
      <div class="ref-menu-head">
        <strong>添加</strong>
        <button type="button" class="ref-menu-close" aria-label="关闭添加面板" @click="close"><X :size="14" /></button>
      </div>
      <button v-if="!inlineQuery && !error" type="button" class="add-row" @click="upload">
        <span class="add-ico"><Paperclip :size="15" aria-hidden="true" /></span>
        <span class="add-label">附件</span>
        <span class="add-desc">上传图片或文档，随消息一并发送</span>
      </button>
      <p v-if="error" class="ref-menu-error" role="alert">{{ error }} <button type="button" class="btn btn-ghost btn-sm" @click="load">重试</button></p>
      <template v-else>
        <div class="ref-search">
          <Search :size="14" aria-hidden="true" />
          <input ref="searchInput" v-model="keyword" placeholder="搜索项目和工作" aria-label="搜索可引用的项目和工作" @keydown.escape.prevent="close" />
        </div>
        <div class="ref-scroll">
          <p class="add-section">项目 <span class="add-section-count" :class="{ full: projects.length >= 3 }">{{ projects.length }}/3</span></p>
          <ul class="ref-list">
            <li v-if="loadingProjects" class="ref-empty">正在加载项目…</li>
            <li v-else-if="!projectOptions.length" class="ref-empty">{{ keyword || query ? '没有匹配的项目' : '暂无可引用的项目' }}</li>
            <li v-else v-for="p in projectOptions" :key="p.id">
              <button type="button" class="add-row" :class="{ on: pickedProject(p) }" @click="toggleProject(p)">
                <span class="add-ico"><FileText :size="15" aria-hidden="true" /></span>
                <span class="add-label">{{ p.title }}</span>
                <span class="add-desc">{{ p.owner_name }}</span>
                <Check :size="14" v-if="pickedProject(p)" class="add-check" aria-hidden="true" />
              </button>
            </li>
          </ul>
          <p v-if="!inlineQuery" class="add-section">工作 <span class="add-section-count" :class="{ full: works.length >= 5 }">{{ works.length }}/5</span></p>
          <ul v-if="!inlineQuery" class="ref-list">
            <li v-if="loadingWorks" class="ref-empty">正在加载工作…</li>
            <li v-else-if="!workOptions.length" class="ref-empty">{{ keyword ? '没有匹配的工作' : '暂无可引用的工作' }}</li>
            <li v-else v-for="w in workOptions" :key="w.id">
              <button type="button" class="add-row" :class="{ on: pickedWork(w) }" @click="toggleWork(w)">
                <span class="add-ico add-ico-work"><ClipboardList :size="15" aria-hidden="true" /></span>
                <span class="add-label">{{ w.title }}</span>
                <span class="add-desc">{{ workMeta(w) }}</span>
                <Check :size="14" v-if="pickedWork(w)" class="add-check" aria-hidden="true" />
              </button>
            </li>
          </ul>
        </div>
      </template>
      <div class="ref-menu-foot">
        <span>点击条目加入或移除引用</span>
        <button type="button" class="btn btn-primary btn-sm" @click="close">完成</button>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { Search, X, Paperclip, FileText, ClipboardList, Check } from 'lucide-vue-next'
import api from '../api'
import { workApi } from '../api'
const props = defineProps({
  projects: { type: Array, default: () => [] },
  works: { type: Array, default: () => [] },
  query: { default: null },
  disabled: Boolean,
  initialProject: String,
})
const emit = defineEmits(['update-projects', 'update-works', 'close', 'upload'])
const root = ref(null), searchInput = ref(null)
const open = ref(false), keyword = ref('')
const projectItems = ref([]), workItems = ref([])
const loadingProjects = ref(false), loadingWorks = ref(false)
const error = ref('')
let generation = 0, initialApplied = false
const inlineQuery = computed(() => props.query !== null)
const statusLabels = { draft: '草稿', pending: '待处理', todo: '待开始', in_progress: '进行中', review: '待验收', completed: '已完成', rejected: '退回修改', cancelled: '已取消' }
const keywordLower = computed(() => keyword.value.trim().toLowerCase())
// Picked items stay in the list with a check mark — clicking toggles them off.
// Cancelled works and archived projects are not referencable — hide them.
const projectOptions = computed(() => projectItems.value
  .filter(p => p.status !== 'archived' && (!props.query || p.title.toLowerCase().includes(props.query.toLowerCase())) && (!keywordLower.value || p.title.toLowerCase().includes(keywordLower.value))))
const workOptions = computed(() => workItems.value
  .filter(w => w.status !== 'cancelled' && (!keywordLower.value || w.title.toLowerCase().includes(keywordLower.value))))
const fmtDue = iso => {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? '' : `${d.getMonth() + 1}/${d.getDate()}`
}
const workMeta = w => [w.assignee_name, w.due_at ? '截止 ' + fmtDue(w.due_at) : '', statusLabels[w.status] || w.status].filter(Boolean).join(' · ')
async function load() {
  error.value = ''
  const ticket = ++generation
  loadingProjects.value = loadingWorks.value = true
  const [proj, work] = await Promise.allSettled([
    api.get('/projects', { params: { search: keyword.value || props.query || '' } }),
    inlineQuery.value ? Promise.resolve({ data: [] }) : workApi.list({ view: 'all', search: keyword.value || undefined, limit: 200 }),
  ])
  if (ticket !== generation) return
  if (proj.status === 'fulfilled') projectItems.value = proj.value.data || []
  else error.value = '项目列表加载失败'
  if (work.status === 'fulfilled') workItems.value = work.value.data || []
  else if (!error.value) error.value = '工作列表加载失败'
  loadingProjects.value = loadingWorks.value = false
  if (props.initialProject && !initialApplied && !props.projects.length && projectItems.value.length) {
    initialApplied = true
    const p = projectItems.value.find(p => p.id === props.initialProject)
    if (p) setProjects([{ id: p.id, title: p.title }])
    else if (!keyword.value) {
      try { const { data } = await api.get(`/projects/${props.initialProject}`); setProjects([{ id: data.id, title: data.title }]) }
      catch { error.value = '所选项目不可访问' }
    }
  }
}
function setProjects(list) { emit('update-projects', list) }
function setWorks(list) { emit('update-works', list) }
const pickedProject = p => props.projects.some(r => r.id === p.id)
const pickedWork = w => props.works.some(r => r.id === w.id)
function toggleProject(p) {
  if (props.disabled) return
  if (pickedProject(p)) { setProjects(props.projects.filter(x => x.id !== p.id)); return }
  if (props.projects.length >= 3) return
  setProjects([...props.projects, { id: p.id, title: p.title }])
  // Inline "#mention" flow (typed in the input): one pick completes the action.
  if (inlineQuery.value) close()
}
function toggleWork(w) {
  if (props.disabled || pickedWork(w)) { if (pickedWork(w)) setWorks(props.works.filter(x => x.id !== w.id)); return }
  if (props.works.length >= 5) return
  setWorks([...props.works, { id: w.id, title: w.title }])
}
function close() { open.value = false; emit('close') }
let uploadAt = 0
// The native file dialog can synthesize a stray document click when it
// closes — never let that close the menu right after choosing 附件.
function upload() { uploadAt = Date.now(); emit('upload') }
function onDocClick(event) {
  if (Date.now() - uploadAt < 800) return
  if ((open.value || inlineQuery.value) && root.value && !root.value.contains(event.target)) close()
}
watch(keyword, load)
watch(() => props.query, () => { if (props.query !== null) load() })
function arm() {
  nextTick(() => searchInput.value?.focus())
  setTimeout(() => document.addEventListener('click', onDocClick))
}
function disarm() { document.removeEventListener('click', onDocClick) }
watch(open, value => { if (value) { load(); arm() } else disarm() })
watch(inlineQuery, value => { if (value) { load(); arm() } else disarm() })
defineExpose({ openMenu: () => { if (!props.disabled) open.value = !open.value } })
onMounted(load)
onBeforeUnmount(disarm)
</script>
<style scoped>
.ref-picker { font-size: 12px; }
.ref-chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 6px 10px 0; }
.ref-chip { display: inline-flex; align-items: center; gap: 5px; max-width: 220px; padding: 3px 6px 3px 9px; border-radius: 999px;
  color: var(--primary); background: var(--primary-light); border: 1px solid color-mix(in srgb, var(--primary) 28%, transparent); }
.ref-chip-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ref-chip button { display: flex; align-items: center; justify-content: center; flex: none; width: 16px; height: 16px; padding: 0;
  border: 0; border-radius: 50%; background: transparent; color: inherit; cursor: pointer; }
.ref-chip button:hover:not(:disabled) { background: color-mix(in srgb, var(--primary) 18%, transparent); }
.ref-chip button:disabled { opacity: .5; cursor: not-allowed; }

.ref-menu { position: relative; z-index: 830; /* above the floating robot (820) */ display: flex; flex-direction: column; gap: 8px; margin: 6px 10px 10px; padding: 12px; border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--primary) 20%, var(--border));
  background: color-mix(in srgb, var(--surface) 90%, transparent);
  backdrop-filter: blur(20px) saturate(140%); -webkit-backdrop-filter: blur(20px) saturate(140%);
  box-shadow: 0 12px 32px rgba(15, 23, 42, .16); }
.ref-menu-head { display: flex; align-items: center; gap: 8px; }
.ref-menu-head strong { font-size: 13px; }
.ref-menu-close { display: flex; align-items: center; justify-content: center; width: 22px; height: 22px; margin-left: auto; padding: 0;
  border: 0; border-radius: 6px; background: transparent; color: var(--text3); cursor: pointer; }
.ref-menu-close:hover { color: var(--text); background: var(--surface2); }
.ref-menu-error { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 12px; color: var(--danger, #E5484D); }

.add-section { display: flex; align-items: center; gap: 6px; margin: 4px 0 2px; font-size: 11px; font-weight: 600; color: var(--text3); }
.add-section-count { font-weight: 500; font-variant-numeric: tabular-nums; color: var(--text3); }
.add-section-count.full { color: var(--danger, #E5484D); }
.add-row { display: flex; align-items: center; gap: 9px; width: 100%; padding: 8px 9px; border: 0; border-radius: 8px;
  background: transparent; color: var(--text); font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.add-row:hover { background: var(--surface2); }
.add-row.on { background: var(--primary-light); }
.add-ico { display: flex; align-items: center; justify-content: center; flex: none; width: 26px; height: 26px; border-radius: 7px;
  background: var(--surface2); color: var(--text2); }
.add-row.on .add-ico { background: color-mix(in srgb, var(--primary) 16%, var(--surface)); color: var(--primary); }
.add-label { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.add-desc { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: var(--text3); }
.add-check { flex: none; margin-left: auto; color: var(--primary); }

.ref-search { position: relative; }
.ref-search svg { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text3); pointer-events: none; }
.ref-search input { width: 100%; box-sizing: border-box; padding: 8px 10px 8px 30px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface2); color: var(--text); font: inherit; font-size: 12px; outline: none; transition: border-color .15s, background .15s; }
.ref-search input:focus { border-color: var(--primary); background: var(--surface); }
.ref-search input::placeholder { color: var(--text3); }

.ref-scroll { max-height: 264px; overflow: auto; display: flex; flex-direction: column; }
.ref-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.ref-empty { padding: 14px 0; text-align: center; font-size: 12px; color: var(--text3); }

.ref-menu-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-top: 8px; border-top: 1px solid var(--border); font-size: 11px; color: var(--text3); }
</style>
