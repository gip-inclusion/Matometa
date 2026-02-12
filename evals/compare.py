"""Extract and compare raw data across backend responses."""

from __future__ import annotations

import json
import re
from itertools import combinations


def extract_json_data(markdown: str) -> list[dict] | None:
    """Extract the api_calls JSON array from a markdown response.

    Looks for a ```json block after '## Données brutes'.
    Returns None if parsing fails.
    """
    # Find the raw data section
    section_match = re.search(
        r"##\s*Données brutes.*?```json\s*\n(.*?)```",
        markdown,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return None

    raw = section_match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    # Accept both a bare list and {"api_calls": [...]}
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "api_calls" in data:
        return data["api_calls"]
    return None


def _flatten_numbers(obj, prefix="") -> dict[str, float]:
    """Recursively extract all numeric values with dotted key paths."""
    results = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            results.update(_flatten_numbers(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            results.update(_flatten_numbers(v, f"{prefix}[{i}]."))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        results[prefix.rstrip(".")] = float(obj)
    return results


def compare_results(
    results: dict[str, list[dict] | None],
    threshold: float = 0.05,
) -> dict:
    """Compare extracted data across backends.

    Returns a dict with:
    - "call_counts": {backend: int}
    - "discrepancies": [{pair, key, values, pct_diff}]
    - "missing_data": [backend names that returned None]
    """
    call_counts = {}
    missing_data = []
    all_numbers: dict[str, dict[str, float]] = {}

    for backend, calls in results.items():
        if calls is None:
            missing_data.append(backend)
            call_counts[backend] = 0
            continue
        call_counts[backend] = len(calls)
        # Flatten all numeric values from results
        flat = {}
        for i, call in enumerate(calls):
            result = call.get("result", {})
            flat.update(_flatten_numbers(result, f"call[{i}]."))
        all_numbers[backend] = flat

    discrepancies = []
    backends_with_data = [b for b in results if b not in missing_data]

    for a, b in combinations(backends_with_data, 2):
        nums_a = all_numbers.get(a, {})
        nums_b = all_numbers.get(b, {})
        common_keys = set(nums_a) & set(nums_b)

        for key in sorted(common_keys):
            va, vb = nums_a[key], nums_b[key]
            if va == vb == 0:
                continue
            denom = max(abs(va), abs(vb))
            pct_diff = abs(va - vb) / denom if denom else 0

            if pct_diff > threshold:
                discrepancies.append({
                    "pair": f"{a} vs {b}",
                    "key": key,
                    "values": {a: va, b: vb},
                    "pct_diff": round(pct_diff * 100, 1),
                })

    return {
        "call_counts": call_counts,
        "discrepancies": discrepancies,
        "missing_data": missing_data,
    }


def format_comparison(question_id: str, comparison: dict) -> str:
    """Format a comparison result as markdown."""
    lines = [f"### {question_id}\n"]

    lines.append("**API calls per backend:**")
    for b, c in comparison["call_counts"].items():
        lines.append(f"- {b}: {c} calls")
    lines.append("")

    if comparison["missing_data"]:
        lines.append(f"**Missing data:** {', '.join(comparison['missing_data'])}\n")

    if comparison["discrepancies"]:
        lines.append(f"**Discrepancies ({len(comparison['discrepancies'])}):**\n")
        lines.append("| Pair | Key | Values | % Diff |")
        lines.append("|------|-----|--------|--------|")
        for d in comparison["discrepancies"]:
            vals = " / ".join(f"{b}={v:g}" for b, v in d["values"].items())
            lines.append(f"| {d['pair']} | `{d['key']}` | {vals} | {d['pct_diff']}% |")
        lines.append("")
    else:
        lines.append("**No discrepancies found.**\n")

    return "\n".join(lines)
