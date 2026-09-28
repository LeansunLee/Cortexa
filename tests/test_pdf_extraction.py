import asyncio
import io
import os
import uuid
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@localhost/test')
import pypdfium2 as pdfium
import pytest
from cortexa.data import pdf_extraction, doc_storage


def blank_pdf():
    output = io.BytesIO()
    with closing(pdfium.PdfDocument.new()) as pdf:
        pdf.new_page(400, 600).close()
        pdf.new_page(400, 600).close()
        pdf.save(output)
    return output.getvalue()


def test_blank_text_layers_use_ocr_for_each_page(monkeypatch):
    calls, progress = [], []
    monkeypatch.setattr(pdf_extraction, 'recognize_image', lambda img: calls.append(img.size) or '政策补贴 5000 元')
    text, pages = pdf_extraction.extract_pdf(blank_pdf(), lambda *args: progress.append(args))
    assert pages == 2 and len(calls) == 2
    assert '【第 2 页】\n政策补贴 5000 元' in text
    assert progress == [(1, 2), (2, 2)]


def test_empty_ocr_is_not_success(monkeypatch):
    monkeypatch.setattr(pdf_extraction, 'recognize_image', lambda img: '  ')
    with pytest.raises(RuntimeError, match='未识别到文字'):
        pdf_extraction.extract_pdf(blank_pdf())


def test_ocr_failure_is_not_silently_swallowed(monkeypatch):
    def fail(img):
        raise RuntimeError('OCR 服务未安装')
    monkeypatch.setattr(pdf_extraction, 'recognize_image', fail)
    with pytest.raises(RuntimeError, match='未安装'):
        pdf_extraction.extract_pdf(blank_pdf())


def test_index_uses_full_content_and_rejects_binary(monkeypatch):
    from cortexa.rag import retriever, embedder
    from cortexa.rag import chunker
    doc = SimpleNamespace(id=uuid.uuid4(), content='summary', metadata_json={})
    db = AsyncMock(); db.get.return_value = doc; db.add = Mock()
    full = '完整正文'*1000 + '末页政策'
    monkeypatch.setattr(doc_storage, 'load_document_content', lambda ident: full)
    original = chunker.chunk_text
    observed = []
    monkeypatch.setattr(chunker, 'chunk_text', lambda text: observed.append(text) or original(text))
    monkeypatch.setattr(embedder, 'embed_texts', lambda texts: [])
    assert asyncio.run(retriever.index_document(db, doc.id, uuid.uuid4())) > 0
    assert observed == [full]
    doc.metadata_json = {'encoding': 'base64'}
    assert asyncio.run(retriever.index_document(db, doc.id, uuid.uuid4())) == 0
    assert len(observed) == 1


def test_retry_reuses_completed_pages(tmp_path, monkeypatch):
    path = tmp_path / 'original'
    path.write_bytes(blank_pdf())
    calls = []
    def recognize(img):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('temporary failure')
        return '首个页面政策'
    monkeypatch.setattr(pdf_extraction, 'recognize_image', recognize)
    with pytest.raises(RuntimeError):
        pdf_extraction.extract_pdf(path)
    monkeypatch.setattr(pdf_extraction, 'recognize_image', lambda img: '第二页政策')
    text, count = pdf_extraction.extract_pdf(path)
    assert count == 2 and '首个页面政策' in text and '第二页政策' in text


def test_bundled_engine_uses_explicit_language_directory(tmp_path, monkeypatch):
    from PIL import Image
    executable = tmp_path / 'bin' / 'tesseract'
    languages = tmp_path / 'share' / 'tessdata'
    languages.mkdir(parents=True)
    monkeypatch.setenv('TESSERACT_BIN', str(executable))
    def run(command, **kwargs):
        assert kwargs['env']['TESSDATA_PREFIX'] == str(languages)
        assert kwargs['env']['OMP_THREAD_LIMIT'] == '1'
        from pathlib import Path
        Path(command[2] + '.txt').write_text('中文政策', encoding='utf-8')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(pdf_extraction.subprocess, 'run', run)
    assert pdf_extraction.recognize_image(Image.new('RGB', (20, 20))) == '中文政策'
