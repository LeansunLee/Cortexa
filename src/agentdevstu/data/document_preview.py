"""Original files and cached, on-demand page previews; no database schema changes."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import shutil
import tempfile
import threading
from contextlib import closing
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps

from agentdevstu.data.doc_storage import DOC_STORAGE_DIR, load_document_content

OFFICE_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico"}
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".py",
    ".sql",
    ".ini",
    ".svg",
}
TEXT_PAGE_SIZE = 12000
MAX_UPLOAD_SIZE = 500 * 1024 * 1024
_pdf_lock = threading.RLock()  # PDFium must not be called concurrently from multiple threads.
_conversion_slots = asyncio.Semaphore(1)
_jobs: dict[str, asyncio.Task] = {}


class PreviewError(Exception):
    pass


def document_dir(doc_id: str) -> Path:
    return Path(DOC_STORAGE_DIR) / doc_id


def save_original(doc_id: str, raw: bytes) -> Path:
    path = document_dir(doc_id) / "original"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def original_file(doc_id: str, name: str, metadata: dict, fallback: str = "") -> Path | None:
    """Recover old lossless uploads, but never pretend extracted PDF text is a PDF."""
    path = document_dir(doc_id) / "original"
    if metadata.get("content_revision") and file_kind(name, metadata) == "text":
        edited = document_dir(doc_id) / "content.txt"
        return edited if edited.exists() else None
    if path.exists():
        return path
    content = load_document_content(doc_id)
    if content is None:
        # Document.content normally holds a summary, not a recoverable original.
        content = fallback if metadata.get("summary_source") == "full" or metadata.get("encoding") == "base64" else None
    if not content or "...[全文已存储到文件系统]" in content:
        return None
    binary = metadata.get("encoding") == "base64" or content.startswith("JVBER")
    try:
        if binary:
            raw = base64.b64decode(content, validate=True)
        elif Path(name).suffix.lower() in OFFICE_EXTENSIONS | IMAGE_EXTENSIONS | {".pdf"}:
            return None
        else:
            raw = content.encode("utf-8")
    except (ValueError, UnicodeError):
        return None
    return save_original(doc_id, raw)


def decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def extract_pdf_text(raw: bytes) -> str:
    with _pdf_lock, closing(pdfium.PdfDocument(raw)) as pdf:
        texts = []
        for index in range(len(pdf)):
            with closing(pdf[index]) as page, closing(page.get_textpage()) as textpage:
                texts.append(textpage.get_text_bounded())
        return "\n\n".join(texts)


def file_kind(name: str, metadata: dict) -> str:
    ext = Path(name).suffix.lower()
    mime = metadata.get("content_type", "")
    if ext == ".pdf" or mime == "application/pdf":
        return "pdf"
    if ext in OFFICE_EXTENSIONS:
        return "office"
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return "image"
    if mime.startswith("text/") or mime in {"application/json", "application/xml"}:
        return "text"
    return "unsupported"


def text_content(doc_id: str, name: str, metadata: dict, fallback: str) -> str:
    if file_kind(name, metadata) == "text":
        path = original_file(doc_id, name, metadata, fallback)
        if path:
            return decode_text(path.read_bytes())
    content = load_document_content(doc_id)
    if content is not None and metadata.get('encoding') != 'base64':
        return content
    if metadata.get("summary_source") == "full" and metadata.get("encoding") != "base64":
        return fallback
    raise PreviewError("原文件及完整正文缺失，请重新上传；摘要可通过“摘要”按钮查看")


def pdf_file(doc_id: str, kind: str) -> Path:
    return document_dir(doc_id) / ("preview/document.pdf" if kind == "office" else "original")


def page_count(path: Path, kind: str) -> int:
    if kind in {"pdf", "office"}:
        with _pdf_lock, closing(pdfium.PdfDocument(path)) as pdf:
            return len(pdf)
    with Image.open(path) as img:
        return getattr(img, "n_frames", 1)


async def _convert_office(doc_id: str, name: str) -> None:
    root = document_dir(doc_id)
    try:
        async with _conversion_slots:
            original = root / "original"
            if not original.exists():
                return
            executable = os.getenv("LIBREOFFICE_BIN") or shutil.which("libreoffice") or shutil.which("soffice")
            if not executable:
                raise PreviewError("Office 预览服务尚未安装，请联系管理员")
            # Private profile prevents concurrent instances and disables document macros.
            with tempfile.TemporaryDirectory(prefix="kb-office-") as temp:
                work = Path(temp)
                profile = work / "profile"
                (profile / "user").mkdir(parents=True)
                (profile / "user/registrymodifications.xcu").write_text(
                    '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
                    '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
                    '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
                    "</item></oor:items>",
                    encoding="utf-8",
                )
                source = work / ("source" + Path(name).suffix.lower())
                shutil.copyfile(original, source)
                process = await asyncio.create_subprocess_exec(
                    executable,
                    f"-env:UserInstallation={profile.as_uri()}",
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--nofirststartwizard",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(work),
                    str(source),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(process.wait(), timeout=120)
                except (TimeoutError, asyncio.CancelledError):
                    process.kill()
                    await process.wait()
                    raise PreviewError("Office 转换超时，请重试或下载原文件查看") from None
                output = work / "source.pdf"
                if process.returncode != 0 or not output.exists():
                    raise PreviewError("无法转换该 Office 文件，请检查文件是否损坏或受密码保护")
                if not original.exists():
                    return  # Document was deleted during conversion.
                target = root / "preview/document.pdf"
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(output, target.with_suffix(".tmp"))
                target.with_suffix(".tmp").replace(target)
    except Exception as error:
        if root.exists():
            (root / "preview-error.json").write_text(
                json.dumps({"message": str(error)}, ensure_ascii=False), encoding="utf-8"
            )
    finally:
        _jobs.pop(doc_id, None)


def preview_info(doc_id: str, name: str, metadata: dict, fallback: str) -> dict:
    """Fast metadata preparation. Office conversion is scheduled by the async caller."""
    kind = file_kind(name, metadata)
    original = original_file(doc_id, name, metadata, fallback)
    result = {
        "kind": kind,
        "status": "ready",
        "page_count": 1,
        "message": "",
        "download_available": original is not None,
    }
    if kind == "unsupported":
        return {**result, "status": "unsupported", "message": "该格式暂不支持在线预览，可下载原文件查看"}
    if kind == "office" and original:
        error_file = document_dir(doc_id) / "preview-error.json"
        if not pdf_file(doc_id, kind).exists():
            if error_file.exists():
                return {**result, "status": "error", "message": json.loads(error_file.read_text())["message"]}
            return {**result, "status": "processing", "page_count": 0, "message": "正在生成分页预览，首次打开需要稍等…"}
    if kind in {"pdf", "office", "image"} and not original:
        # Historical PDF uploads sometimes contain only extracted text.
        if kind == "pdf" and metadata.get("encoding") != "base64" and (
            load_document_content(doc_id) is not None or metadata.get("summary_source") == "full"
        ):
            kind = "text"
            result.update(kind=kind, message="此历史文件仅保存了提取文本；重新上传后可查看原版分页预览")
        else:
            return {**result, "status": "unsupported", "message": "历史文件的原文件缺失，请重新上传以启用预览"}
    try:
        if kind == "text":
            result["page_count"] = max(
                1, math.ceil(len(text_content(doc_id, name, metadata, fallback)) / TEXT_PAGE_SIZE)
            )
        else:
            result["page_count"] = page_count(pdf_file(doc_id, kind) if kind in {"pdf", "office"} else original, kind)
    except PreviewError as error:
        return {**result, "status": "unsupported", "message": str(error)}
    except Exception:
        return {**result, "status": "error", "message": "无法读取文件，请检查文件是否损坏或受密码保护"}
    return result


def start_office_preview(doc_id: str, name: str) -> None:
    if doc_id not in _jobs:
        _jobs[doc_id] = asyncio.create_task(_convert_office(doc_id, name))


def render_page(doc_id: str, kind: str, page_number: int) -> Path:
    """Rasterize only the requested page; subsequent requests reuse the disk cache."""
    root = document_dir(doc_id)
    target = root / "preview" / f"{kind}-{page_number}.png"
    # Serialize PDFium and duplicate page renders, while keeping them off the event loop.
    with _pdf_lock:
        if target.exists():
            return target
        if kind in {"pdf", "office"}:
            with closing(pdfium.PdfDocument(pdf_file(doc_id, kind))) as pdf:
                if not 1 <= page_number <= len(pdf):
                    raise IndexError("Page out of range")
                with closing(pdf[page_number - 1]) as page:
                    width, height = page.get_size()
                    scale = min(2, 1600 / max(width, height))
                    bitmap = page.render(scale=scale)
                    try:
                        image = bitmap.to_pil().copy()
                    finally:
                        bitmap.close()
        else:
            with Image.open(root / "original") as source:
                if not 1 <= page_number <= getattr(source, "n_frames", 1):
                    raise IndexError("Page out of range")
                source.seek(page_number - 1)
                image = ImageOps.exif_transpose(source).convert("RGBA")
                image.thumbnail((1600, 1600))
        try:
            # Never recreate a deleted document's directory.
            target.parent.mkdir(exist_ok=True)
            image.save(target.with_suffix(".tmp"), format="PNG")
            target.with_suffix(".tmp").replace(target)
        finally:
            image.close()
    return target
