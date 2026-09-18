<template>
  <article class="knowledge-card" :class="{ 'menu-active': moreOpen, expanded }">
    <header class="card-heading">
      <div class="folder-icon"><FolderOpen :size="22" /></div>
      <div class="card-info"><div class="card-title-row"><button class="kb-root-link" type="button" :title="kb.name" @click="navigateToFolder(null)">{{ kb.name }}</button><div v-if="breadcrumbs.length" class="folder-breadcrumbs header-breadcrumbs"><template v-for="crumb in breadcrumbs" :key="crumb.id"><ChevronRight :size="13" /><button type="button" @click="navigateToFolder(crumb.id)">{{ crumb.name }}</button></template></div><button class="copy-path" type="button" :title="`复制：${readablePath}`" aria-label="复制当前知识库可读路径和 API 路径" @click="copyResourcePath"><Copy :size="14" /></button></div><p>{{ loading ? '正在读取文档…' : `${documents.length} 个文档` }}<span v-if="totalSize"> · {{ formatSize(totalSize) }}</span><span v-if="kb.description"> · {{ kb.description }}</span></p></div>
      <span class="kb-status" :class="{ disabled: !enabled }">{{ enabled ? '已启用' : '已禁用' }}</span>
      <slot name="actions" />
      <button class="quiet" :aria-expanded="expanded" @click="expanded = !expanded"><ChevronUp v-if="expanded" :size="16" /><ChevronDown v-else :size="16" />{{ expanded ? '收起' : '展开' }}</button>
      <div v-if="canManage" class="more-wrap" @click.stop><button class="icon" aria-label="更多知识库操作" title="更多" @click="toggleMenu('kb', kb.id)"><MoreHorizontal :size="18" /></button><div v-if="isMenuOpen('kb', kb.id)" class="resource-menu" role="menu"><button @click="openEditor('rename-kb', kb)"><Pencil :size="14" />重命名</button><button @click="toggleStatus(); closeMenu()"><Power :size="14" />{{ enabled ? '禁用知识库' : '启用知识库' }}</button><div class="menu-divider"></div><button class="danger" @click="confirmTarget = { type: 'kb', name: kb.name }; closeMenu()"><Trash2 :size="14" />删除知识库</button></div></div>
    </header>
    <div v-show="expanded" class="card-content">
      <div class="documents-toolbar">
        <label class="search"><Search :size="15" /><input v-model="search" placeholder="搜索整个知识库的文件名称" aria-label="搜索文件名称" /></label>
        <div class="file-type-filters" role="group" aria-label="文件类型筛选"><button v-for="item in fileTypeOptions" :key="item.value" type="button" class="file-type-filter" :class="{ selected: typeFilter === item.value }" :aria-pressed="typeFilter === item.value" @click="typeFilter = typeFilter === item.value ? null : item.value">{{ item.label }}</button></div>
        <button class="quiet refresh-action" :disabled="loading" @click="loadDocs"><RefreshCw :size="14" />刷新</button>
        <div v-if="canUse" class="toolbar-actions">
          <button v-if="canManage" class="btn btn-ghost btn-sm toolbar-action" type="button" @click="openEditor('create-folder')"><FolderPlus :size="15" />新建文件夹</button>
          <button class="btn btn-ghost btn-sm toolbar-action create-text-btn" type="button" @click="createTextDocTarget = true"><FilePlus :size="16" />创建文本文档</button>
          <button class="btn btn-primary btn-sm toolbar-action upload-action" type="button" title="拖拽文件到这里，或点击选择。支持多文件，单个文件不超过 500 MB。PDF、Word、Excel、PowerPoint、图片及文本均可在线预览。" aria-label="上传文件。拖拽文件到这里，或点击选择。支持多文件，单个文件不超过 500 MB。PDF、Word、Excel、PowerPoint、图片及文本均可在线预览。" :disabled="uploading" @click="openUploadPicker"><Plus :size="15" />{{ uploading ? '上传中…' : '上传文件' }}</button>
        </div>
      </div>
      <KnowledgeUpload v-if="canUse" ref="uploadRef" compact :kb-id="kb.id" :folder-id="currentFolderId" @uploaded="loadDocs" @busy="uploading = $event" />
      <div class="resource-divider" aria-hidden="true"></div>
      <div v-if="loadError" class="list-error">{{ loadError }} <button @click="loadDocs">重试</button></div>
      <div v-else-if="loading && !documents.length" class="empty">正在加载文档…</div>
      <div v-else class="resource-layout" :class="{ 'without-explorer': isFiltering, 'explorer-collapsed': !explorerExpanded && !isFiltering }">
        <aside v-if="!isFiltering" class="explorer-pane" :class="{ collapsed: !explorerExpanded }" aria-label="资源管理器">
          <div class="explorer-heading"><button type="button" class="quiet explorer-toggle" :aria-expanded="explorerExpanded" :aria-controls="'folder-tree-' + kb.id" :aria-label="explorerExpanded ? '收起资源管理器' : '展开资源管理器'" :title="explorerExpanded ? '收起资源管理器' : '展开资源管理器'" @click="explorerExpanded = !explorerExpanded"><PanelLeftClose v-if="explorerExpanded" :size="16" /><PanelLeftOpen v-else :size="16" /></button><span v-if="explorerExpanded" class="explorer-title">总文件夹数</span><strong v-if="explorerExpanded" class="tree-count">{{ folders.length }}</strong></div>
          <div v-if="showExplorer" :id="'folder-tree-' + kb.id" class="folder-tree" aria-label="文件夹"><button class="tree-root" :class="{ selected: currentFolderId === null }" @click="selectRoot"><Folder :size="16" class="folder-symbol" />根目录<span>{{ documents.filter(doc => !doc.folder_id).length }}</span></button><div v-for="item in treeFolders" :key="item.folder.id" class="tree-item" :class="{ selected: currentFolderId === item.folder.id }" :style="{ paddingLeft: (12 + item.depth * 16) + 'px' }">
          <button v-if="item.hasChildren" type="button" class="tree-toggle" :aria-label="(expandedFolderIds.has(item.folder.id) ? '收起子文件夹 ' : '展开子文件夹 ') + item.folder.name" :aria-expanded="expandedFolderIds.has(item.folder.id)" @click.stop="toggleFolderExpansion(item.folder.id)"><ChevronRight :class="{ rotated: expandedFolderIds.has(item.folder.id) }" :size="13" /></button><span v-else class="tree-spacer"></span>
          <button type="button" class="tree-folder" :aria-current="currentFolderId === item.folder.id ? 'location' : undefined" @click="selectFolder(item.folder)"><Folder :size="16" class="folder-symbol" /><span class="tree-name">{{ item.folder.name }}</span><span class="tree-file-count">{{ item.count }}</span></button>
        </div></div></aside>
        <div class="document-list" ref="documentListRef">
        <div v-if="isFiltering" class="search-results-heading"><span role="status">整个知识库 · 找到 {{ currentDocuments.length }} 个文件</span><button type="button" class="quiet" @click="returnToBrowsing">返回文件夹浏览</button></div>
        <Transition name="batch-expand">
          <div v-if="expanded && totalSelectedCount" class="batch-toolbar" role="toolbar" aria-label="批量资源操作">
            <label class="batch-select-page"><input type="checkbox" :checked="allVisibleSelected" :indeterminate="someVisibleSelected && !allVisibleSelected" :disabled="uploading || deleting || !visibleResourceCount" @change="selectPage($event.target.checked)" />本页全选</label>
            <strong>已选 {{ totalSelectedCount }} 个<span v-if="hiddenSelectedCount">，其中 {{ hiddenSelectedCount }} 个不在当前页</span></strong>
            <button type="button" :title="selectedIds.length ? '下载所选文件' : '所选内容中没有文件'" :disabled="!selectedIds.length || downloading || deleting" @click="downloadDocuments()">{{ downloading === 'batch' ? '打包中…' : '批量下载' }}</button>
            <button v-if="canUse" type="button" :title="selectedCanEdit ? '移动所选文件和文件夹' : '所选内容中包含无权修改的资源'" :disabled="!selectedCanEdit || deleting" @click="openEditor('move-resources')">批量移动</button>
            <button v-if="canUse" type="button" class="batch-delete" :title="selectedCanEdit ? '删除所选文件和空文件夹' : '所选内容中包含无权删除的资源'" :disabled="!selectedCanEdit || uploading || deleting" @click="confirmBatch">批量删除</button>
            <button type="button" class="batch-close" title="取消选择（Esc）" aria-label="取消选择" @click="clearSelection">×</button>
          </div>
        </Transition>
        <div v-if="!currentDocuments.length && !visibleFolders.length" class="empty empty-list"><Files :size="28" /><p>{{ isFiltering ? '整个知识库中没有匹配的文件' : readonly ? '此目录暂无文档' : '上传第一份文件，让知识库开始积累知识' }}</p></div>
        <div v-for="folder in visibleFolders" :key="folder.id" class="folder-row"><input v-if="canManage" type="checkbox" :aria-label="`选择文件夹 ${folder.name}`" :checked="selectedFolderIds.includes(folder.id)" :disabled="uploading || deleting" @change="selectFolderResource(folder.id, $event.target.checked)" /><span v-else class="selection-spacer" aria-hidden="true"></span><button class="folder-open" type="button" @dblclick="navigateToFolder(folder.id)" @click="selectFolder(folder)"><span class="resource-type-icon folder-type"><Folder :size="18" class="folder-symbol" /></span><strong>{{ folder.name }}</strong><span class="folder-kind">文件夹</span></button><div v-if="canManage" class="more-wrap" @click.stop><button class="icon" title="更多文件夹操作" aria-label="更多文件夹操作" @click="toggleMenu('folder', folder.id)"><MoreHorizontal :size="18" /></button><div v-if="isMenuOpen('folder', folder.id)" class="resource-menu" role="menu"><button @click="openEditor('rename-folder', folder)"><Pencil :size="14" />重命名</button><button @click="openEditor('move-folder', folder)"><FolderInput :size="14" />移动到</button><div class="menu-divider"></div><button class="danger" @click="removeFolder(folder); closeMenu()"><Trash2 :size="14" />删除文件夹</button></div></div></div>
        <div v-for="doc in visibleDocuments" :key="doc.id" class="document-row" :class="{ expired: isExpired(doc), located: locatedDocumentId === doc.id }" :data-document-id="doc.id" tabindex="-1">
          <input type="checkbox" :aria-label="`选择 ${doc.name}`" :checked="selectedIds.includes(doc.id)" :disabled="uploading || deleting" @change="selectDocument(doc.id, $event.target.checked)" />
          <span class="resource-type-icon file-type" :class="typeClass(doc.name)">{{ extension(doc.name) }}</span>
          <div class="document-info">
          <button class="document-name" :title="doc.name" @click="preview = doc">
          <strong>{{ doc.name }} <Pencil v-if="canEdit(doc)" :size="12" class="inline-pencil" @click.stop="renameDoc(doc)" /></strong>
          </button>
          <div class="document-details">
            <span class="meta-line">
              <span v-if="doc.metadata_json?.extraction_status === 'error'" class="extraction-status status-error" :title="extractionLabel(doc)">{{ extractionLabel(doc) }}</span>
              <span class="meta-details"><span v-if="doc.metadata_json?.extraction_status === 'error'"> · </span>{{ formatSize(doc.metadata_json?.size) }}<span v-if="doc.created_at"> · {{ new Date(doc.created_at).toLocaleDateString('zh-CN') }}</span> · <span class="validity-label" :class="{ expired: isExpired(doc) }">{{ validityLabel(doc) }}</span><span v-if="documentStatus(doc)" class="job-status status-error" :title="documentErrors(doc)"> · {{ documentStatus(doc) }}</span></span>
            </span>
            <button type="button" class="copy-path" :title="'复制完整路径：' + documentPath(doc)" :aria-label="'复制文件路径 ' + doc.name" @click="copyDocumentPath(doc)"><FolderTree :size="14" /></button>
            <button v-if="isFiltering" type="button" class="copy-path" :title="'打开所在文件夹：' + folderPath(doc.folder_id)" :aria-label="'打开所在文件夹 ' + doc.name" @click="openContainingFolder(doc)"><FolderOpen :size="14" /></button>
          </div>
          </div>
          <button class="quiet preview-action" @click="preview = doc"><Eye :size="15" />预览</button>
          <button class="quiet summary-action" @click="summaryTarget = doc"><ScrollText :size="15" />摘要</button>
          <div class="more-wrap" @click.stop><button class="icon" :aria-label="`更多文件操作 ${doc.name}`" title="更多" @click="toggleMenu('doc', doc.id)"><MoreHorizontal :size="18" /></button><div v-if="isMenuOpen('doc', doc.id)" class="resource-menu resource-menu-right" role="menu"><button @click="downloadDocuments(doc); closeMenu()"><Download :size="14" />下载</button><button v-if="canEdit(doc)" @click="openEditor('rename-doc', doc)"><Pencil :size="14" />重命名</button><button v-if="canEdit(doc)" @click="openEditor('move-doc', doc)"><FolderInput :size="14" />移动到</button><button v-if="canEdit(doc)" @click="validityTarget = doc; closeMenu()"><CalendarClock :size="14" />{{ isExpired(doc) ? '续期' : '修改有效期' }}</button><button v-if="canManage && canPush && kb.agent_id" @click="pushTarget = doc; closeMenu()"><Share2 :size="14" />推送到公共库</button><button v-if="canEdit(doc) && doc.metadata_json?.extraction_status === 'error'" @click="retryExtraction(doc); closeMenu()">重试识别</button><button v-if="canEdit(doc) && doc.metadata_json?.index_status === 'error'" @click="retryIndex(doc); closeMenu()">重试索引</button><div class="menu-divider"></div><button v-if="canEdit(doc)" class="danger" @click="confirmTarget = { type: 'doc', id: doc.id, name: doc.name }; closeMenu()"><Trash2 :size="14" />删除文件</button></div></div>
        </div>
        <div v-if="currentDocuments.length > pageSize" class="list-pagination"><span>共 {{ currentDocuments.length }} 个文件 · 每页 {{ pageSize }} 个</span><button :disabled="listPage === 1" @click="listPage--">上一页</button><span>{{ listPage }} / {{ pageCount }}</span><button :disabled="listPage === pageCount" @click="listPage++">下一页</button></div>
        </div></div>
      </div>
    <DocumentPreview v-if="preview" :key="preview.id" :kb-id="kb.id" :doc-id="preview.id" :name="preview.name" :readonly="readonly" @close="preview = null" />
    <PushDocumentDialog v-if="pushTarget" :kb="kb" :doc="pushTarget" @close="pushTarget = null" @pushed="$emit('pushed', $event)" />
    <DocumentValidityDialog v-if="validityTarget" :kb-id="kb.id" :doc="validityTarget" @close="validityTarget = null" @saved="validitySaved" />
    <DocumentSummaryDialog v-if="summaryTarget" :kb-id="kb.id" :doc="summaryTarget" :readonly="readonly" @close="summaryTarget = null" @saved="summarySaved" @queued="summaryTarget = null; loadDocs()" />
    <CreateTextDocDialog v-if="createTextDocTarget" :kb-id="kb.id" :folder-id="currentFolderId" @close="createTextDocTarget = false" @created="onTextDocCreated" />
    <ConfirmDialog v-if="confirmTarget" :title="confirmTarget.type === 'kb' ? '删除知识库？' : confirmTarget.type === 'batch' ? '批量删除资源？' : '删除文档？'" :message="confirmationMessage" :busy="deleting" @cancel="confirmTarget = null" @confirm="performDelete" />
    <Teleport v-if="pageTabActive" to="body">
      <div v-if="editor" class="editor-overlay" @click.self="closeEditor" @keydown.esc.stop="closeEditor" @keydown.tab="trapEditorFocus">
        <form ref="editorForm" class="resource-editor" role="dialog" aria-modal="true" :aria-labelledby="'resource-editor-title-' + kb.id" @submit.prevent="submitEditor">
          <div class="editor-heading">
            <h3 :id="'resource-editor-title-' + kb.id">{{ editorTitle }}</h3>
            <button type="button" class="icon" aria-label="关闭" :disabled="editorBusy" @click="closeEditor"><X :size="18" /></button>
          </div>
          <label v-if="!['move-docs', 'move-resources', 'move-folder'].includes(editor.type)" class="editor-field">
            名称
            <input v-model="editor.value" class="form-input" :placeholder="editor.type === 'create-folder' ? '请输入文件夹名称' : '请输入名称'" :readonly="editor.type === 'move-doc'" :disabled="editorBusy" maxlength="200" required />
          </label>
          <div v-if="editor.type === 'create-folder' || editor.type.startsWith('move-')" class="editor-field">
            <span>{{ editor.type === 'create-folder' ? '父级文件夹' : '目标位置' }}</span>
            <SearchSelect v-model="editor.parentId" :options="editorOptions" :aria-label="editor.type === 'create-folder' ? '父级文件夹' : '目标位置'" search-placeholder="搜索文件夹名称或路径" :disabled="editorBusy" />
          </div>
          <div class="editor-actions">
            <button type="button" class="btn btn-ghost btn-sm" :disabled="editorBusy" @click="closeEditor">取消</button>
            <button type="submit" class="btn btn-primary btn-sm" :disabled="editorBusy">{{ editorBusy ? '保存中…' : '保存' }}</button>
          </div>
        </form>
      </div>
    </Teleport>
  </article>
