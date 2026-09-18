import test from 'node:test'
import assert from 'node:assert/strict'
import { documentBusy, documentStatus, documentErrors } from '../src/components/knowledge/documentStatus.js'

test('summary and index pending states keep polling active', () => {
  for (const key of ['summary_status', 'index_status', 'extraction_status']) {
    assert.equal(documentBusy({ metadata_json: { [key]: 'pending' } }), true)
    assert.equal(documentBusy({ metadata_json: { [key]: 'processing' } }), true)
  }
  assert.equal(documentBusy({ metadata_json: { index_status: 'error' } }), false)
})

test('status includes failure reasons without assuming PDF', () => {
  const doc = { metadata_json: { summary_status: 'error', index_status: 'ready', summary_error: 'provider unavailable' } }
  assert.match(documentStatus(doc), /摘要：失败/)
  assert.doesNotMatch(documentStatus(doc), /索引：就绪/)
  assert.equal(documentErrors(doc), 'provider unavailable')
})
