"""Migrate existing document content from DB to filesystem."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from sqlalchemy import select
from cortexa.db.engine import async_session_factory
from cortexa.db.models import Document
from cortexa.data.doc_storage import save_document_content, make_summary


async def migrate():
    async with async_session_factory() as db:
        result = await db.execute(select(Document))
        docs = list(result.scalars().all())
        print(f"Found {len(docs)} documents to migrate")

        for doc in docs:
            if doc.content and len(doc.content) > 2000:
                save_document_content(str(doc.id), doc.content)
                doc.content = make_summary(doc.content)
                print(f"  Migrated: {doc.name} ({len(doc.content)} chars -> summary)")
            else:
                if doc.content:
                    save_document_content(str(doc.id), doc.content)
                print(f"  Saved: {doc.name} (small content)")

        await db.commit()
        print("Migration complete!")


if __name__ == "__main__":
    asyncio.run(migrate())