</template>
<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount, inject } from 'vue'
import { PanelLeftOpen, PanelLeftClose, FolderOpen, Folder, FolderTree, FolderPlus, FolderInput, ChevronDown, ChevronUp, ChevronRight, Trash2, Search, RefreshCw, Files, Eye, Share2, Download, CalendarClock, ScrollText, FilePlus, Pencil, Power, Plus, MoreHorizontal, Copy, X } from 'lucide-vue-next'
import { knowledgeApi } from '../../api'
import KnowledgeUpload from './KnowledgeUpload.vue'
import SearchSelect from '../SearchSelect.vue'
import DocumentPreview from './DocumentPreview.vue'
import ConfirmDialog from './ConfirmDialog.vue'
import PushDocumentDialog from './PushDocumentDialog.vue'
import DocumentValidityDialog from './DocumentValidityDialog.vue'
import DocumentSummaryDialog from './DocumentSummaryDialog.vue'
import CreateTextDocDialog from './CreateTextDocDialog.vue'
import { documentBusy, documentStatus, documentErrors } from './documentStatus.js'
const props = defineProps({ kb: { type: Object, required: true }, readonly: Boolean, canPush: { type: Boolean, default: true }, canManage: Boolean, canUse: Boolean, refreshKey: { type: Number, default: 0 } })
const emit = defineEmits(['deleted', 'documents-change', 'pushed'])
const pageTabActive = inject('pageTabActive', true)
const editorForm = ref(null)
let editorPreviousFocus
const documents = ref([]), loading = ref(false), loadError = ref(''), expanded = ref(false), uploading = ref(false), search = ref(''), typeFilter = ref(null), listPage = ref(1), preview = ref(null), confirmTarget = ref(null), deleting = ref(false)
const selectedIds = ref([]), selectedFolderIds = ref([]), pushTarget = ref(null), validityTarget = ref(null), downloading = ref(null)
const summaryTarget = ref(null), uploadRef = ref(null)
const createTextDocTarget = ref(false)
const folders = ref([]), currentFolderId = ref(null), expandedFolderIds = ref(new Set()), moreOpen = ref(null), editor = ref(null), editorBusy = ref(false)
import { auth } from '../../auth'
const canManage = computed(() => !props.readonly && props.canManage)
const canUse = computed(() => !props.readonly && props.canUse)
const canEdit = doc => canManage.value || (canUse.value && doc.created_by && doc.created_by === auth.user?.id)
const explorerExpanded = ref(false)
const isFiltering = computed(() => Boolean(search.value.trim()) || typeFilter.value !== null)
const showExplorer = computed(() => explorerExpanded.value && !isFiltering.value)
const documentListRef = ref(null), locatedDocumentId = ref(null)
const visibleFolders = computed(() => isFiltering.value ? [] : folders.value.filter(folder => (folder.parent_id || null) === currentFolderId.value))
const treeFolders = computed(() => { const result = []; const walk = (parent, depth) => folders.value.filter(folder => (folder.parent_id || null) === parent).sort((a, b) => a.name.localeCompare(b.name)).forEach(folder => { const children = folders.value.some(item => item.parent_id === folder.id); result.push({ folder, depth, hasChildren: children, count: documents.value.filter(doc => doc.folder_id === folder.id).length }); if (children && expandedFolderIds.value.has(folder.id)) walk(folder.id, depth + 1) }); walk(null, 0); return result })
const editorTitle = computed(() => ({ 'rename-kb': '重命名知识库', 'create-folder': '新建文件夹', 'rename-folder': '重命名文件夹', 'move-folder': '移动文件夹', 'rename-doc': '重命名文件', 'move-doc': '移动文件', 'move-docs': `移动 ${selectedIds.value.length} 个文件`, 'move-resources': `移动 ${totalSelectedCount.value} 个项目` }[editor.value?.type] || '编辑'))
const editorOptions = computed(() => {
  const result = [{ value: null, label: '根目录' }]
  const blocked = new Set()
  const collect = id => { blocked.add(id); folders.value.filter(folder => folder.parent_id === id).forEach(folder => collect(folder.id)) }
  if (editor.value?.type === 'move-folder' && editor.value.target?.id) collect(editor.value.target.id)
  if (editor.value?.type === 'move-resources') selectedFolderIds.value.forEach(collect)
  const walk = (parent, path) => folders.value.filter(folder => (folder.parent_id || null) === parent).forEach(folder => { if (!blocked.has(folder.id)) { const label = path ? path + ' / ' + folder.name : folder.name; result.push({ value: folder.id, label }); walk(folder.id, label) } })
  walk(null, '')
  return result
})
const folderById = computed(() => new Map(folders.value.map(folder => [folder.id, folder])))
function folderAncestors(folderId) {
  const result = [], visited = new Set()
  let id = folderId
  while (id && !visited.has(id)) {
    visited.add(id)
    const folder = folderById.value.get(id)
    if (!folder) break
    result.unshift(folder); id = folder.parent_id
  }
  return result
}
const breadcrumbs = computed(() => folderAncestors(currentFolderId.value))
const folderPath = folderId => [props.kb.name, ...folderAncestors(folderId).map(folder => folder.name)].join(' / ')
const documentPath = doc => `${folderPath(doc.folder_id)} / ${doc.name}`
const readablePath = computed(() => folderPath(currentFolderId.value))
const resourcePath = computed(() => currentFolderId.value ? `/api/knowledge/${props.kb.id}/folders/${currentFolderId.value}` : `/api/knowledge/${props.kb.id}`)
const copiedPath = computed(() => `路径：${readablePath.value}\nAPI：${resourcePath.value}`)
const statusUpdating = ref(false), status = ref(props.kb.status || 'active')
const pageSize = 10
function openUploadPicker() { uploadRef.value?.openPicker() }
const fileTypeOptions = [{ value: 'all', label: '全部类型' }, { value: 'pdf', label: 'PDF' }, { value: 'document', label: '文档' }, { value: 'sheet', label: '表格' }, { value: 'slides', label: '演示' }, { value: 'image', label: '图片' }, { value: 'text', label: '文本' }, { value: 'other', label: '其他' }]
const enabled = computed(() => status.value === 'active')
watch(() => props.kb.status, value => { status.value = value || 'active' })
const totalSelectedCount = computed(() => selectedIds.value.length + selectedFolderIds.value.length)
const visibleResourceCount = computed(() => visibleDocuments.value.length + (canManage.value ? visibleFolders.value.length : 0))
const allVisibleSelected = computed(() => visibleResourceCount.value > 0 && visibleDocuments.value.every(doc => selectedIds.value.includes(doc.id)) && (!canManage.value || visibleFolders.value.every(folder => selectedFolderIds.value.includes(folder.id))))
const someVisibleSelected = computed(() => visibleDocuments.value.some(doc => selectedIds.value.includes(doc.id)) || (canManage.value && visibleFolders.value.some(folder => selectedFolderIds.value.includes(folder.id))))
const hiddenSelectedCount = computed(() => selectedIds.value.filter(id => !visibleDocuments.value.some(doc => doc.id === id)).length + selectedFolderIds.value.filter(id => !visibleFolders.value.some(folder => folder.id === id)).length)
const selectedCanEdit = computed(() => (!selectedFolderIds.value.length || canManage.value) && documents.value.filter(doc => selectedIds.value.includes(doc.id)).every(canEdit))
const confirmationMessage = computed(() => {
  const target = confirmTarget.value
  if (!target) return ''
  if (target.type === 'kb') return `将删除「${target.name}」及其中的 ${documents.value.length} 个文档。此操作无法撤销。`
  if (target.type === 'batch') {
    const names = [...target.folders.map(folder => `• 文件夹：${folder.name}`), ...target.docs.map(doc => `• 文件：${doc.name}`)]
    return `确定删除以下 ${target.docs.length} 个文件和 ${target.folders.length} 个文件夹？文件夹必须为空；若任一文件夹非空，整次操作将取消。此操作无法撤销。\n\n${names.join('\n')}`
  }
  return `确定删除「${target.name}」？删除后将无法从此知识库检索该文档，此操作无法撤销。`
})
function selectDocument(id, checked) { selectedIds.value = checked ? [...new Set([...selectedIds.value, id])] : selectedIds.value.filter(value => value !== id) }
function selectFolderResource(id, checked) { selectedFolderIds.value = checked ? [...new Set([...selectedFolderIds.value, id])] : selectedFolderIds.value.filter(value => value !== id) }
function clearSelection() { selectedIds.value = []; selectedFolderIds.value = [] }
function selectPage(checked) { for (const doc of visibleDocuments.value) selectDocument(doc.id, checked); if (canManage.value) for (const folder of visibleFolders.value) selectFolderResource(folder.id, checked) }
function confirmBatch() {
  if (!totalSelectedCount.value || uploading.value || deleting.value) return
  confirmTarget.value = { type: 'batch', docs: documents.value.filter(doc => selectedIds.value.includes(doc.id)).map(doc => ({ id: doc.id, name: doc.name })), folders: folders.value.filter(folder => selectedFolderIds.value.includes(folder.id)).map(folder => ({ id: folder.id, name: folder.name })) }
}
watch(() => props.refreshKey, () => loadDocs())
const typeCategory = name => { const ext = extension(name); if (ext === 'PDF') return 'pdf'; if (['DOC','DOCX','ODT','RTF'].includes(ext)) return 'document'; if (['XLS','XLSX','CSV','ODS'].includes(ext)) return 'sheet'; if (['PPT','PPTX','ODP'].includes(ext)) return 'slides'; if (['PNG','JPG','JPEG','GIF','WEBP','TIFF','SVG'].includes(ext)) return 'image'; if (['TXT','MD','JSON','XML','YAML','YML'].includes(ext) || !name?.includes('.')) return 'text'; return 'other' }
const filtered = computed(() => documents.value.filter(doc => (doc.name || '').toLowerCase().includes(search.value.trim().toLowerCase()) && (typeFilter.value === null || typeFilter.value === 'all' || typeCategory(doc.name) === typeFilter.value)))
const pageCount = computed(() => Math.max(1, Math.ceil(currentDocuments.value.length / pageSize)))
const currentDocuments = computed(() => isFiltering.value ? filtered.value : filtered.value.filter(doc => (doc.folder_id || null) === currentFolderId.value))
const visibleDocuments = computed(() => currentDocuments.value.slice((listPage.value - 1) * pageSize, listPage.value * pageSize))
const totalSize = computed(() => documents.value.reduce((n, doc) => n + (doc.metadata_json?.size || 0), 0))
watch([search, typeFilter], () => { listPage.value = 1; clearSelection(); closeMenu(); locatedDocumentId.value = null })
watch(pageCount, count => listPage.value = Math.min(listPage.value, count))
const formatSize = size => !size ? '' : size < 1024 ? `${size} B` : size < 1048576 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1048576).toFixed(1)} MB`
const extension = name => (name?.includes('.') ? name.split('.').pop().slice(0, 5).toUpperCase() : 'TEXT')
const typeClass = name => { const ext = extension(name); return ['PDF'].includes(ext) ? 'pdf' : ['XLS', 'XLSX', 'CSV'].includes(ext) ? 'sheet' : ['PNG', 'JPG', 'JPEG', 'GIF', 'WEBP', 'TIFF'].includes(ext) ? 'image' : ['PPT', 'PPTX'].includes(ext) ? 'slides' : 'text' }
const toast = (message, type = 'success') => window.dispatchEvent(new CustomEvent('toast', { detail: { message, type } }))
function copyResourcePath() { return copyPath(copiedPath.value, '可读路径和 API 路径已复制') }
function copyDocumentPath(doc) { return copyPath(documentPath(doc), '文件完整路径已复制') }
async function copyPath(value, message) {
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value)
    else {
      const input = document.createElement('textarea')
      input.value = value; input.setAttribute('readonly', ''); input.style.position = 'fixed'; input.style.opacity = '0'
      document.body.appendChild(input); input.select()
      let copied
      try { copied = document.execCommand('copy') } finally { input.remove() }
      if (!copied) throw new Error('copy failed')
    }
    toast(message)
  } catch { toast('复制路径失败，请重试', 'error') }
}
function toggleMenu(type, id) { moreOpen.value = moreOpen.value?.type === type && moreOpen.value.id === id ? null : { type, id } }
function isMenuOpen(type, id) { return moreOpen.value?.type === type && moreOpen.value.id === id }
function closeMenu() { moreOpen.value = null }
function revealFolderPath(folderId) {
  const next = new Set(expandedFolderIds.value)
  for (const folder of folderAncestors(folderId)) if (folder.parent_id) next.add(folder.parent_id)
  expandedFolderIds.value = next
}
function returnToBrowsing() { search.value = ''; typeFilter.value = null; listPage.value = 1; clearSelection(); closeMenu(); locatedDocumentId.value = null }
function navigateToFolder(folderId) { returnToBrowsing(); currentFolderId.value = folderId; revealFolderPath(folderId) }
async function openContainingFolder(doc) {
  navigateToFolder(doc.folder_id || null)
  // Let filter watchers reset pagination before locating the document.
  await nextTick()
  const index = currentDocuments.value.findIndex(item => item.id === doc.id)
  if (index < 0) return
  listPage.value = Math.floor(index / pageSize) + 1
  locatedDocumentId.value = doc.id
  await nextTick()
  const row = Array.from(documentListRef.value?.querySelectorAll('[data-document-id]') || []).find(item => item.dataset.documentId === String(doc.id))
  row?.focus({ preventScroll: true })
  row?.scrollIntoView({ block: 'nearest' })
}
function selectRoot() { navigateToFolder(null) }
function selectFolder(folder) { navigateToFolder(folder.id) }
function toggleFolderExpansion(folderId) {
  const next = new Set(expandedFolderIds.value)
  if (next.has(folderId)) next.delete(folderId)
  else next.add(folderId)
  expandedFolderIds.value = next
}
function openEditor(type, target = null) {
  editorPreviousFocus = document.activeElement
  closeMenu()
  const suffix = target?.name?.includes('.') ? target.name.slice(target.name.lastIndexOf('.')) : ''
  editor.value = { type, target, value: type === 'rename-doc' ? target.name.slice(0, target.name.length - suffix.length) : (target?.name || ''), parentId: type === 'move-doc' ? (target.folder_id || null) : type === 'move-folder' ? (target.parent_id || null) : currentFolderId.value }
}
watch(editor, async (value, previous) => {
  await nextTick()
  if (value && !previous) editorForm.value?.querySelector('input:not([readonly]), .search-select-trigger')?.focus()
  if (!value && previous && editorPreviousFocus?.isConnected) editorPreviousFocus.focus()
})
function trapEditorFocus(event) {
  const controls = Array.from(editorForm.value?.querySelectorAll('button:not(:disabled), input:not(:disabled)') || [])
  const first = controls[0], last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
function closeEditor() { if (!editorBusy.value) editor.value = null }
async function submitEditor() {
  if (!editor.value || editorBusy.value) return
  const current = editor.value; editorBusy.value = true
  try {
    if (current.type === 'rename-kb') { const { data } = await knowledgeApi.rename(props.kb.id, current.value.trim()); Object.assign(props.kb, data); toast('知识库已重命名') }
    else if (current.type === 'create-folder') { await knowledgeApi.createFolder(props.kb.id, { name: current.value.trim(), parent_id: current.parentId }); await loadDocs(); toast('文件夹已创建') }
    else if (current.type === 'rename-folder') { await knowledgeApi.renameFolder(props.kb.id, current.target.id, current.value.trim()); await loadDocs(); toast('文件夹已重命名') }
    else if (current.type === 'move-folder') { await knowledgeApi.moveFolder(props.kb.id, current.target.id, current.parentId); await loadDocs(); toast('文件夹已移动') }
    else if (current.type === 'rename-doc') { const { data } = await knowledgeApi.renameDoc(props.kb.id, current.target.id, current.value.trim()); Object.assign(current.target, data); toast('文件已重命名') }
    else if (current.type === 'move-doc' || current.type === 'move-docs') { const docs = current.type === 'move-doc' ? [current.target] : documents.value.filter(doc => selectedIds.value.includes(doc.id)); if (!docs.length || docs.some(doc => !canEdit(doc))) throw new Error('只能移动自己上传的文件'); await knowledgeApi.moveDocs(props.kb.id, docs.map(doc => doc.id), current.parentId); clearSelection(); await loadDocs(); toast('文件已移动') }
    else if (current.type === 'move-resources') { await knowledgeApi.moveResources(props.kb.id, selectedIds.value, selectedFolderIds.value, current.parentId); clearSelection(); await loadDocs(); toast('所选项目已移动') }
    editor.value = null
  } catch (e) { toast((e.message === '只能移动自己上传的文件' ? e.message : '操作失败：' + (e.response?.data?.detail || e.message || '请重试')), 'error') }
  finally { editorBusy.value = false }
}
async function removeFolder(folder) {
  if (!window.confirm('确定删除文件夹？仅能删除空文件夹。')) return
  try { await knowledgeApi.deleteFolder(props.kb.id, folder.id); await loadDocs(); toast('文件夹已删除') }
  catch (e) { toast('删除文件夹失败：' + (e.response?.data?.detail || '请先移空文件夹'), 'error') }
}
async function renameKB() { openEditor('rename-kb', props.kb) }
async function toggleStatus() {
  if (statusUpdating.value) return
  statusUpdating.value = true
  const nextStatus = enabled.value ? 'disabled' : 'active'
  try {
    const { data } = await knowledgeApi.updateStatus(props.kb.id, nextStatus)
    Object.assign(props.kb, data)
    status.value = data.status || 'active'
    toast(nextStatus === 'active' ? '知识库已启用' : '知识库已禁用')
  } catch (e) { toast('状态更新失败：' + (e.response?.data?.detail || '请重试'), 'error') }
  finally { statusUpdating.value = false }
}
async function renameDoc(doc) { openEditor('rename-doc', doc) }
const extractionLabel = doc => ({ pending: '等待文字识别', processing: '正在识别文字…', ready: doc.metadata_json.ocr_pages ? '文字已识别（OCR）' : '文字已提取', error: '文字识别失败：' + (doc.metadata_json.extraction_error || '请重试') }[doc.metadata_json.extraction_status])
const shanghaiDate = () => { const parts = Object.fromEntries(new Intl.DateTimeFormat('en', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date()).map(part => [part.type, part.value])); return `${parts.year}-${parts.month}-${parts.day}` }
const isExpired = doc => Boolean(doc.valid_until && doc.valid_until < shanghaiDate())
const validityLabel = doc => isExpired(doc) ? `已过期 · 有效期至 ${doc.valid_until}` : doc.valid_until ? `有效期至 ${doc.valid_until}` : '永久有效'
function validitySaved(updated) {
  const index = documents.value.findIndex(doc => doc.id === updated.id)
  if (index >= 0) documents.value[index] = updated
  validityTarget.value = null
  emit('documents-change', documents.value)
  toast(isExpired(updated) ? '有效期已更新，文件当前已过期' : '有效期已更新')
}
function summarySaved(updated) {
  const index = documents.value.findIndex(doc => doc.id === updated.id)
  if (index >= 0) documents.value[index] = updated
  summaryTarget.value = null
  emit('documents-change', documents.value)
  toast('摘要已保存，检索时立即生效')
}
function onTextDocCreated() {
  createTextDocTarget.value = false
  loadDocs()
  toast('文本文档已创建')
}
async function retryExtraction(doc) {
  try { await knowledgeApi.extractDoc(props.kb.id, doc.id); await loadDocs() }
  catch { toast('无法启动识别，请重试', 'error') }
}
async function retryIndex(doc) {
  try { await knowledgeApi.reindexDoc(props.kb.id, doc.id); await loadDocs() }
  catch (error) { toast(error.response?.data?.detail || '无法启动索引，请重试', 'error') }
}
let pollTimer, disposed = false
onBeforeUnmount(() => { disposed = true; clearTimeout(pollTimer) })
let requestId = 0
async function loadDocs() {
  const id = ++requestId
  loading.value = true; loadError.value = ''
  try {
    const { data } = await knowledgeApi.detail(props.kb.id)
    if (id !== requestId) return
    documents.value = data.documents || []; folders.value = data.folders || []; if (currentFolderId.value && !folders.value.some(folder => folder.id === currentFolderId.value)) currentFolderId.value = null; selectedIds.value = selectedIds.value.filter(id => documents.value.some(doc => doc.id === id)); selectedFolderIds.value = selectedFolderIds.value.filter(id => folders.value.some(folder => folder.id === id)); emit('documents-change', documents.value)
    if (summaryTarget.value) summaryTarget.value = documents.value.find(doc => doc.id === summaryTarget.value.id) || null
  } catch (e) { if (id === requestId) loadError.value = '文档列表加载失败，请重试' }
  finally {
    if (id === requestId) {
      loading.value = false
      clearTimeout(pollTimer)
      if (!disposed && documents.value.some(documentBusy)) pollTimer = setTimeout(loadDocs, 5000)
    }
  }
}
async function downloadDocuments(doc = null) {
  if (downloading.value) return
  const ids = [...selectedIds.value]
  if (!doc && !ids.length) return
  if (!doc && ids.length > 500) { toast('每次最多下载 500 个文档，请减少勾选数量', 'error'); return }
  downloading.value = doc ? doc.id : 'batch'
  try {
    const { data } = doc ? await knowledgeApi.downloadDoc(props.kb.id, doc.id) : await knowledgeApi.batchDownloadDocs(props.kb.id, ids)
    const url = URL.createObjectURL(data), link = document.createElement('a')
    link.href = url; link.download = doc ? doc.name : `${props.kb.name}.zip`
    document.body.appendChild(link); link.click(); link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  } catch (e) {
    let detail = e.response?.data?.detail
    if (e.response?.data instanceof Blob) { try { detail = JSON.parse(await e.response.data.text()).detail } catch {} }
    toast('下载失败：' + (detail || '请重试'), 'error')
  } finally { downloading.value = null }
}
async function performDelete() {
  if (deleting.value) return
  deleting.value = true
  try {
    if (confirmTarget.value.type === 'kb') { await knowledgeApi.delete(props.kb.id); emit('deleted', props.kb.id) }
    else if (confirmTarget.value.type === 'batch') {
      await knowledgeApi.batchDeleteResources(props.kb.id, confirmTarget.value.docs.map(doc => doc.id), confirmTarget.value.folders.map(folder => folder.id))
      clearSelection(); await loadDocs()
    }
    else { await knowledgeApi.deleteDoc(props.kb.id, confirmTarget.value.id); await loadDocs() }
    confirmTarget.value = null; toast('删除成功')
  } catch (e) { toast('删除失败：' + (e.response?.data?.detail || '请重试'), 'error') }
  finally { deleting.value = false }
}
function handleDocumentClick() { closeMenu() }
function handleKeydown(event) { if (event.key === 'Escape' && totalSelectedCount.value && !editor.value && !confirmTarget.value) clearSelection() }
onMounted(() => { loadDocs(); document.addEventListener('click', handleDocumentClick); document.addEventListener('keydown', handleKeydown) })
onBeforeUnmount(() => { document.removeEventListener('click', handleDocumentClick); document.removeEventListener('keydown', handleKeydown) })
</script>
<style scoped>
.job-status{font-size:11px;line-height:1.6;white-space:nowrap}
.document-details .meta-line{flex:0 1 auto;display:flex;align-items:center;max-width:100%;min-width:0;white-space:nowrap;overflow:hidden}
.extraction-status{min-width:0;overflow:hidden;text-overflow:ellipsis}
.meta-details{flex-shrink:0}
.document-row .status-error{color:var(--danger,#dc2626)}
.kb-status{display:inline-flex;align-items:center;padding:3px 7px;border-radius:999px;background:#16a34a14;color:#15803d;font-size:10px;font-weight:600;white-space:nowrap}.kb-status.disabled{background:#64748b18;color:#64748b}.status-action{color:#15803d!important}.status-action.disabled{color:#64748b!important}
.batch-toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:5px;width:100%;box-sizing:border-box;margin-bottom:6px;padding:8px 10px;background:color-mix(in srgb,var(--surface2,#f1f5f9) 72%,transparent);border-radius:8px;font-size:12px;color:var(--text3,#94a3b8)}.batch-toolbar strong{margin-right:5px;color:inherit;font-size:12px;font-weight:400}.batch-toolbar strong span{font-weight:400;color:inherit}.batch-toolbar button,.batch-select-page{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:30px;box-sizing:border-box;border:0;border-radius:7px;padding:5px 9px;background:transparent;color:inherit;font:inherit;font-size:12px;cursor:pointer}.batch-select-page{gap:6px}.batch-select-page input{width:15px;height:15px;margin:0;accent-color:var(--primary,#6366f1)}.batch-toolbar button:hover,.batch-select-page:hover{background:var(--surface2,#f1f5f9);color:var(--text2,#64748b)}.batch-toolbar button:disabled{opacity:.38;cursor:default}.batch-toolbar .batch-delete{color:inherit}.batch-toolbar .batch-delete:hover{background:var(--surface2,#f1f5f9);color:var(--text2,#64748b)}.batch-toolbar .batch-close{width:30px;margin-left:auto;padding:0;font-size:19px;line-height:1;color:inherit}.resource-divider{width:100%;height:1px;margin:0 0 10px;background:var(--border,#e2e8f0)}.batch-expand-enter-active,.batch-expand-leave-active{transition:opacity .16s ease,transform .16s ease}.batch-expand-enter-from,.batch-expand-leave-to{opacity:0;transform:translateY(-4px)}.push-action{color:var(--primary,#7c3aed)!important}.document-row>input,.folder-row>input{flex-shrink:0;accent-color:var(--primary,#7c3aed)}

.knowledge-card{border:1px solid var(--border,#e2e8f0);background:var(--surface,#fff);border-radius:15px;overflow:hidden;color:var(--text,#334155);box-shadow:0 2px 8px #00000003}.card-heading{display:flex;align-items:center;gap:12px;padding:20px}.knowledge-card.expanded .card-heading{padding-bottom:10px}.folder-icon{background:var(--navigation-background,var(--primary-light,#eef2ff));color:var(--navigation-color,var(--primary,#6366f1));height:44px;width:44px;display:grid;place-items:center;border-radius:12px;flex-shrink:0}.card-info{flex:1;min-width:0}.card-info h3{margin:0 0 6px;font-size:16px;font-weight:600;overflow-wrap:anywhere}.card-info p{margin:0;font-size:12px;color:var(--text3,#64748b);line-height:1.5;overflow-wrap:anywhere}.card-content{padding:0 20px 16px}.documents-toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin:0 0 10px}.documents-toolbar strong{font-size:13px;white-space:nowrap}.documents-toolbar strong span{display:inline-block;padding:2px 7px;border-radius:6px;background:var(--surface2,#f1f5f9);font-size:11px;margin-left:4px}.search{margin-left:auto;display:flex;align-items:center;gap:8px;padding:7px 10px;border:1px solid var(--border,#ddd);border-radius:8px;max-width:250px;min-width:80px;color:var(--text3,#64748b)}.search input{width:100%;border:0;outline:none;background:transparent;color:var(--text,#334155);font-size:12px;min-width:0}.quiet,.icon{border:0;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;gap:5px;background:transparent;color:var(--text3,#64748b);padding:7px;cursor:pointer;font-size:12px;white-space:nowrap}.quiet:hover,.icon:hover{background:var(--surface2,#f1f5f9);color:var(--primary,#6366f1)}.danger:hover{background:#ef444410;color:#dc2626}button:disabled{opacity:.4;cursor:default}.document-row{display:flex;align-items:center;gap:12px;padding:12px 6px;border-bottom:1px solid var(--border,#f1f5f9)}.document-row.expired{background:#f59e0b08}.document-row:last-child{border-bottom:0}.file-type{width:42px;height:44px;border-radius:8px;display:grid;place-items:center;font-size:9px;font-weight:700;flex-shrink:0;background:#3b82f612;color:#3b82f6}.file-type.pdf{background:#ef444412;color:#ef4444}.file-type.sheet{background:#10b98112;color:#059669}.file-type.image{background:#8b5cf612;color:#8b5cf6}.file-type.slides{background:#f9731612;color:#ea580c}.document-name{flex:1;min-width:0;border:0;background:transparent;text-align:left;cursor:pointer;display:flex;flex-direction:column;gap:5px;color:inherit;padding:0}.document-name strong{font-size:13px;font-weight:500;white-space:nowrap;text-overflow:ellipsis;overflow:hidden;max-width:100%}.document-name>span{font-size:11px;color:var(--text3,#64748b)}.document-name .validity-label{color:#16a34a}.document-name .validity-label.expired{color:#d97706;font-weight:600}.validity-action,.summary-action{color:var(--primary,#7c3aed)!important}.document-name:hover strong{color:var(--primary,#6366f1)}.empty{text-align:center;padding:30px 12px;color:var(--text3,#94a3b8);font-size:13px}.empty p{margin:12px 0 0}.list-error{font-size:13px;padding:24px;color:#dc2626}.list-pagination{display:flex;align-items:center;justify-content:flex-end;gap:12px;padding-top:14px;border-top:1px solid var(--border,#eee);font-size:12px;color:var(--text3,#64748b)}.list-pagination>span:first-child{margin-right:auto}.list-pagination button,.list-error button{border:1px solid var(--border,#ddd);border-radius:6px;background:var(--surface,#fff);color:inherit;font-size:12px;padding:5px 8px;cursor:pointer}@media(max-width:640px){.card-heading{padding:14px;gap:8px;flex-wrap:wrap}.knowledge-card.expanded .card-heading{padding-bottom:8px}.card-content{padding:0 14px 14px}.folder-icon{width:34px;height:34px}.card-info{min-width:130px}.documents-toolbar{gap:6px}.list-pagination{flex-wrap:wrap;gap:7px}.list-pagination>span:first-child{width:100%}.document-row{gap:7px;flex-wrap:wrap}.document-name{min-width:45%}.preview-action{font-size:0;gap:0}}
.folder-breadcrumbs{display:flex;align-items:center;gap:3px;width:100%;min-width:0;max-width:100%;overflow-x:auto;overflow-y:hidden;color:var(--text3,#64748b);font-size:12px;line-height:26px;white-space:nowrap;margin:0 0 8px;scrollbar-width:thin}.folder-breadcrumbs svg{flex:0 0 auto}.folder-breadcrumbs button{flex:0 0 auto;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:0;background:transparent;color:inherit;padding:4px 5px;border-radius:5px;cursor:pointer}.folder-breadcrumbs button:hover,.folder-breadcrumbs button:focus-visible{background:var(--surface2,#f1f5f9);color:var(--primary,#6366f1);outline:none}.toolbar-actions{display:flex;align-items:center;gap:8px;margin-left:auto;flex-shrink:0}.toolbar-action{min-height:34px;justify-content:center;white-space:nowrap}.toolbar-action svg{flex-shrink:0}.folder-row{display:flex;align-items:center;gap:10px;padding:9px 6px;border-bottom:1px solid var(--border,#f1f5f9)}.folder-open{display:flex;align-items:center;gap:8px;flex:1;min-width:0;border:0;background:transparent;color:var(--text,#334155);padding:4px 0;text-align:left;cursor:pointer}.folder-open svg{color:var(--primary,#6366f1);flex-shrink:0}.folder-open strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}.folder-open:hover strong{color:var(--primary,#6366f1)}.folder-actions{display:flex;align-items:center;gap:2px;flex-shrink:0}
.documents-toolbar .search{margin-left:0}
.file-type-filters{display:flex;align-items:center;gap:2px;flex-wrap:wrap;min-width:0}
.file-type-filter{border:0;border-radius:6px;background:transparent;color:var(--text3,#64748b);padding:7px 8px;cursor:pointer;font:inherit;font-size:12px;line-height:18px;white-space:nowrap}
.file-type-filter:hover,.file-type-filter:focus-visible{background:var(--surface2,#f1f5f9);color:var(--primary,#6366f1);outline:none}
.file-type-filter.selected{background:var(--primary-light);color:var(--navigation-color,var(--primary,#6366f1));font-weight:600}
@media(max-width:640px){.documents-toolbar{flex-wrap:wrap}.documents-toolbar .search{flex:1 1 180px;max-width:none}.file-type-filters{flex:1 1 100%;order:3;overflow:auto}.refresh-action{margin-left:auto}.toolbar-actions{flex:1 1 100%;order:4;justify-content:flex-end}.folder-breadcrumbs{margin-bottom:6px}}
.folder-kind{margin-left:auto;color:var(--text3,#94a3b8);font-size:11px}.resource-layout{display:grid;grid-template-columns:210px minmax(0,1fr);gap:18px;align-items:stretch}.folder-tree{border-right:1px solid var(--border,#eef2f7);padding-right:10px;min-height:180px}.tree-title{display:flex;justify-content:space-between;align-items:center;padding:4px 10px 9px;color:var(--text3,#64748b);font-size:11px;font-weight:600}.tree-count{font-weight:400;color:var(--text3,#94a3b8)}.tree-root,.tree-item{width:100%;display:flex;align-items:center;gap:7px;border:0;background:transparent;color:var(--text2,#475569);border-radius:7px;padding:7px 9px;text-align:left;font:inherit;font-size:12px;cursor:pointer}.tree-root:hover,.tree-item:hover,.tree-root.selected,.tree-item.selected{background:var(--navigation-background,var(--primary-light,#eef2ff));color:var(--navigation-color,var(--primary,#4f46e5))}.tree-root span:last-child,.tree-file-count{display:inline-flex;align-items:center;justify-content:center;width:24px;flex:0 0 24px;margin-left:auto;color:var(--text3,#94a3b8);font-size:11px;font-variant-numeric:tabular-nums}.tree-item svg:first-child{transition:transform .16s ease;flex-shrink:0}.tree-item svg.rotated{transform:rotate(90deg)}.tree-spacer{width:20px;flex-shrink:0}.tree-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.more-wrap{position:relative;display:inline-flex;flex-shrink:0}.resource-menu{position:absolute;right:0;top:calc(100% + 5px);z-index:20;min-width:154px;padding:5px;border:1px solid var(--border,#e2e8f0);border-radius:9px;background:var(--surface,#fff);box-shadow:0 12px 28px #1720331f}.resource-menu button{width:100%;display:flex;align-items:center;gap:8px;border:0;background:transparent;border-radius:6px;padding:8px 9px;color:var(--text,#334155);font:inherit;font-size:12px;text-align:left;cursor:pointer;white-space:nowrap}.resource-menu button:hover{background:var(--surface2,#f1f5f9);color:var(--primary,#4f46e5)}.resource-menu button.danger{color:var(--danger,#dc2626)}.resource-menu button.danger:hover{background:var(--danger-bg,#fef2f2);color:var(--danger,#dc2626)}.menu-divider{height:1px;background:var(--border,#eef2f7);margin:4px 2px}.editor-overlay{position:fixed;inset:0;z-index:2500;display:grid;place-items:center;padding:20px;background:var(--overlay)}
.resource-editor{box-sizing:border-box;width:min(400px,calc(100vw - 40px));max-width:100%;max-height:calc(100dvh - 40px);overflow-y:auto;padding:24px;border:1px solid var(--border);border-radius:var(--radius,12px);background:var(--surface);box-shadow:0 20px 60px #0003;color:var(--text)}
.editor-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;gap:12px}
.editor-heading h3{margin:0;font-size:18px;font-weight:600}
.editor-field{display:flex;flex-direction:column;gap:8px;font-size:13px;color:var(--text2)}
.editor-field + .editor-field{margin-top:20px}
.editor-field .form-input{box-sizing:border-box;min-height:40px;font:inherit;font-size:14px}
.editor-field :deep(.search-select-trigger){min-height:40px;font-size:14px}
.editor-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:24px}
.editor-actions .btn{min-height:36px;justify-content:center}
@media(max-width:760px){.resource-layout{grid-template-columns:1fr;align-items:start}.folder-tree{border-right:0;border-bottom:1px solid var(--border,#eef2f7);padding:0 0 10px;max-height:190px;overflow:auto}.tree-root,.tree-item{display:inline-flex;width:auto;min-width:150px;margin-right:3px}.folder-tree{white-space:nowrap}}@media(max-width:640px){.folder-kind{display:none}.resource-menu{position:fixed;right:12px;top:auto;margin-top:4px}}
.knowledge-card{position:relative;z-index:1;overflow:visible}.knowledge-card.menu-active{z-index:30}
.resource-layout{position:relative;z-index:1}.document-list{position:relative;min-width:0}.folder-row,.document-row{position:relative}
.resource-menu{z-index:1000}
.list-pagination{display:flex;align-items:center;justify-content:flex-end;gap:12px;width:100%;box-sizing:border-box;padding:14px 0 0;border-top:1px solid var(--border,#eee);font-size:12px;color:var(--text3,#64748b)}
.list-pagination>span:first-child{margin-right:0}
.tree-root svg,.tree-item .folder-symbol,.folder-open .folder-symbol{width:18px;height:18px;flex-shrink:0;color:var(--navigation-color,var(--primary,#6366f1));stroke-width:1.8}
.selection-spacer{width:18px;height:1px;flex:0 0 18px}
.resource-type-icon{box-sizing:border-box;width:42px;height:44px;border-radius:8px;display:grid;place-items:center;flex:0 0 42px}
.folder-type{background:var(--navigation-background,var(--primary-light,#eef2ff));color:var(--navigation-color,var(--primary,#6366f1))}
.folder-type .folder-symbol{width:20px;height:20px;color:currentColor;stroke-width:1.8}
.file-type{width:42px;height:44px;flex-basis:42px}
.folder-row{gap:12px;padding-top:8px;padding-bottom:8px}
.folder-open{gap:12px;padding:0}
.folder-open .folder-type{flex-shrink:0}
.folder-kind{margin-left:auto}
.document-row>input,.folder-row>input{width:18px;height:18px;margin:0}
.document-row .summary-action{color:var(--primary,#6366f1)!important}
.card-title-row{display:flex;align-items:center;gap:4px;width:fit-content;max-width:100%;min-width:0;margin-bottom:6px}
.kb-root-link{flex:0 1 auto;min-width:0;max-width:min(420px,45vw);margin:0;padding:0;border:0;background:transparent;color:inherit;font:inherit;font-size:16px;font-weight:600;line-height:24px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer}
.kb-root-link:hover,.kb-root-link:focus-visible{color:var(--primary,#6366f1);outline:none}
.header-breadcrumbs{flex:0 1 auto;width:auto;max-width:min(560px,48vw);min-width:0;margin:0;line-height:24px;scrollbar-width:none}
.header-breadcrumbs::-webkit-scrollbar{display:none}
.header-breadcrumbs>svg:first-of-type{margin-left:2px}
.copy-path{width:28px;height:28px;display:inline-grid;place-items:center;flex:0 0 28px;border:0;border-radius:6px;background:transparent;color:var(--text3,#64748b);cursor:pointer}
.copy-path:hover,.copy-path:focus-visible{background:var(--surface2,#f1f5f9);color:var(--primary,#6366f1);outline:none}
@media(max-width:640px){.selection-spacer{width:18px;flex-basis:18px}.resource-type-icon{width:42px;height:44px;flex-basis:42px}.folder-open{gap:7px}.summary-action{font-size:0;gap:0}.kb-root-link{max-width:42vw}.header-breadcrumbs{max-width:38vw}.header-breadcrumbs button{max-width:110px}.batch-toolbar{overflow-x:auto;flex-wrap:nowrap}.batch-toolbar button,.batch-select-page{padding:5px 7px;white-space:nowrap}}
@media(prefers-reduced-motion:reduce){.batch-expand-enter-active,.batch-expand-leave-active{transition:none}}
.tree-item{padding-top:0;padding-bottom:0;cursor:default;gap:4px}
.tree-toggle,.tree-folder{display:flex;align-items:center;border:0;background:transparent;color:inherit;font:inherit;cursor:pointer;border-radius:4px}
.tree-toggle{justify-content:center;flex:0 0 20px;width:20px;height:28px;padding:0}
.tree-toggle:hover{background:var(--surface2)}
.tree-folder{flex:1;min-width:0;gap:7px;padding:7px 0;text-align:left}
.tree-folder .tree-file-count{display:inline-flex;align-items:center;justify-content:center;width:24px;flex:0 0 24px;margin-left:auto;color:var(--text3);font-size:11px;font-variant-numeric:tabular-nums}
.resource-layout.without-explorer{grid-template-columns:minmax(0,1fr)}
.resource-layout.explorer-collapsed{grid-template-columns:36px minmax(0,1fr);gap:12px}
.explorer-pane{min-width:0;border-right:1px solid var(--border);padding-right:10px;min-height:180px}
.explorer-pane.collapsed{padding-right:5px}
.explorer-heading{display:flex;align-items:center;gap:6px;min-height:30px;margin-bottom:6px;color:var(--text2);white-space:nowrap}
.explorer-pane:not(.collapsed) .explorer-heading{padding-right:9px}
.explorer-title{color:var(--text2);font-size:12px;font-weight:400;line-height:1}
.explorer-heading .tree-count{display:inline-flex;align-items:center;justify-content:center;width:24px;flex:0 0 24px;margin-left:auto;color:var(--text2);font-size:12px;font-weight:600;font-variant-numeric:tabular-nums;line-height:1}
.explorer-toggle{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;padding:0;flex-shrink:0;border-radius:5px}
.explorer-toggle:hover{background:var(--surface2);color:var(--primary)}
.explorer-pane .folder-tree{border:0;padding:0;min-height:0;max-height:none;white-space:normal}
@media(max-width:760px){.resource-layout{grid-template-columns:136px minmax(0,1fr);gap:10px;align-items:stretch}.explorer-pane{padding-right:6px}.explorer-pane .tree-root,.explorer-pane .tree-item{display:flex;width:100%;min-width:0;box-sizing:border-box;margin-right:0}.resource-layout:not(.without-explorer):not(.explorer-collapsed) .document-list{overflow-x:auto}.resource-layout:not(.without-explorer):not(.explorer-collapsed) .document-row{min-width:300px}}
.search-results-heading{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;padding:4px 0 12px;color:var(--text2);font-size:12px}
.document-info{flex:1;min-width:0}
.document-info .document-name{width:100%;min-width:0}
.document-details{display:flex;align-items:center;gap:3px;min-width:0;margin-top:3px;color:var(--text3);font-size:11px}
.document-details .validity-label{color:var(--success,#16a34a)}
.document-details .validity-label.expired{color:var(--warning,#d97706);font-weight:600}
.document-details .copy-path{width:24px;height:24px;flex-basis:24px}
.document-row.located{background:var(--navigation-background,var(--surface2));border-radius:8px;box-shadow:inset 3px 0 var(--primary)}
.document-row:focus-visible,.document-details button:focus-visible{outline:2px solid var(--primary);outline-offset:2px}
@media(max-width:640px){.document-info{flex-basis:45%;min-width:0}.list-pagination{flex-wrap:wrap;gap:8px}.toolbar-actions{flex-wrap:wrap}}
@media(max-width:760px){.explorer-heading{gap:2px}.explorer-heading .explorer-toggle{width:24px;flex:0 0 24px}.explorer-title{font-size:11px}}
</style>
