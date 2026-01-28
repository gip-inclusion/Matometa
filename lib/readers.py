"""
File format readers for Excel, Word, PDF, and ZIP files.

Usage:
    from lib.readers import read_excel, read_word, read_pdf, list_zip

    # Read Excel file - returns markdown table(s)
    content = read_excel("/path/to/file.xlsx")
    content = read_excel("/path/to/file.xlsx", sheet="Sheet1")  # specific sheet

    # Read Word document - returns markdown
    content = read_word("/path/to/file.docx")

    # Read PDF - returns text with page markers
    content = read_pdf("/path/to/file.pdf")
    content = read_pdf("/path/to/file.pdf", pages="1-5")  # specific pages

    # List ZIP contents
    contents = list_zip("/path/to/file.zip")

CLI usage (for agent):
    python -c "from lib.readers import read_excel; print(read_excel('file.xlsx'))"
"""

import io
from pathlib import Path
from typing import Optional, Union


def read_excel(
    path: Union[str, Path],
    sheet: Optional[str] = None,
    max_rows: int = 1000,
) -> str:
    """
    Read an Excel file and return contents as markdown tables.

    Args:
        path: Path to .xlsx or .xls file
        sheet: Specific sheet name (default: all sheets)
        max_rows: Maximum rows per sheet to prevent huge outputs

    Returns:
        Markdown formatted tables, one per sheet
    """
    import pandas as pd

    path = Path(path)
    if not path.exists():
        return f"Error: File not found: {path}"

    try:
        # Read all sheets or specific sheet
        if sheet:
            df = pd.read_excel(path, sheet_name=sheet, nrows=max_rows)
            sheets = {sheet: df}
        else:
            sheets = pd.read_excel(path, sheet_name=None, nrows=max_rows)

        results = []
        for sheet_name, df in sheets.items():
            results.append(f"## Sheet: {sheet_name}\n")
            results.append(f"*{len(df)} rows, {len(df.columns)} columns*\n")

            if len(df) == 0:
                results.append("(empty sheet)\n")
            else:
                # Convert to markdown table
                results.append(df.to_markdown(index=False))

            if len(df) == max_rows:
                results.append(f"\n*Truncated at {max_rows} rows*")

            results.append("\n")

        return "\n".join(results)

    except Exception as e:
        return f"Error reading Excel file: {e}"


def read_word(path: Union[str, Path]) -> str:
    """
    Read a Word document and return contents as markdown.

    Args:
        path: Path to .docx file

    Returns:
        Markdown formatted content
    """
    import mammoth

    path = Path(path)
    if not path.exists():
        return f"Error: File not found: {path}"

    try:
        with open(path, "rb") as f:
            result = mammoth.convert_to_markdown(f)

        content = result.value
        if result.messages:
            warnings = [m.message for m in result.messages if m.type == "warning"]
            if warnings:
                content += "\n\n---\n*Conversion warnings:*\n"
                content += "\n".join(f"- {w}" for w in warnings[:5])

        return content

    except Exception as e:
        return f"Error reading Word file: {e}"


def read_pdf(
    path: Union[str, Path],
    pages: Optional[str] = None,
    max_pages: int = 50,
) -> str:
    """
    Read a PDF and return text content with page markers.

    Args:
        path: Path to .pdf file
        pages: Page range like "1-5" or "1,3,5" (default: all)
        max_pages: Maximum pages to extract

    Returns:
        Text content with page markers
    """
    import pdfplumber

    path = Path(path)
    if not path.exists():
        return f"Error: File not found: {path}"

    try:
        # Parse page range
        page_nums = None
        if pages:
            page_nums = _parse_page_range(pages)

        results = []
        with pdfplumber.open(path) as pdf:
            total_pages = len(pdf.pages)
            results.append(f"*PDF: {total_pages} pages*\n")

            pages_to_read = page_nums if page_nums else range(total_pages)
            pages_read = 0

            for i in pages_to_read:
                if i >= total_pages:
                    continue
                if pages_read >= max_pages:
                    results.append(f"\n*Truncated at {max_pages} pages*")
                    break

                page = pdf.pages[i]
                text = page.extract_text() or "(no text on this page)"

                results.append(f"\n--- Page {i + 1} ---\n")
                results.append(text)
                pages_read += 1

                # Also extract tables if present
                tables = page.extract_tables()
                if tables:
                    for j, table in enumerate(tables):
                        results.append(f"\n*Table {j + 1}:*\n")
                        results.append(_table_to_markdown(table))

        return "\n".join(results)

    except Exception as e:
        return f"Error reading PDF file: {e}"


def list_zip(path: Union[str, Path], max_entries: int = 100) -> str:
    """
    List contents of a ZIP file.

    Args:
        path: Path to .zip file
        max_entries: Maximum entries to list

    Returns:
        Formatted list of ZIP contents with sizes
    """
    import zipfile

    path = Path(path)
    if not path.exists():
        return f"Error: File not found: {path}"

    try:
        results = []
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            results.append(f"*ZIP archive: {len(infos)} entries*\n")

            for i, info in enumerate(infos[:max_entries]):
                if info.is_dir():
                    results.append(f"  {info.filename}/")
                else:
                    size = _format_size(info.file_size)
                    results.append(f"  {info.filename} ({size})")

            if len(infos) > max_entries:
                results.append(f"\n*... and {len(infos) - max_entries} more entries*")

        return "\n".join(results)

    except zipfile.BadZipFile:
        return "Error: Invalid or corrupted ZIP file"
    except Exception as e:
        return f"Error reading ZIP file: {e}"


def extract_from_zip(
    zip_path: Union[str, Path],
    file_path: str,
) -> str:
    """
    Extract and read a single file from a ZIP archive.

    Args:
        zip_path: Path to .zip file
        file_path: Path within the ZIP to extract

    Returns:
        File contents (text if decodable, else error)
    """
    import zipfile

    zip_path = Path(zip_path)
    if not zip_path.exists():
        return f"Error: ZIP file not found: {zip_path}"

    # Security: prevent path traversal
    if ".." in file_path or file_path.startswith("/"):
        return "Error: Invalid file path (security)"

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if file_path not in zf.namelist():
                return f"Error: File not found in ZIP: {file_path}"

            info = zf.getinfo(file_path)

            # Size limit: 10MB
            if info.file_size > 10 * 1024 * 1024:
                return f"Error: File too large ({_format_size(info.file_size)})"

            content = zf.read(file_path)

            # Try to decode as text
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    return content.decode("latin-1")
                except UnicodeDecodeError:
                    return f"Error: Binary file, cannot display as text ({_format_size(len(content))})"

    except Exception as e:
        return f"Error extracting from ZIP: {e}"


def _parse_page_range(pages: str) -> list[int]:
    """Parse page range string like '1-5' or '1,3,5' into list of 0-indexed page numbers."""
    result = []
    for part in pages.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            result.extend(range(int(start) - 1, int(end)))
        else:
            result.append(int(part) - 1)
    return result


def _table_to_markdown(table: list[list]) -> str:
    """Convert a table (list of rows) to markdown format."""
    if not table or not table[0]:
        return "(empty table)"

    # Use first row as header
    header = table[0]
    rows = table[1:] if len(table) > 1 else []

    lines = []
    lines.append("| " + " | ".join(str(c or "") for c in header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(c or "") for c in row) + " |")

    return "\n".join(lines)


def _format_size(size: int) -> str:
    """Format byte size as human readable."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
