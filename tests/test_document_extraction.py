"""Automatic summaries for Office, archives and other uploads."""
import asyncio
import json
import zipfile
from unittest.mock import AsyncMock
import pytest
from agentdevstu.data import document_extraction as extraction, document_preview as previews, pdf_extraction


@pytest.mark.parametrize('name', ['report.doc', 'report.docx', 'sheet.xls', 'sheet.xlsx', 'slides.ppt', 'slides.pptx', 'notes.odt', 'notes.rtf'])
def test_office_conversion_feeds_pdf_extraction(tmp_path, monkeypatch, name):
    monkeypatch.setattr(previews, 'DOC_STORAGE_DIR', str(tmp_path))
    original = previews.save_original('doc', b'office contents')
    async def convert(doc_id, filename):
        target = previews.pdf_file(doc_id, 'office')
        target.parent.mkdir(parents=True)
        target.write_bytes(b'converted pdf')
    monkeypatch.setattr(previews, '_convert_office', convert)
    def extract(path):
        assert path.read_bytes() == b'converted pdf'
        return '全部页的正文和表格', 2
    monkeypatch.setattr(pdf_extraction, 'extract_pdf', extract)
    try:
        assert asyncio.run(extraction.extract_document('doc', name, {}, original)) == ('全部页的正文和表格', 2, False)
    finally:
        previews._jobs.clear()


def test_office_failure_is_not_summarized_as_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(previews, 'DOC_STORAGE_DIR', str(tmp_path))
    original = previews.save_original('doc', b'bad office')
    async def convert(*args):
        (original.parent / 'preview-error.json').write_text(json.dumps({'message': '文件受密码保护'}))
    monkeypatch.setattr(previews, '_convert_office', convert)
    try:
        with pytest.raises(RuntimeError, match='密码保护'):
            asyncio.run(extraction.extract_document('doc', 'bad.docx', {}, original))
    finally:
        previews._jobs.clear()


def test_unknown_binary_gets_honest_file_information(tmp_path):
    original = tmp_path / 'original'
    original.write_bytes(b'\x00\xff\x89binary')
    text, count, limited = extraction.extract_other('design.bin', {}, original)
    assert limited is True and count == 0
    assert '未' not in text or '正文' in text
    assert '暂无法提取正文' in text
    assert 'design.bin' in text
    assert 'binary' not in text


def test_unknown_extension_can_still_contain_text(tmp_path):
    original = tmp_path / 'original'
    original.write_text('内容无需通过文件扩展名猜测', encoding='utf-8')
    assert extraction.extract_other('notes.custom', {}, original) == ('内容无需通过文件扩展名猜测', 0, False)


def test_archive_lists_members_without_extracting_paths(tmp_path):
    original = tmp_path / 'original'
    with zipfile.ZipFile(original, 'w') as archive:
        archive.writestr('../outside.txt', 'inside content')
    text, _, limited = extraction.extract_other('archive.zip', {}, original)
    assert '../outside.txt' in text and '未解压分析文件正文' in text
    assert not (tmp_path.parent / 'outside.txt').exists()
    assert limited is False
