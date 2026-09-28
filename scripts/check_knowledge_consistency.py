"""Read-only DB/filesystem consistency audit; never repairs or deletes data."""
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import select, func
from cortexa.db.engine import async_session_factory
from cortexa.db.models import Document, DocumentChunk
from cortexa.data.doc_storage import DOC_STORAGE_DIR


async def main():
    issues = []
    async with async_session_factory() as session:
        docs = list((await session.execute(select(Document))).scalars().all())
        chunk_counts = dict((await session.execute(select(DocumentChunk.document_id, func.count())
                                                   .group_by(DocumentChunk.document_id))).all())
    ids = {str(doc.id) for doc in docs}
    for doc in docs:
        metadata = doc.metadata_json or {}
        root = Path(DOC_STORAGE_DIR) / str(doc.id)
        problems = []
        if not root.is_dir():
            problems.append('directory_missing')
        if metadata.get('has_original') and not (root / 'original').is_file():
            problems.append('original_missing')
        if metadata.get('has_full_content') and (not (root / 'content.txt').is_file() or not (root / 'content.txt').stat().st_size):
            problems.append('full_text_missing_or_empty')
        for job in ('extraction', 'summary', 'index'):
            state = metadata.get(f'{job}_status')
            if state == 'error':
                problems.append(f'{job}_error: {metadata.get(f"{job}_error", "")}')
            if state in {'pending', 'processing'}:
                problems.append(f'{job}_{state}')
        if metadata.get('index_status') == 'ready' and not chunk_counts.get(doc.id):
            problems.append('ready_index_has_no_chunks')
        if metadata.get('summary_status') == 'ready' and not (doc.content or '').strip():
            problems.append('ready_summary_is_empty')
        if problems:
            issues.append({'id': str(doc.id), 'name': doc.name, 'issues': problems})
    for path in Path(DOC_STORAGE_DIR).glob('*'):
        if path.is_dir() and not path.name.startswith('.') and path.name not in ids:
            issues.append({'directory': path.name, 'issues': ['orphan_directory']})
    for doc_id, count in chunk_counts.items():
        if str(doc_id) not in ids:
            issues.append({'id': str(doc_id), 'chunks': count, 'issues': ['orphan_chunks']})
    print(json.dumps({'documents': len(docs), 'issues_count': len(issues), 'issues': issues}, ensure_ascii=False, indent=2))
    return bool(issues)


if __name__ == '__main__':
    raise SystemExit(int(asyncio.run(main())))
