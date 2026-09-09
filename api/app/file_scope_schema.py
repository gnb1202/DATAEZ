"""Immutable, owner-scoped analysis copies of retained file rows."""

DDL = """
ALTER TABLE table_meta ADD COLUMN IF NOT EXISTS original_file_id UUID REFERENCES files(id);
ALTER TABLE table_meta ADD COLUMN IF NOT EXISTS original_content_hash CHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_original_file_analysis
    ON table_meta(user_id,project_id,original_file_id) WHERE original_file_id IS NOT NULL;
CREATE OR REPLACE FUNCTION reject_original_file_write() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Original file analysis rows are read-only' USING ERRCODE='55000';
END $$;
"""
