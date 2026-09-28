"""Local PDF text extraction with page-level Chinese/English OCR fallback."""
from contextlib import closing
from pathlib import Path
import os
import json
import shutil
import subprocess
import tempfile
import threading
import time

import pypdfium2 as pdfium
from cortexa.data import document_preview as previews

_ocr_slot = threading.Semaphore(1)


def extract_image(path):
    """Recognize the first displayed frame, preserving transparency and orientation."""
    from PIL import Image, ImageOps

    with Image.open(path) as source, ImageOps.exif_transpose(source) as oriented:
        with oriented.convert('RGBA') as rgba, Image.new('RGBA', oriented.size, 'white') as background:
            background.alpha_composite(rgba)
            with background.convert('RGB') as image:
                text = recognize_image(image).strip()
    if not text or not any(character.isalnum() for character in text):
        raise RuntimeError('未识别到文字，请上传清晰的文字图片，或手动填写摘要')
    return text, 1


def recognize_image(image):
    executable = os.getenv('TESSERACT_BIN') or ('/opt/agentdevstu/ocr-runtime/bin/tesseract' if Path('/opt/agentdevstu/ocr-runtime/bin/tesseract').exists() else shutil.which('tesseract'))
    if not executable:
        raise RuntimeError('OCR 服务未安装')
    environment = {**os.environ, 'OMP_THREAD_LIMIT': '1'}
    language_dir = Path(executable).parent.parent / 'share' / 'tessdata'
    if language_dir.is_dir():
        environment['TESSDATA_PREFIX'] = str(language_dir)
    with _ocr_slot, tempfile.TemporaryDirectory(prefix='knowledge-ocr-') as directory:
        path = Path(directory) / 'page.png'
        image.save(path)
        result = subprocess.run([executable, str(path), str(Path(directory) / 'text'), '-l', 'chi_sim+eng'],
                                capture_output=True, timeout=180, env=environment)
        if result.returncode:
            raise RuntimeError('OCR 识别失败，请重试')
        return (Path(directory) / 'text.txt').read_text(encoding='utf-8').strip()


def extract_pdf(path, progress=None):
    deadline = time.monotonic() + 1800
    # Release PDFium's global lock while OCR runs so previews remain responsive.
    with previews._pdf_lock:
        pdf = pdfium.PdfDocument(path)
        count = len(pdf)
    pages, ocr_pages = [], 0
    cache = Path(path).parent / 'preview' / 'ocr-v1' if isinstance(path, (str, Path)) else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    try:
        for index in range(count):
            if time.monotonic() > deadline:
                raise TimeoutError('PDF 识别超过 30 分钟，已保存页面进度，请重试继续')
            cached = cache / f'{index + 1}.json' if cache else None
            if cached and cached.exists():
                saved = json.loads(cached.read_text())
                pages.append(saved['text'])
                ocr_pages += int(saved['ocr'])
                if progress:
                    progress(index + 1, count)
                continue
            image = None
            with previews._pdf_lock, closing(pdf[index]) as page:
                with closing(page.get_textpage()) as textpage:
                    text = textpage.get_text_bounded().strip()
                # Sparse text layers (e.g. page numbers over scanned pages) need OCR too.
                if sum(c.isalnum() for c in text) < 30:
                    scale = min(2, 2200 / max(page.get_size()))
                    with closing(page.render(scale=scale)) as bitmap:
                        image = bitmap.to_pil().copy()
            if image is not None:
                try:
                    recognized = recognize_image(image)
                    if len(recognized) > len(text):
                        text = recognized
                    ocr_pages += 1
                finally:
                    image.close()
            if cached:
                pending = cached.with_suffix('.tmp')
                pending.write_text(json.dumps({'text': text, 'ocr': image is not None}, ensure_ascii=False), encoding='utf-8')
                pending.replace(cached)
            pages.append(text)
            if progress:
                progress(index + 1, count)
    finally:
        with previews._pdf_lock:
            pdf.close()
    if not any(page.strip() for page in pages):
        raise RuntimeError('未识别到文字，请检查扫描清晰度或文件是否为空白')
    return '\n\n'.join(f'【第 {i + 1} 页】\n{text}' for i, text in enumerate(pages)), ocr_pages
