-- Migration: Add parent-child document retrieval fields to DocumentChunk
-- Run: psql -h 47.97.82.200 -U agentdevstu -d agentdevstu -f migrations/add_parent_child_fields.sql

-- Add parent_chunk_id column for parent-child document retrieval
ALTER TABLE t_document_chunks
ADD COLUMN IF NOT EXISTS parent_chunk_id UUID
    REFERENCES t_document_chunks(id) ON DELETE SET NULL;

-- Add is_parent flag to distinguish parent vs child chunks
ALTER TABLE t_document_chunks
ADD COLUMN IF NOT EXISTS is_parent BOOLEAN DEFAULT FALSE;

-- Index for efficient parent-child lookups
CREATE INDEX IF NOT EXISTS idx_chunks_parent_id
    ON t_document_chunks(parent_chunk_id)
    WHERE parent_chunk_id IS NOT NULL;

-- Index for filtering parent vs child chunks
CREATE INDEX IF NOT EXISTS idx_chunks_is_parent
    ON t_document_chunks(is_parent);
