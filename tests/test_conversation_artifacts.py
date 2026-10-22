"""Conversation artifact storage and save_document tool unit tests."""
import asyncio
import uuid

import pytest

from cortexa.conversation import artifacts as A


def test_safe_filename_strips_unsafe_characters():
    assert A.safe_filename('方案/报告: final*.md') == '方案_报告_ final_.md'
    assert A.safe_filename('') == '文档.md'
    assert A.safe_filename('..hidden..') == 'hidden'
    assert A.safe_filename('a' * 300) == 'a' * 255


def test_detect_format_by_extension():
    assert A.detect_format('方案.md') == 'markdown'
    assert A.detect_format('方案.markdown') == 'markdown'
    assert A.detect_format('数据.txt') == 'text'
    assert A.detect_format('无扩展名') == 'text'


def test_save_document_tool_reports_turn_cap():
    created = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    tool = A.save_document_tool(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), None, created)[0]
    result = asyncio.run(tool.ainvoke({'title': 'x', 'filename': 'x.md', 'content': '正文'}))
    assert result['success'] is False
    assert '上限' in result['error']
    assert len(created) == 3


def test_overwrite_writes_blob_and_measures(monkeypatch, tmp_path):
    monkeypatch.setattr(A, 'ROOT', tmp_path)
    ident = uuid.uuid4()
    text = '# 标题\n内容'
    size, digest = A.overwrite(ident, text)
    path = A.blob_path(ident)
    assert path.is_file()
    assert path.read_text(encoding='utf-8') == text
    assert size == len(text.encode('utf-8'))
    assert len(digest) == 64
    with pytest.raises(ValueError):
        A.overwrite(ident, 'x' * (A.MAX_BYTES + 1))


def test_resolve_path_scoped_under_root():
    row = type('Row', (), {'path': 'ab/cd.md'})()
    resolved = A.resolve_path(row)
    assert resolved == A.ROOT / 'ab' / 'cd.md'
