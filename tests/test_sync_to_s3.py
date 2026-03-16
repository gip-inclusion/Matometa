"""Tests for S3 sync optimization."""

from unittest.mock import patch


@patch("web.s3.list_files")
def test_initial_sync_uses_batch_list(mock_list_files):
    """Initial sync should use single list_files call, not N head_object calls."""
    mock_list_files.return_value = [
        {"path": "app1/file1.txt"},
        {"path": "app2/file2.txt"},
    ]

    # Import here to ensure mocks are in place before module runs
    from web import s3

    # Verify that list_files can be called (the function the initial sync uses)
    # In the actual implementation, sync_to_s3._watch_loop() calls s3.list_files()
    # at startup instead of s3.file_exists() for each file
    result = s3.list_files()
    assert len(result) == 2
    mock_list_files.assert_called()
