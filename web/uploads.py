"""File upload handling for chat conversations.

Provides secure file upload with:
- Size validation
- MIME type detection
- SHA256 hashing for deduplication
- Text file detection
- AV scanning (via ClamAV when available)
- Read-only, non-executable file storage
- S3 mirroring support
"""

import hashlib
import logging
import mimetypes
import os
import re
import shutil
import stat
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Optional, Tuple

from . import config
from .database import store, UploadedFile

logger = logging.getLogger(__name__)

# Text MIME types that can be read directly
TEXT_MIME_TYPES = {
    "text/plain",
    "text/csv",
    "text/html",
    "text/css",
    "text/javascript",
    "text/markdown",
    "text/xml",
    "text/yaml",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/x-sh",
    "application/sql",
}

# File extensions that are considered text
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".css", ".js", ".ts", ".jsx", ".tsx",
    ".py", ".rb", ".php", ".java", ".c", ".cpp", ".h", ".hpp",
    ".go", ".rs", ".swift", ".kt", ".scala", ".r", ".sql",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".conf", ".ini", ".cfg", ".toml", ".env", ".properties",
    ".log", ".gitignore", ".dockerignore", ".editorconfig",
}

# Dangerous file extensions that should be blocked
BLOCKED_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib",  # Executables
    ".bat", ".cmd", ".com", ".msi",   # Windows executables
    ".scr", ".pif", ".hta", ".cpl",   # Windows script/control panel
    ".vbs", ".vbe", ".js", ".jse", ".ws", ".wsf", ".wsc", ".wsh",  # Windows scripting
    ".ps1", ".psm1", ".psd1",         # PowerShell
    ".jar", ".class",                  # Java
    ".app",                            # macOS application
}


class UploadError(Exception):
    """Base exception for upload errors."""
    pass


class FileTooLargeError(UploadError):
    """File exceeds size limit."""
    pass


class BlockedFileTypeError(UploadError):
    """File type is blocked for security reasons."""
    pass


class AVScanFailedError(UploadError):
    """File failed antivirus scan."""
    pass


def _ensure_uploads_dir() -> Path:
    """Ensure the uploads directory exists with proper permissions."""
    uploads_dir = config.UPLOADS_DIR
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir


