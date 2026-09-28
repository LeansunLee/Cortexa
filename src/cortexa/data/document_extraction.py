"""Extract summary input from originals; never treat binary bytes as text."""
import asyncio
import json
from pathlib import Path
import zipfile

from starlette.concurrency import run_in_threadpool
from cortexa.data import document_preview as previews
from cortexa.data import pdf_extraction


async def extract_document(doc_id, name, metadata, original):
    """Return text, OCR page count and whether only file information is available."""
    kind = previews.file_kind(name, metadata)
    if kind == 'pdf':
        text, pages = await run_in_threadpool(pdf_extraction.extract_pdf, original)
        return text, pages, False
    if kind == 'image':
        text, pages = await run_in_threadpool(pdf_extraction.extract_image, original)
        return text, pages, False
    if kind == 'office':
        target = previews.pdf_file(doc_id, 'office')
        if not target.exists():
            previews.start_office_preview(doc_id, name)
            job = previews._jobs.get(doc_id)
            if job:
                await asyncio.shield(job)
        if not target.exists():
            error = previews.document_dir(doc_id) / 'preview-error.json'
            message = json.loads(error.read_text()).get('message') if error.exists() else None
            raise RuntimeError(message or 'Office 正文提取失败，请重试')
        text, pages = await run_in_threadpool(pdf_extraction.extract_pdf, target)
        return text, pages, False
    return await run_in_threadpool(extract_other, name, metadata, original)


def extract_other(name, metadata, original):
    # Limit generic decoding; known text documents retain their existing pipeline.
    with original.open('rb') as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) <= 2 * 1024 * 1024 and b'\x00' not in raw:
        try:
            text = raw.decode('utf-8-sig').strip()
            if text and sum(c.isprintable() or c.isspace() for c in text) / len(text) > .98:
                return text, 0, False
        except UnicodeError:
            pass
    if zipfile.is_zipfile(original):
        with zipfile.ZipFile(original) as archive:
            files = archive.infolist()
            entries = [f'{item.filename}（{item.file_size} 字节）' for item in files[:200]]
        text = f'压缩包 {name}，共 {len(files)} 个条目。以下是文件目录，未解压分析文件正文：\n' + '\n'.join(entries)
        if len(files) > 200:
            text += '\n仅列出前 200 个条目。'
        return text, 0, False
    extension = Path(name).suffix.lower() or '无扩展名'
    text = (f'文件信息摘要：{name}\n类型：{extension}；大小：{original.stat().st_size} 字节。\n'
            '该格式暂无法提取正文，本摘要仅包含文件信息，不代表文件的内容。可下载原文件查看或手动补充摘要。')
    return text, 0, True
