"""Back up and repair legacy encoded summaries without changing the schema."""
import argparse
import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from cortexa.api import knowledge
from cortexa.data import document_preview as previews
from cortexa.data.doc_storage import save_document_content
from cortexa.db.engine import async_session_factory
from cortexa.db.models import Document


async def main(apply=False):
    backup = Path('data/repair-backups') / ('binary-summary-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    queued = []
    async with async_session_factory() as session:
        docs = list((await session.execute(select(Document).where(
            Document.status == 'active', Document.metadata_json['encoding'].as_string() == 'base64'
        ).order_by(Document.created_at))).scalars().all())
        for doc in docs:
            metadata = doc.metadata_json or {}
            kind = previews.file_kind(doc.name, metadata)
            known_summary = metadata.get('summary_source') in {'manual', 'llm', 'full'}
            print(json.dumps({'id': str(doc.id), 'name': doc.name, 'kind': kind, 'apply': apply}, ensure_ascii=False), flush=True)
            if not apply:
                continue
            await session.refresh(doc, with_for_update=True)
            metadata = doc.metadata_json or {}
            known_summary = metadata.get('summary_source') in {'manual', 'llm', 'full'}
            saved = backup / str(doc.id)
            saved.mkdir(parents=True, exist_ok=False)
            (saved / 'record.json').write_text(json.dumps({'id': str(doc.id), 'content': doc.content, 'metadata_json': metadata}, ensure_ascii=False), encoding='utf-8')
            directory = previews.document_dir(str(doc.id))
            if directory.exists():
                await run_in_threadpool(shutil.copytree, directory, saved / 'files')
            original = await run_in_threadpool(previews.original_file, str(doc.id), doc.name, metadata, doc.content or '')
            if not known_summary:
                doc.content = ''
            # Clear legacy encoded text only after the original has been recovered.
            if original:
                await run_in_threadpool(save_document_content, str(doc.id), '')
            supported = kind != 'text'
            doc.metadata_json = {**metadata,
                'summary_source': metadata.get('summary_source') if known_summary else None,
                'summary_status': 'ready' if known_summary else 'pending' if supported else 'unsupported',
                'index_status': 'pending' if supported else 'unsupported',
                'summary_error': None, 'index_error': None,
                **({'extraction_status': 'pending', 'extraction_error': None} if supported else {})}
            await session.commit()
            if supported:
                queued.append((doc.id, doc.knowledge_base_id))
    if apply:
        print(json.dumps({'backup': str(backup.resolve()), 'queued': len(queued)}), flush=True)
        for doc_id, kb_id in queued:
            await knowledge._process_pdf(doc_id, kb_id)
            async with async_session_factory() as session:
                doc = await session.get(Document, doc_id)
                print(json.dumps({'id': str(doc_id), 'metadata': doc.metadata_json,
                                  'summary_characters': len(doc.content or '')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply repairs; default only lists candidates')
    asyncio.run(main(parser.parse_args().apply))
