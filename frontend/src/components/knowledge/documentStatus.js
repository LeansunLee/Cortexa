export const pending = value => ['pending', 'processing'].includes(value)
export const documentBusy = doc => ['extraction_status', 'summary_status', 'index_status'].some(key => pending(doc.metadata_json?.[key]))
export function documentStatus(doc) {
  const metadata = doc.metadata_json || {}
  const labels = { pending: '等待处理', processing: '处理中', ready: '就绪', error: '失败', unsupported: '不支持' }
  return [['summary', '摘要'], ['index', '索引']].filter(([key]) => metadata[`${key}_status`] && metadata[`${key}_status`] !== 'ready')
    .map(([key, label]) => `${label}：${labels[metadata[`${key}_status`]] || metadata[`${key}_status`]}`)
    .join(' · ')
}
export const documentErrors = doc => ['extraction_error', 'summary_error', 'index_error'].map(key => doc.metadata_json?.[key]).filter(Boolean).join('；')