def _compute_sha256(content: bytes) -> str:
    """Compute SHA256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def _is_text_file(filename: str, mime_type: Optional[str], content: bytes) -> bool:
    """Determine if a file is a text file that can be read directly."""
    # Check by extension
    ext = Path(filename).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return True

    # Check by MIME type
    if mime_type and mime_type in TEXT_MIME_TYPES:
        return True

    # Try to detect by content (look for high ratio of printable chars)
    if len(content) > 0:
        try:
            # Try decoding as UTF-8
            text = content[:8192].decode("utf-8")
            # Check if mostly printable
            printable = sum(1 for c in text if c.isprintable() or c in "\n\r\t")
            if printable / len(text) > 0.9:
                return True
        except (UnicodeDecodeError, ZeroDivisionError):
            pass

    return False


def _sanitize_filename(filename: str) -> str:
    """Sanitize a filename to prevent path traversal and other issues."""
    # Remove path components
    filename = os.path.basename(filename)
    # Replace problematic characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
    # Limit length
    if len(filename) > 200:
        name, ext = os.path.splitext(filename)
        filename = name[:200 - len(ext)] + ext
    return filename or "unnamed"


def _generate_stored_filename(original_filename: str) -> str:
    """Generate a unique stored filename while preserving extension."""
    ext = Path(original_filename).suffix.lower()
    unique_id = uuid.uuid4().hex[:12]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized = _sanitize_filename(Path(original_filename).stem)[:50]
    return f"{timestamp}_{unique_id}_{sanitized}{ext}"


def _set_readonly_permissions(filepath: Path) -> None:
    """Make a file read-only and non-executable."""
    try:
        # Remove all write and execute permissions, keep only read
        # 0o444 = r--r--r--
        os.chmod(filepath, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError as e:
        logger.warning(f"Failed to set readonly permissions on {filepath}: {e}")


def _scan_with_clamav(filepath: Path) -> Tuple[bool, bool]:
    """
    Scan a file with ClamAV if available.

    Returns:
        Tuple of (scanned: bool, clean: bool)
        - (True, True) = scanned and clean
        - (True, False) = scanned and infected
        - (False, None) = not scanned (ClamAV not available)
    """
    # Check if clamscan is available
    if not shutil.which("clamscan"):
        logger.debug("ClamAV not available, skipping scan")
        return (False, None)

    try:
        result = subprocess.run(
            ["clamscan", "--no-summary", str(filepath)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # Exit code 0 = clean, 1 = infected, 2 = error
        if result.returncode == 0:
            logger.debug(f"ClamAV scan clean: {filepath}")
            return (True, True)
        elif result.returncode == 1:
            logger.warning(f"ClamAV detected threat in {filepath}: {result.stdout}")
            return (True, False)
        else:
            logger.warning(f"ClamAV scan error for {filepath}: {result.stderr}")
            return (False, None)
    except subprocess.TimeoutExpired:
        logger.warning(f"ClamAV scan timed out for {filepath}")
        return (False, None)
    except Exception as e:
        logger.warning(f"ClamAV scan failed for {filepath}: {e}")
        return (False, None)


def _upload_to_s3(relative_path: str, content: bytes, content_type: Optional[str] = None) -> bool:
    """Upload file to S3 if configured."""
    if not config.USE_S3:
        return True  # No S3, local storage is fine

    try:
        from . import s3
        # Use a different prefix for uploads vs interactive
        key = f"uploads/{relative_path}"
        return s3.upload_file(key, content, content_type)
    except Exception as e:
        logger.error(f"S3 upload failed for {relative_path}: {e}")
        return False


def upload_file(
    file_obj: BinaryIO,
    filename: str,
    conversation_id: Optional[str] = None,
    user_id: Optional[str] = None,
    check_duplicate: bool = True,
) -> Tuple[UploadedFile, Optional[str]]:
    """
    Upload a file securely.

    Args:
        file_obj: File-like object with read() method
        filename: Original filename
        conversation_id: Optional conversation to associate with
        user_id: Email of uploading user
        check_duplicate: Whether to check for existing file with same hash

    Returns:
        Tuple of (UploadedFile record, text_content if small text file else None)

    Raises:
        FileTooLargeError: If file exceeds MAX_UPLOAD_SIZE
        BlockedFileTypeError: If file extension is blocked
        AVScanFailedError: If AV scan detects a threat
    """
    # Read file content
    content = file_obj.read()
    file_size = len(content)

    # Check size limit
    if file_size > config.MAX_UPLOAD_SIZE:
        raise FileTooLargeError(
            f"File size {file_size} bytes exceeds limit of {config.MAX_UPLOAD_SIZE} bytes"
        )

    # Check for blocked extensions
    ext = Path(filename).suffix.lower()
    if ext in BLOCKED_EXTENSIONS:
        raise BlockedFileTypeError(f"File type {ext} is not allowed")

    # Compute hash
    sha256_hash = _compute_sha256(content)

    # Check for existing file with same hash (deduplication)
    if check_duplicate:
        existing = store.get_uploaded_file_by_hash(sha256_hash)
        if existing:
            logger.info(f"Found existing file with hash {sha256_hash[:16]}...")
            # Create a new record pointing to the same file
            new_record = store.add_uploaded_file(
                conversation_id=conversation_id,
                user_id=user_id,
                original_filename=_sanitize_filename(filename),
                stored_filename=existing.stored_filename,
                storage_path=existing.storage_path,
                file_size=existing.file_size,
                sha256_hash=sha256_hash,
                mime_type=existing.mime_type,
                is_text=existing.is_text,
                av_scanned=existing.av_scanned,
                av_clean=existing.av_clean,
            )
            # Return text content if it's a small text file
            text_content = None
            if existing.is_text and file_size <= config.TEXT_FILE_INLINE_LIMIT:
                try:
                    text_content = content.decode("utf-8")
                except UnicodeDecodeError:
                    pass
            return new_record, text_content

    # Detect MIME type
    mime_type, _ = mimetypes.guess_type(filename)
    if mime_type is None:
        mime_type = "application/octet-stream"

    # Check if it's a text file
    is_text = _is_text_file(filename, mime_type, content)

    # Generate stored filename and path
    stored_filename = _generate_stored_filename(filename)
    uploads_dir = _ensure_uploads_dir()
    storage_path = uploads_dir / stored_filename

    # Write file
    storage_path.write_bytes(content)

    # Set read-only permissions
    _set_readonly_permissions(storage_path)

    # Run AV scan
    av_scanned, av_clean = _scan_with_clamav(storage_path)

    # If AV scan found a threat, delete the file and raise error
    if av_scanned and av_clean is False:
        try:
            storage_path.unlink()
        except OSError:
            pass
        raise AVScanFailedError("File failed antivirus scan")

    # Upload to S3 if configured
    relative_path = stored_filename
    if not _upload_to_s3(relative_path, content, mime_type):
        logger.warning(f"S3 upload failed for {stored_filename}, keeping local copy")

    # Create database record
    uploaded_file = store.add_uploaded_file(
        conversation_id=conversation_id,
        user_id=user_id,
        original_filename=_sanitize_filename(filename),
        stored_filename=stored_filename,
        storage_path=str(storage_path),
        file_size=file_size,
        sha256_hash=sha256_hash,
        mime_type=mime_type,
        is_text=is_text,
        av_scanned=av_scanned,
        av_clean=av_clean,
    )

    # Return text content if it's a small text file
    text_content = None
    if is_text and file_size <= config.TEXT_FILE_INLINE_LIMIT:
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError:
            pass

    logger.info(
        f"Uploaded file: {filename} -> {stored_filename} "
        f"({file_size} bytes, hash={sha256_hash[:16]}...)"
    )

    return uploaded_file, text_content


def get_file_content(uploaded_file: UploadedFile) -> Optional[bytes]:
    """
    Get the content of an uploaded file.

    Tries local filesystem first, falls back to S3 if configured.
    """
    # Try local path first
    local_path = Path(uploaded_file.storage_path)
    if local_path.exists():
        return local_path.read_bytes()

    # Try S3 if configured
    if config.USE_S3:
        try:
            from . import s3
            key = f"uploads/{uploaded_file.stored_filename}"
            return s3.download_file(key)
        except Exception as e:
            logger.error(f"Failed to download from S3: {e}")

    return None


def copy_file_for_modification(
    uploaded_file: UploadedFile,
    destination_dir: Optional[Path] = None,
    new_filename: Optional[str] = None,
) -> Optional[Path]:
    """
    Create a writable copy of an uploaded file for modification.

    This is used when the user asks the agent to modify a file.
    The original file remains read-only; a copy is made elsewhere.

    Args:
        uploaded_file: The file record to copy
        destination_dir: Where to put the copy (defaults to /data/modified for persistence)
        new_filename: Optional new name for the copy

    Returns:
        Path to the writable copy, or None if copy failed
    """
    content = get_file_content(uploaded_file)
    if content is None:
        logger.error(f"Could not read file {uploaded_file.stored_filename} for copying")
        return None

    # Default destination: /data/modified for persistence across container restarts
    if destination_dir is None:
        destination_dir = config.MODIFIED_DIR

    destination_dir.mkdir(parents=True, exist_ok=True)

    # Generate copy filename
    if new_filename:
        copy_filename = _sanitize_filename(new_filename)
    else:
        stem = Path(uploaded_file.original_filename).stem
        ext = Path(uploaded_file.original_filename).suffix
        copy_filename = f"{stem}_copy_{uuid.uuid4().hex[:8]}{ext}"

    copy_path = destination_dir / copy_filename
    copy_path.write_bytes(content)

    # Make writable (unlike original)
    os.chmod(copy_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    logger.info(f"Created writable copy: {copy_path}")
    return copy_path


def format_file_for_context(uploaded_file: UploadedFile, text_content: Optional[str] = None) -> str:
    """
    Format file information for inclusion in conversation context.

    For small text files, includes the content directly.
    For larger or binary files, provides path and metadata.
    """
    lines = [f"[Uploaded file: {uploaded_file.original_filename}]"]
    lines.append(f"- Size: {uploaded_file.file_size:,} bytes")
    lines.append(f"- Type: {uploaded_file.mime_type or 'unknown'}")
    lines.append(f"- Path: {uploaded_file.storage_path}")

    if text_content:
        lines.append(f"- Content ({len(text_content):,} chars):")
        lines.append("```")
        lines.append(text_content)
        lines.append("```")
    elif uploaded_file.is_text:
        lines.append("- Note: Text file too large to include inline. Use Read tool to access.")
    else:
        lines.append("- Note: Binary file. Use appropriate tools to process.")

    return "\n".join(lines)


def delete_file(uploaded_file: UploadedFile) -> bool:
    """
    Delete an uploaded file from storage.

    Only deletes if no other records reference the same stored file.
    """
    # Check if any other records use this stored file
    # (files with same hash share the same storage)
    from .database import get_db
    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM uploaded_files WHERE stored_filename = ?",
            (uploaded_file.stored_filename,)
        ).fetchone()["cnt"]

    if count > 1:
        # Other records reference this file, just delete the DB record
        store.delete_uploaded_file(uploaded_file.id)
        logger.debug(f"Deleted record {uploaded_file.id}, file still referenced by others")
        return True

    # Delete the actual file
    local_path = Path(uploaded_file.storage_path)
    if local_path.exists():
        try:
            # Need to make writable first to delete
            os.chmod(local_path, stat.S_IWUSR | stat.S_IRUSR)
            local_path.unlink()
            logger.info(f"Deleted file: {local_path}")
        except OSError as e:
            logger.error(f"Failed to delete file {local_path}: {e}")

    # Delete from S3 if configured
    if config.USE_S3:
        try:
            from . import s3
            key = f"uploads/{uploaded_file.stored_filename}"
            s3.delete_file(key)
        except Exception as e:
            logger.error(f"Failed to delete from S3: {e}")

    # Delete DB record
    store.delete_uploaded_file(uploaded_file.id)
    return True
