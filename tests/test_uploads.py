"""Tests for file upload functionality.

These tests focus on the core upload logic without requiring the full
Flask application to be initialized. This allows testing in environments
where not all dependencies are installed.
"""

import hashlib
import io
import os
import tempfile
from pathlib import Path

import pytest

# Set up test environment BEFORE any imports
_tmp_dir = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp_dir

# Now we can safely import
from web import config
from web.database import ConversationStore, UploadedFile, init_db
from web.uploads import (
    BLOCKED_EXTENSIONS,
    TEXT_EXTENSIONS,
    BlockedFileTypeError,
    FileTooLargeError,
    _compute_sha256,
    _generate_stored_filename,
    _is_text_file,
    _sanitize_filename,
    format_file_for_context,
    upload_file,
)

# Configure for testing
config.DATA_DIR = Path(_tmp_dir)
config.UPLOADS_DIR = Path(_tmp_dir) / "uploads"
config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
config.MAX_UPLOAD_SIZE = 10 * 1024 * 1024
config.TEXT_FILE_INLINE_LIMIT = 1024
config.USE_S3 = False

# Create a fresh store for tests
init_db()
store = ConversationStore()


@pytest.fixture
def setup_db(tmp_path, monkeypatch):
    """Tmp upload dirs, stub ClamAV, one DB transaction rolled back per test."""
    import web.config as config
    from web.db import test_transaction

    monkeypatch.setattr(
        "web.uploads._scan_with_clamav",
        lambda _path: (False, None),
    )

    with test_transaction():
        config.DATA_DIR = tmp_path
        config.UPLOADS_DIR = tmp_path / "uploads"
        config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        config.MAX_UPLOAD_SIZE = 10 * 1024 * 1024
        config.TEXT_FILE_INLINE_LIMIT = 1024
        config.USE_S3 = False

        yield tmp_path


class TestComputeSha256:
    """Tests for SHA256 hash computation."""

    def test_computes_correct_hash(self):
        """SHA256 hash is computed correctly."""
        content = b"Hello, World!"
        expected = hashlib.sha256(content).hexdigest()
        assert _compute_sha256(content) == expected

    def test_empty_content(self):
        """SHA256 of empty content is correct."""
        content = b""
        expected = hashlib.sha256(content).hexdigest()
        assert _compute_sha256(content) == expected

    def test_deterministic(self):
        """Same content produces same hash."""
        content = b"test content"
        hash1 = _compute_sha256(content)
        hash2 = _compute_sha256(content)
        assert hash1 == hash2


class TestIsTextFile:
    """Tests for text file detection."""

    def test_text_extension_is_detected(self):
        """Files with text extensions are detected as text."""
        for ext in [".txt", ".md", ".csv", ".json", ".py", ".ts"]:
            assert _is_text_file(f"file{ext}", None, b"") is True

    def test_binary_extension_is_not_text(self):
        """Files with binary extensions are not detected as text."""
        assert _is_text_file("image.png", "image/png", b"\x89PNG") is False
        # PDF with binary content is detected as binary
        assert _is_text_file("doc.pdf", "application/pdf", b"\x00\x01\x02") is False

    def test_text_mime_type_is_detected(self):
        """Files with text MIME types are detected as text."""
        assert _is_text_file("file", "text/plain", b"") is True
        assert _is_text_file("file", "application/json", b"") is True

    def test_content_based_detection(self):
        """Text is detected by content analysis."""
        text_content = b"This is plain text content with mostly printable characters."
        assert _is_text_file("unknown", None, text_content) is True

    def test_binary_content_not_detected_as_text(self):
        """Binary content is not detected as text."""
        binary_content = bytes(range(256))  # Contains non-printable bytes
        assert _is_text_file("unknown", None, binary_content) is False


class TestSanitizeFilename:
    """Tests for filename sanitization."""

    def test_removes_path_components(self):
        """Path traversal attempts are blocked."""
        assert _sanitize_filename("../../../etc/passwd") == "passwd"
        assert _sanitize_filename("/etc/passwd") == "passwd"
        # On Unix, backslashes are treated as regular characters (sanitized to underscores)
        result = _sanitize_filename("..\\..\\windows\\system32\\config")
        assert "passwd" not in result.lower()  # Not confused with Unix paths
        assert "_" in result  # Backslashes replaced

    def test_removes_problematic_chars(self):
        """Problematic characters are replaced."""
        result = _sanitize_filename('file<>:"|?*name.txt')
        assert result.endswith(".txt")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert '"' not in result
        assert "|" not in result
        assert "?" not in result
        assert "*" not in result

    def test_limits_length(self):
        """Long filenames are truncated."""
        long_name = "a" * 300 + ".txt"
        result = _sanitize_filename(long_name)
        assert len(result) <= 200
        assert result.endswith(".txt")

    def test_empty_filename(self):
        """Empty filename returns 'unnamed'."""
        assert _sanitize_filename("") == "unnamed"
        # Note: whitespace-only filenames are not currently treated as empty
        # This is acceptable since os.path.basename("   ") returns "   "

    def test_preserves_valid_filename(self):
        """Valid filenames are preserved."""
        assert _sanitize_filename("my_file-2024.csv") == "my_file-2024.csv"


