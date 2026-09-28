"""Repair existing summaries and indexes without changing the schema."""
import argparse
import asyncio
import json

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from cortexa.api import knowledge
from cortexa.data import document_preview as previews
from cortexa.data.doc_storage import load_document_content, save_document_content
from cortexa.db.engine import async_session_factory
from cortexa.db.models import Document


def needs_repair(doc, force=False):
    metadata = doc.metadata_json or {}
    if previews.file_kind(doc.name, metadata) != 'pdf' and metadata.get('encoding') == 'base64':
        return False
    return (force or metadata.get('index_status') != 'ready'
            or metadata.get('summary_status') != 'ready'
            or not metadata.get('summary_source')
            or (previews.file_kind(doc.name, metadata) == 'pdf' and metadata.get('extraction_status') != 'ready'))


async def main(dry_run=False, limit=None, force=False):
    async with async_session_factory() as session:
        docs = list((await session.execute(select(Document).where(Document.status == 'active')
                                           .order_by(Document.created_at))).scalars().all())
    candidates = [doc for doc in docs if needs_repair(doc, force)]
    if limit is not None:
        candidates = candidates[:limit]
    counts = {'candidates': len(candidates), 'ready': 0, 'error': 0}
    for doc in candidates:
        print(json.dumps({'id': str(doc.id), 'name': doc.name, 'dry_run': dry_run}, ensure_ascii=False), flush=True)
        if dry_run:
            continue
        try:
            async with async_session_factory() as session:
                current = await session.get(Document, doc.id)
                if not current:
                    continue
                metadata = current.metadata_json or {}
                content = await run_in_threadpool(load_document_content, str(doc.id))
                pdf = previews.file_kind(current.name, metadata) == 'pdf'
                if force and metadata.get('summary_source') == 'manual':
                    metadata = {**metadata, 'summary_source': 'truncated'}
                if pdf and (not content or metadata.get('encoding') == 'base64'
                            or metadata.get('extraction_status') != 'ready'):
                    current.metadata_json = {**metadata, 'extraction_status': 'pending'}
                else:
                    if content is None:
                        original = await run_in_threadpool(previews.original_file, str(doc.id), current.name, metadata, '')
                        if original and previews.file_kind(current.name, metadata) == 'text':
                            content = await run_in_threadpool(lambda: previews.decode_text(original.read_bytes()))
                        elif not metadata.get('has_full_content'):
                            content = current.content
                        if content:
                            await run_in_threadpool(save_document_content, str(doc.id), content)
                    if not content or not content.strip():
                        raise RuntimeError('Full text missing; summary was not used as a replacement')
                    current.metadata_json = {**metadata, 'index_status': 'pending',
                                             'summary_status': 'ready' if metadata.get('summary_source') == 'manual' else 'pending'}
                await session.commit()
                extraction = (current.metadata_json or {}).get('extraction_status')
            if pdf and extraction == 'pending':
                await knowledge._process_pdf(doc.id, doc.knowledge_base_id)
            else:
                await knowledge._summarize_document(doc.id)
                await knowledge._safe_index(doc.id, doc.knowledge_base_id)
            async with async_session_factory() as session:
                current = await session.get(Document, doc.id)
                metadata = current.metadata_json if current else {}
                ok = metadata.get('summary_status') == 'ready' and metadata.get('index_status') == 'ready'
                counts['ready' if ok else 'error'] += 1
                print(json.dumps({'id': str(doc.id), 'ready': ok, 'metadata': metadata}, ensure_ascii=False), flush=True)
        except Exception as error:
            counts['error'] += 1
            print(json.dumps({'id': str(doc.id), 'error': str(error)}, ensure_ascii=False), flush=True)
    print(json.dumps(counts), flush=True)
    return counts['error']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true', help='Explicitly replace even manual summaries')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    raise SystemExit(1 if asyncio.run(main(args.dry_run, args.limit, args.force)) else 0)
