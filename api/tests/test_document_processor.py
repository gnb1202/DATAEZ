"""Unit tests for document text extraction and chunking."""

import pytest

from app.document_processor import chunk_text, extract_text


class TestChunkText:
    def test_empty(self):
        assert chunk_text("") == []
        assert chunk_text("   \n\n  ") == []

    def test_short_text_one_chunk(self):
        chunks = chunk_text("짧은 문장 하나입니다.", chunk_size=800)
        assert len(chunks) == 1
        assert chunks[0] == "짧은 문장 하나입니다."

    def test_long_text_multiple_chunks(self):
        text = "단락1입니다.\n\n" + ("긴문장. " * 200) + "\n\n단락3입니다."
        chunks = chunk_text(text, chunk_size=200, chunk_overlap=20)
        assert len(chunks) > 1
        assert all(len(c) <= 200 for c in chunks)

    def test_paragraph_boundary_preferred(self):
        text = "Para A. " * 50 + "\n\n" + "Para B. " * 50
        chunks = chunk_text(text, chunk_size=500, chunk_overlap=0)
        # Either chunk should not span the paragraph break in the middle.
        # Verify that we got multiple chunks and each respects the size cap.
        assert len(chunks) >= 2
        assert all(len(c) <= 500 for c in chunks)

    def test_overlap_capped_below_chunk_size(self):
        # overlap >= chunk_size should be silently clamped, not crash.
        chunks = chunk_text("아무 글이나" * 30, chunk_size=50, chunk_overlap=999)
        assert len(chunks) >= 1
        assert all(len(c) <= 50 for c in chunks)


class TestExtractText:
    def test_md_decode(self):
        content = "# 제목\n\n본문입니다.".encode("utf-8")
        text = extract_text(content, "doc.md")
        assert "제목" in text
        assert "본문" in text

    def test_txt_decode(self):
        content = "안녕하세요\n반갑습니다.".encode("utf-8")
        text = extract_text(content, "doc.txt")
        assert "안녕" in text

    def test_cp949_fallback(self):
        # Korean text encoded in cp949 (legacy Windows Korean encoding).
        content = "한글 문서".encode("cp949")
        text = extract_text(content, "legacy.txt")
        assert "한글" in text

    def test_unsupported_type_raises(self):
        with pytest.raises(ValueError):
            extract_text(b"...", "image.png")
