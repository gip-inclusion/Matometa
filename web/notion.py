"""Publish reports to Notion as pages in the 'Rapports publics' database."""

import json
import os
import re
import urllib.request

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_REPORTS_DB = os.getenv("NOTION_REPORTS_DB")


def is_configured() -> bool:
    return bool(NOTION_TOKEN and NOTION_REPORTS_DB)


def parse_inline(text: str) -> list[dict]:
    results = []
    pattern = re.compile(
        r"\*\*(.+?)\*\*"  # bold
        r"|\*(.+?)\*"  # italic
        r"|`([^`]+)`"  # inline code
        r"|\[([^\]]+)\]\(([^)]+)\)"  # link
        r"|([^*`\[]+)"  # plain text
        r"|(.)"  # fallback single char
    )
    for m in pattern.finditer(text):
        bold, italic, code, link_text, link_url, plain, fallback = m.groups()
        if bold:
            results.append(rich_text(bold, bold=True))
        elif italic:
            results.append(rich_text(italic, italic=True))
        elif code:
            results.append(rich_text(code, code=True))
        elif link_text:
            results.append(rich_text(link_text, link=link_url))
        elif plain:
            results.append(rich_text(plain))
        elif fallback:
            results.append(rich_text(fallback))
    return results or [rich_text("")]


def rich_text(content: str, bold=False, italic=False, code=False, link=None) -> dict:
    content = content[:2000]
    obj = {
        "type": "text",
        "text": {"content": content},
        "annotations": {
            "bold": bold,
            "italic": italic,
            "code": code,
            "strikethrough": False,
            "underline": False,
            "color": "default",
        },
    }
    if link:
        obj["text"]["link"] = {"url": link}
    return obj


NOTION_CODE_LANG_MAP = {
    "django": "html",
    "bash": "bash",
    "python": "python",
    "javascript": "javascript",
    "html": "html",
    "mermaid": "mermaid",
    "yaml": "yaml",
    "json": "json",
    "css": "css",
    "sql": "sql",
    "shell": "bash",
    "sh": "bash",
}


def markdown_to_blocks(md: str) -> list[dict]:
    # Strip YAML frontmatter
    md = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.DOTALL)

    lines = md.split("\n")
    blocks = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        # Divider
        if re.match(r"^---+\s*$", line):
            blocks.append({"type": "divider", "divider": {}})
            i += 1
            continue

        # Headings
        heading_match = re.match(r"^(#{1,3})\s+(.*)", line)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2).strip()
            htype = f"heading_{level}"
            blocks.append({"type": htype, htype: {"rich_text": parse_inline(text)}})
            i += 1
            continue

        # Code block (fenced)
        code_match = re.match(r"^```(\w*)", line)
        if code_match:
            lang = code_match.group(1) or "plain text"
            notion_lang = NOTION_CODE_LANG_MAP.get(lang, lang)
            code_lines = []
            i += 1
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            code_content = "\n".join(code_lines)
            if len(code_content) > 2000:
                code_content = code_content[:1997] + "..."
            blocks.append(
                {
                    "type": "code",
                    "code": {
                        "rich_text": [rich_text(code_content)],
                        "language": notion_lang,
                    },
                }
            )
            continue

        # Table
        if "|" in line and re.match(r"^\s*\|", line):
            table_lines = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                table_lines.append(lines[i])
                i += 1
            data_lines = [line for line in table_lines if not re.match(r"^\s*\|[-:\s|]+\|\s*$", line)]
            if data_lines:
                rows = []
                for tl in data_lines:
                    cells = [c.strip() for c in tl.strip().strip("|").split("|")]
                    rows.append(cells)
                col_count = max(len(r) for r in rows)
                table_rows = []
                for row in rows:
                    while len(row) < col_count:
                        row.append("")
                    row = row[:col_count]
                    table_rows.append(
                        {
                            "type": "table_row",
                            "table_row": {
                                "cells": [parse_inline(cell) for cell in row],
                            },
                        }
                    )
                blocks.append(
                    {
                        "type": "table",
                        "table": {
                            "table_width": col_count,
                            "has_column_header": True,
                            "has_row_header": False,
                            "children": table_rows,
                        },
                    }
                )
            continue

        # Numbered list
        num_match = re.match(r"^(\d+)\.\s+(.*)", line)
        if num_match:
            blocks.append(
                {
                    "type": "numbered_list_item",
                    "numbered_list_item": {"rich_text": parse_inline(num_match.group(2))},
                }
            )
            i += 1
            continue

        # Bullet list
        bullet_match = re.match(r"^[-*]\s+(.*)", line)
        if bullet_match:
            blocks.append(
                {
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": parse_inline(bullet_match.group(1))},
                }
            )
            i += 1
            continue

        # Regular paragraph
        para_lines = []
        while (
            i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,3}\s|```|---|\|.*\||\d+\.\s|[-*]\s)", lines[i])
        ):
            para_lines.append(lines[i])
            i += 1
        if para_lines:
            blocks.append(
                {
                    "type": "paragraph",
                    "paragraph": {"rich_text": parse_inline(" ".join(para_lines))},
                }
            )
            continue

        i += 1

    return blocks


def notion_request(method: str, endpoint: str, payload: dict = None) -> dict:
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    url = f"https://api.notion.com/v1/{endpoint}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def publish_report(
    title: str,
    content: str,
    website: str | None = None,
    original_query: str | None = None,
    date: str | None = None,
) -> tuple[str, str]:
    """Publish markdown content to Notion. Returns (page_id, url).

    Raises on API errors (urllib.error.HTTPError).
    """
    if not is_configured():
        raise RuntimeError("Notion not configured (NOTION_TOKEN / NOTION_REPORTS_DB)")

    # Extract from frontmatter (authoritative source, overrides DB fields)
    fm_date = None
    fm_query = None
    m = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", content, re.MULTILINE)
    if m:
        fm_date = m.group(1)
    m = re.search(r'^original_query:\s*"?(.+?)"?\s*$', content, re.MULTILINE)
    if m:
        fm_query = m.group(1)

    date = fm_date or date
    original_query = fm_query or original_query

    # Build page properties
    properties = {
        "Titre": {"title": [{"text": {"content": title}}]},
    }
    if date:
        properties["Date de publication"] = {"date": {"start": date}}
    if website:
        properties["Produits concernés"] = {
            "multi_select": [{"name": website}],
        }
    if original_query:
        properties["Requête initiale"] = {
            "rich_text": [{"text": {"content": original_query[:2000]}}],
        }

    # Create page
    result = notion_request(
        "POST",
        "pages",
        {"parent": {"database_id": NOTION_REPORTS_DB}, "properties": properties},
    )
    page_id = result["id"]
    page_url = result["url"]

    # Convert and append blocks
    blocks = markdown_to_blocks(content)
    for i in range(0, len(blocks), 100):
        batch = blocks[i : i + 100]
        notion_request("PATCH", f"blocks/{page_id}/children", {"children": batch})

    return page_id, page_url