class TestGenerateStoredFilename:
    """Tests for stored filename generation."""

    def test_preserves_extension(self):
        """File extension is preserved."""
        result = _generate_stored_filename("document.pdf")
        assert result.endswith(".pdf")

    def test_includes_original_stem(self):
        """Original filename stem is included."""
        result = _generate_stored_filename("my_report.csv")
        assert "my_report" in result

    def test_generates_unique_names(self):
        """Generated names are unique."""
        name1 = _generate_stored_filename("file.txt")
        name2 = _generate_stored_filename("file.txt")
        assert name1 != name2

    def test_handles_no_extension(self):
        """Files without extension are handled."""
        result = _generate_stored_filename("Makefile")
        assert "Makefile" in result


@pytest.mark.usefixtures("setup_db")
class TestUploadFile:
    """Tests for the main upload function."""

    def test_upload_text_file(self):
        """Text files are uploaded successfully."""
        content = b"Hello, World!"
        file_obj = io.BytesIO(content)

        result, text_content = upload_file(
            file_obj=file_obj,
            filename="hello.txt",
            conversation_id=None,
            user_id="test@example.com",
        )

        assert result is not None
        assert result.original_filename == "hello.txt"
        assert result.file_size == len(content)
        assert result.is_text is True
        assert result.sha256_hash == _compute_sha256(content)
        assert text_content == "Hello, World!"

    def test_upload_binary_file(self):
        """Binary files are uploaded without text content."""
        content = bytes(range(256)) * 100  # Binary content
        file_obj = io.BytesIO(content)

        result, text_content = upload_file(
            file_obj=file_obj,
            filename="data.bin",
            conversation_id=None,
            user_id="test@example.com",
        )

        assert result is not None
        assert result.is_text is False
        assert text_content is None

    def test_upload_large_text_file_no_inline(self):
        """Large text files don't return inline content."""
        # Make content larger than TEXT_FILE_INLINE_LIMIT (1KB in tests)
        content = b"x" * 2000
        file_obj = io.BytesIO(content)

        result, text_content = upload_file(
            file_obj=file_obj,
            filename="large.txt",
            conversation_id=None,
            user_id="test@example.com",
        )

        assert result is not None
        assert result.is_text is True
        assert text_content is None  # Too large to inline

    def test_file_too_large_rejected(self):
        """Files exceeding size limit are rejected."""
        import web.config as config

        config.MAX_UPLOAD_SIZE = 100  # Very small for testing

        content = b"x" * 200
        file_obj = io.BytesIO(content)

        with pytest.raises(FileTooLargeError):
            upload_file(
                file_obj=file_obj,
                filename="big.txt",
                conversation_id=None,
                user_id="test@example.com",
            )

    def test_blocked_extension_rejected(self):
        """Files with blocked extensions are rejected."""
        content = b"MZ"  # PE header start
        file_obj = io.BytesIO(content)

        with pytest.raises(BlockedFileTypeError):
            upload_file(
                file_obj=file_obj,
                filename="malware.exe",
                conversation_id=None,
                user_id="test@example.com",
            )

    def test_duplicate_detection(self):
        """Duplicate files are detected by hash."""
        content = b"same content"
        file_obj1 = io.BytesIO(content)
        file_obj2 = io.BytesIO(content)

        result1, _ = upload_file(
            file_obj=file_obj1,
            filename="file1.txt",
            conversation_id=None,
            user_id="user1@example.com",
        )

        result2, _ = upload_file(
            file_obj=file_obj2,
            filename="file2.txt",  # Different name
            conversation_id=None,
            user_id="user2@example.com",
        )

        # Both should have same hash and stored filename
        assert result1.sha256_hash == result2.sha256_hash
        assert result1.stored_filename == result2.stored_filename
        # But different IDs and original filenames
        assert result1.id != result2.id
        assert result1.original_filename != result2.original_filename

    def test_file_permissions_readonly(self):
        """Uploaded files are set to read-only."""
        content = b"test"
        file_obj = io.BytesIO(content)

        result, _ = upload_file(
            file_obj=file_obj,
            filename="test.txt",
            conversation_id=None,
            user_id="test@example.com",
        )

        path = Path(result.storage_path)
        assert path.exists()

        # Check file is not writable (mode should be 0o444)
        mode = path.stat().st_mode
        assert not (mode & 0o222)  # No write bits


