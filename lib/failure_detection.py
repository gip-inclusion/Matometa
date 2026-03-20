"""Detect failure markers in assistant messages.

Identifies messages where Autometa likely made an error, correction,
or omission — based on keyword matching in the assistant's own text.
"""

import re

# Failure markers grouped by category
FAILURE_MARKERS = [
    # Erreurs
    "je me suis trompé",
    "erreur de ma part",
    "pardon",
    "mea culpa",
    # Corrections
    "correction :",
    "j'aurais dû",
    "je corrige",
    # Oublis
    "j'ai oublié",
    "oubli de ma part",
    "j'avais omis",
    # Excuses
    "désolé",
    "je m'excuse",
    "toutes mes excuses",
    # Échecs
    "n'a pas fonctionné",
    "a échoué",
    "impossible de",
    "je n'ai pas réussi",
]


def find_failure_marker(text: str) -> str | None:
    """Return the first failure marker found in text, or None."""
    text_lower = text.lower()
    for marker in FAILURE_MARKERS:
        if marker in text_lower:
            return marker
    return None


def extract_snippet(content: str, marker: str | None = None) -> str:
    """Extract a short snippet around the first failure marker found."""
    content_lower = content.lower()
    markers_to_check = [marker] if marker else FAILURE_MARKERS

    for m in markers_to_check:
        pos = content_lower.find(m)
        if pos == -1:
            continue
        # Find sentence boundaries around the marker
        start = max(0, content.rfind(".", 0, pos) + 1)
        end = content.find(".", pos)
        if end == -1 or end - start > 200:
            end = min(len(content), pos + len(m) + 80)
        else:
            end += 1  # include the period
        snippet = content[start:end].strip()
        # Clean up markdown/whitespace
        snippet = re.sub(r"\s+", " ", snippet)
        if len(snippet) > 150:
            snippet = snippet[:147] + "..."
        return snippet
    return ""
