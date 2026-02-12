"""Blind LLM evaluation — ask Claude to compare responses without knowing which backend is which."""

from __future__ import annotations

import random
import subprocess
import string
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from web import config


EVAL_PROMPT = """\
Tu es un évaluateur expert en analyse de données. On a posé la même question \
à {n} systèmes différents. Évalue leurs réponses sans savoir lequel est lequel.

## Question posée
{question}

{responses_block}

## Consignes d'évaluation

Pour chaque réponse, évalue sur 5 points :
1. **Données réelles** (0-5) : les chiffres proviennent-ils visiblement d'appels API réels, \
ou semblent-ils inventés/arrondis de façon suspecte ?
2. **Complétude** (0-5) : toutes les données demandées sont-elles présentes ?
3. **Cohérence** (0-5) : l'analyse correspond-elle aux données brutes affichées ?

Réponds avec un tableau récapitulatif puis un commentaire par réponse. \
Signale explicitement toute réponse que tu soupçonnes d'hallucination.\
"""


def run_blind_eval(
    question_text: str,
    responses: dict[str, str],
    cli_path: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Run a blind eval using the CLI backend.

    Returns (eval_text, label_to_backend_mapping).
    """
    cli = cli_path or config.CLAUDE_CLI

    # Shuffle backends and assign random labels
    backends = list(responses.keys())
    random.shuffle(backends)
    labels = list(string.ascii_uppercase[: len(backends)])
    label_map = dict(zip(labels, backends))

    # Build the responses block
    parts = []
    for label, backend in zip(labels, backends):
        text = responses[backend]
        # Truncate very long responses
        if len(text) > 15000:
            text = text[:15000] + "\n\n[... tronqué ...]"
        parts.append(f"## Réponse {label}\n\n{text}")
    responses_block = "\n\n---\n\n".join(parts)

    prompt = EVAL_PROMPT.format(
        n=len(backends),
        question=question_text,
        responses_block=responses_block,
    )

    result = subprocess.run(
        [cli, "--print", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(config.BASE_DIR),
    )

    if result.returncode != 0:
        return f"Blind eval failed: {result.stderr.strip()}", label_map

    return result.stdout.strip(), label_map


def format_blind_eval(
    question_id: str,
    eval_text: str,
    label_map: dict[str, str],
) -> str:
    """Format blind eval results with the reveal."""
    lines = [
        f"### {question_id}\n",
        eval_text,
        "\n**Reveal:**\n",
    ]
    for label, backend in sorted(label_map.items()):
        lines.append(f"- Réponse {label} = **{backend}**")
    lines.append("")
    return "\n".join(lines)