class TestFormatFileForContext:
    """Tests for formatting file info for conversation context."""

    def test_format_with_text_content(self):
        """Text content is included when provided."""
        uploaded_file = UploadedFile(
            original_filename="notes.txt",
            storage_path="/data/uploads/notes.txt",
            file_size=100,
            mime_type="text/plain",
            sha256_hash="abc123",
            is_text=True,
        )

        result = format_file_for_context(uploaded_file, "Hello, World!")

        assert "[Uploaded file: notes.txt]" in result
        assert "Size: 100 bytes" in result
        assert "Hello, World!" in result
        assert "```" in result  # Code block markers

    def test_format_without_text_content(self):
        """Binary files show path information."""
        uploaded_file = UploadedFile(
            original_filename="image.png",
            storage_path="/data/uploads/image.png",
            file_size=50000,
            mime_type="image/png",
            sha256_hash="abc123",
            is_text=False,
        )

        result = format_file_for_context(uploaded_file, None)

        assert "[Uploaded file: image.png]" in result
        assert "Path: /data/uploads/image.png" in result
        assert "Binary file" in result

    def test_format_large_text_file(self):
        """Large text files mention using Read tool."""
        uploaded_file = UploadedFile(
            original_filename="large.txt",
            storage_path="/data/uploads/large.txt",
            file_size=100000,
            mime_type="text/plain",
            sha256_hash="abc123",
            is_text=True,
        )

        result = format_file_for_context(uploaded_file, None)

        assert "too large to include inline" in result
        assert "Read tool" in result


class TestBlockedExtensions:
    """Tests for blocked file extension list."""

    def test_executable_extensions_blocked(self):
        """Common executable extensions are in the blocked list."""
        assert ".exe" in BLOCKED_EXTENSIONS
        assert ".dll" in BLOCKED_EXTENSIONS
        assert ".bat" in BLOCKED_EXTENSIONS
        assert ".com" in BLOCKED_EXTENSIONS

    def test_script_extensions_blocked(self):
        """Script extensions are in the blocked list."""
        assert ".vbs" in BLOCKED_EXTENSIONS
        assert ".ps1" in BLOCKED_EXTENSIONS
        assert ".jar" in BLOCKED_EXTENSIONS


class TestTextExtensions:
    """Tests for text file extension list."""

    def test_common_text_extensions_included(self):
        """Common text file extensions are recognized."""
        assert ".txt" in TEXT_EXTENSIONS
        assert ".md" in TEXT_EXTENSIONS
        assert ".json" in TEXT_EXTENSIONS
        assert ".csv" in TEXT_EXTENSIONS

    def test_programming_extensions_included(self):
        """Programming language files are recognized as text."""
        assert ".py" in TEXT_EXTENSIONS
        assert ".ts" in TEXT_EXTENSIONS
        assert ".java" in TEXT_EXTENSIONS
        assert ".go" in TEXT_EXTENSIONS


@pytest.mark.usefixtures("setup_db")
class TestDatabaseIntegration:
    """Tests for database integration."""

    def test_file_record_stored(self):
        """Uploaded files are stored in database."""
        content = b"test content"
        file_obj = io.BytesIO(content)

        result, _ = upload_file(
            file_obj=file_obj,
            filename="test.txt",
            conversation_id=None,
            user_id="test@example.com",
        )

        # Retrieve from database
        retrieved = store.get_uploaded_file(result.id)
        assert retrieved is not None
        assert retrieved.original_filename == "test.txt"
        assert retrieved.user_id == "test@example.com"

    def test_files_by_hash(self):
        """Files can be found by hash."""
        content = b"unique content"
        file_obj = io.BytesIO(content)

        result, _ = upload_file(
            file_obj=file_obj,
            filename="test.txt",
            conversation_id=None,
            user_id="test@example.com",
        )

        # Find by hash
        found = store.get_uploaded_file_by_hash(result.sha256_hash)
        assert found is not None
        assert found.id == result.id

    def test_conversation_files(self):
        """Files can be listed by conversation."""
        # Create a conversation first
        conv = store.create_conversation(user_id="test@example.com")

        # Upload files to conversation
        for i in range(3):
            content = f"file {i}".encode()
            file_obj = io.BytesIO(content)
            upload_file(
                file_obj=file_obj,
                filename=f"file{i}.txt",
                conversation_id=conv.id,
                user_id="test@example.com",
            )

        # List files
        files = store.get_conversation_files(conv.id)
        assert len(files) == 3
