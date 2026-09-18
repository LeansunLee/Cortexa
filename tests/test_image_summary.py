"""Binary upload/legacy image regressions: never summarize encoded bytes."""
import asyncio
import io
import importlib
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, UploadFile
from PIL import Image
from agentdevstu.api import knowledge
from agentdevstu.data import doc_storage, document_preview as previews, pdf_extraction
from agentdevstu.rag import summary
from test_doc_summary import document
from test_knowledge_hardening import run_as_knowledge_admin


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(previews, 'DOC_STORAGE_DIR', str(tmp_path))
    monkeypatch.setattr(doc_storage, 'DOC_STORAGE_DIR', str(tmp_path))
    return tmp_path


@pytest.mark.parametrize('name,encoding,extraction', [('image.png', 'utf-8', 'pending'), ('file.docx', 'utf-8', 'pending'), ('file.bin', 'utf-8', 'pending')])
def test_binary_upload_never_saves_encoded_summary(storage, monkeypatch, name, encoding, extraction):
    db = AsyncMock()
    added = []
    db.add = added.append
    async def flush():
        added[-1].id = uuid.uuid4()
    db.flush.side_effect = flush
    monkeypatch.setattr(knowledge, '_ensure_document_name_available', AsyncMock())
    tasks = BackgroundTasks()
    raw = b'\x89PNG\x00\xff binary contents'
    doc = run_as_knowledge_admin(knowledge.ingest_document(uuid.uuid4(), tasks, UploadFile(filename=name, file=io.BytesIO(raw)), db))
    assert doc.content == ''
    assert doc_storage.load_document_content(str(doc.id)) == ''
    assert previews.original_file(str(doc.id), name, doc.metadata_json, '').read_bytes() == raw
    assert doc.metadata_json['encoding'] == encoding
    assert doc.metadata_json.get('extraction_status') == extraction
    assert [t.func for t in tasks.tasks] == ([knowledge._process_pdf] if extraction else [])


@pytest.mark.parametrize('recognized', ['清晰的图片正文', '   ', '...'])
def test_image_ocr_handles_transparency_and_no_text(storage, monkeypatch, recognized):
    path = storage / 'image.png'
    with Image.new('RGBA', (12, 12), (0, 0, 0, 0)) as image:
        image.save(path)
    def recognize(image):
        assert image.mode == 'RGB'
        assert image.getpixel((0, 0)) == (255, 255, 255)
        return recognized
    monkeypatch.setattr(pdf_extraction, 'recognize_image', recognize)
    if recognized.strip() and recognized != '...':
        assert pdf_extraction.extract_image(path) == (recognized, 1)
    else:
        with pytest.raises(RuntimeError, match='未识别到文字'):
            pdf_extraction.extract_image(path)


@pytest.mark.parametrize('manual,failed', [(False, False), (True, False), (False, True), (True, True)])
def test_legacy_image_pipeline_preserves_manual_summary(storage, monkeypatch, manual, failed):
    metadata = {'encoding': 'base64', 'extraction_status': 'pending'}
    if manual:
        metadata['summary_source'] = 'manual'
    doc = document('image.png', '人工摘要' if manual else '', metadata)
    previews.save_original(str(doc.id), b'original image bytes')
    doc_storage.save_document_content(str(doc.id), 'iVBORw0KGgo encoded image')
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.get.return_value = doc
    monkeypatch.setattr(importlib.import_module('agentdevstu.db.engine'), 'async_session_factory', lambda: session)
    def extract(path):
        assert path.read_bytes() == b'original image bytes'
        if failed:
            raise RuntimeError('未识别到文字')
        return '图片中识别出的正文', 1
    monkeypatch.setattr(pdf_extraction, 'extract_image', extract)
    generate = AsyncMock(return_value=('正常图片摘要', 'llm'))
    monkeypatch.setattr(summary, 'generate_document_summary', generate)
    index = AsyncMock()
    monkeypatch.setattr(knowledge, '_safe_index', index)
    asyncio.run(knowledge._process_pdf_impl(doc.id, doc.knowledge_base_id))
    assert doc.content == ('人工摘要' if manual else '' if failed else '正常图片摘要')
    assert doc.metadata_json['extraction_status'] == ('error' if failed else 'ready')
    assert doc.metadata_json['summary_status'] == ('error' if failed and not manual else 'ready')
    if failed:
        generate.assert_not_awaited()
        index.assert_not_awaited()
        assert doc.metadata_json['index_status'] == 'error'
    else:
        generate.assert_awaited_once_with('image.png', '图片中识别出的正文')
        assert doc_storage.load_document_content(str(doc.id)) == '图片中识别出的正文'
        assert doc.metadata_json['encoding'] == 'utf-8'
        index.assert_awaited_once()


def test_legacy_image_can_retry_extraction(monkeypatch):
    doc = document('image.png', '', {'encoding': 'base64', 'summary_status': 'unsupported'})
    monkeypatch.setattr(knowledge, '_preview_document_record', AsyncMock(return_value=doc))
    tasks = BackgroundTasks()
    run_as_knowledge_admin(knowledge.retry_pdf_extraction(doc.knowledge_base_id, doc.id, tasks, AsyncMock(), None))
    assert doc.metadata_json['summary_status'] == 'pending'
    assert [t.func for t in tasks.tasks] == [knowledge._process_pdf]
