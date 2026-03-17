"""Tests for cron delta upload optimization."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from web.cron import _prepare_s3_workdir, _upload_s3_results


@patch("web.s3.list_files")
@patch("web.s3.download_file")
def test_prepare_s3_workdir_computes_hashes(mock_download, mock_list):
    """_prepare_s3_workdir should compute MD5 hashes at download time."""
    mock_list.return_value = [
        {"path": "myapp/file1.txt"},
        {"path": "myapp/file2.txt"},
    ]
    mock_download.side_effect = [b"content1", b"content2"]

    workdir, pre_hashes = _prepare_s3_workdir("myapp")

    assert len(pre_hashes) == 2
    assert "file1.txt" in pre_hashes
    assert "file2.txt" in pre_hashes
    # MD5 of "content1"
    assert pre_hashes["file1.txt"] == "7e55db001d319a94b0b713529a756623"


@patch("web.s3.upload_file")
def test_upload_s3_results_skips_unchanged_files(mock_upload):
    """_upload_s3_results should only upload files with changed hashes."""
    workdir = Path(tempfile.mkdtemp())
    (workdir / "unchanged.txt").write_bytes(b"same content")
    (workdir / "changed.txt").write_bytes(b"new content")

    pre_hashes = {
        "unchanged.txt": "793953ee398d864ec40252df9554c3e6",  # MD5 of "same content"
        "changed.txt": "old_hash",  # Different hash
    }

    _upload_s3_results("myapp", workdir, pre_hashes)

    # Should only upload changed.txt
    assert mock_upload.call_count == 1
    mock_upload.assert_called_with("myapp/changed.txt", b"new content")
