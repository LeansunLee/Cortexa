<template>
  <TextDocumentEditorDialog v-model="content" v-model:name="docName" creating :saving="saving" :error="errorMessage" @close="$emit('close')" @save="create" />
</template>
<script setup>
import { ref } from 'vue'
import TextDocumentEditorDialog from './TextDocumentEditorDialog.vue'
import { knowledgeApi } from '../../api'
const props = defineProps({ kbId: { type: String, required: true }, folderId: { type: String, default: null } })
const emit = defineEmits(['close', 'created'])
const docName = ref('')
const content = ref('')
const saving = ref(false)
const errorMessage = ref('')
async function create() {
  if (saving.value || !docName.value.trim() || !content.value.trim()) return
  saving.value = true
  errorMessage.value = ''
  try {
    const payload = { name: docName.value.trim(), content: content.value }
    if (props.folderId) payload.folder_id = props.folderId
    await knowledgeApi.addDoc(props.kbId, payload)
    emit('created')
  } catch (error) { errorMessage.value = '创建失败：' + (error.response?.data?.detail || '请重试') }
  finally { saving.value = false }
}
</script>
