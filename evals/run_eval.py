#!/usr/bin/env python
"""Backend eval suite — send identical questions to multiple backends, compare results.

Usage:
    .venv/bin/python evals/run_eval.py
    .venv/bin/python evals/run_eval.py --backends cli ollama
    .venv/bin/python evals/run_eval.py --questions emplois_jan26 monrecap_yoy
    .venv/bin/python evals/run_eval.py --skip-blind   # skip LLM blind eval
    .venv/bin/python evals/run_eval.py --ollama-models  # auto-detect all ollama models
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from web import config
from web.agents.base import AgentMessage
from web.agents.cli import CLIBackend
from web.agents.cli_ollama import CLIOllamaBackend
from web.agents.ollama import OllamaBackend

from questions import PROMPT_TEMPLATE, QUESTIONS, BACKENDS
from compare import extract_json_data, compare_results, format_comparison
from blind_eval import run_blind_eval, format_blind_eval


BACKEND_CLASSES = {
    "cli": CLIBackend,
    "ollama": OllamaBackend,
    "cli-ollama": CLIOllamaBackend,
}


def get_ollama_models() -> list[str]:
    """Get installed ollama models via CLI."""
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    models = []
    for line in result.stdout.strip().split("\n")[1:]:  # skip header
        if line.strip():
            name = line.split()[0]
            models.append(name)
    return models


async def run_backend(backend_name: str, prompt: str, model_override: str | None = None) -> tuple[str, list[AgentMessage]]:
    """Run a prompt against a backend, return (assistant_text, all_messages).

    For ollama backends, model_override temporarily replaces config.OLLAMA_MODEL.
    """
    original_model = config.OLLAMA_MODEL
    if model_override:
        config.OLLAMA_MODEL = model_override

    try:
        cls = BACKEND_CLASSES[backend_name]
        backend = cls()
        conv_id = str(uuid.uuid4())
        messages = []

        async for msg in backend.send_message(conv_id, prompt, history=[], session_id=None):
            messages.append(msg)

        # Join assistant text
        text_parts = []
        for msg in messages:
            if msg.type == "assistant" and isinstance(msg.content, str):
                text_parts.append(msg.content)

        assistant_text = "\n".join(text_parts)
        return assistant_text, messages
    finally:
        config.OLLAMA_MODEL = original_model


def build_prompt(question: dict) -> str:
    """Build the eval prompt from a question."""
    return PROMPT_TEMPLATE.format(question=question["question"])


def parse_args():
    parser = argparse.ArgumentParser(description="Backend eval suite")
    parser.add_argument(
        "--backends", nargs="+", default=None,
        help="Backends to evaluate (cli, ollama, cli-ollama). "
             "When --ollama-models is used, 'ollama' entries are expanded per model.",
    )
    parser.add_argument(
        "--ollama-models", nargs="*", default=None,
        help="Ollama models to test. Pass without args to auto-detect, or list specific models.",
    )
    parser.add_argument(
        "--ollama-backend", default="ollama",
        choices=["ollama", "cli-ollama"],
        help="Which backend type to use for ollama models (default: ollama)",
    )
    parser.add_argument(
        "--copy-from", type=Path, default=None,
        help="Copy existing backend results from a previous run directory",
    )
    parser.add_argument(
        "--questions", nargs="+", default=None,
        help="Question IDs to run (default: all)",
    )
    parser.add_argument(
        "--skip-blind", action="store_true",
        help="Skip LLM blind evaluation",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Output directory (default: evals/results/<timestamp>)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    # Build backend list: list of (display_name, backend_type, model_override)
    backend_entries: list[tuple[str, str, str | None]] = []

    if args.ollama_models is not None:
        # --ollama-models used: auto-detect or use specified models
        models = args.ollama_models if args.ollama_models else get_ollama_models()
        if not models:
            print("No ollama models found. Install models with 'ollama pull <model>'.")
            sys.exit(1)

        # Add non-ollama backends from --backends (default: cli, unless --copy-from)
        if args.copy_from:
            base_backends = args.backends or []
        else:
            base_backends = args.backends or ["cli"]
        for b in base_backends:
            if b and b not in ("ollama", "cli-ollama"):
                backend_entries.append((b, b, None))

        # Add one ollama entry per model (using chosen backend type)
        backend_type = args.ollama_backend
        for model in models:
            # Sanitize model name for filenames (replace : with _)
            safe_name = f"ollama_{model.replace(':', '_').replace('/', '_')}"
            backend_entries.append((safe_name, backend_type, model))
    else:
        # Legacy mode: use --backends or defaults
        backends = args.backends or BACKENDS
        for b in backends:
            backend_entries.append((b, b, None))

    # Filter questions
    questions = QUESTIONS
    if args.questions:
        questions = [q for q in QUESTIONS if q["id"] in args.questions]
        if not questions:
            print(f"No questions matched: {args.questions}")
            print(f"Available: {[q['id'] for q in QUESTIONS]}")
            sys.exit(1)

    # Setup output directory
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir or Path(__file__).parent / "results" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    backend_display = [name for name, _, _ in backend_entries]

    # Copy results from a previous run if requested
    copied_backends: list[str] = []
    if args.copy_from:
        print(f"Copying results from {args.copy_from}...")

    print(f"Eval run: {run_id}")
    print(f"Backends: {backend_display}")
    print(f"Questions: {[q['id'] for q in questions]}")
    print(f"Output: {output_dir}")
    print()

    # Phase 1: Run all questions against all backends
    all_responses: dict[str, dict[str, str]] = {}  # question_id -> {backend_name -> text}

    # Pre-populate from --copy-from if provided
    if args.copy_from:
        for question in questions:
            qid = question["id"]
            src_dir = args.copy_from / qid
            if not src_dir.exists():
                continue
            question_dir = output_dir / qid
            question_dir.mkdir(exist_ok=True)
            all_responses.setdefault(qid, {})
            for md_file in src_dir.glob("*.md"):
                backend_name = md_file.stem
                if backend_name in ("comparison", "blind_eval"):
                    continue
                text = md_file.read_text(encoding="utf-8")
                (question_dir / md_file.name).write_text(text, encoding="utf-8")
                all_responses[qid][backend_name] = text
                if backend_name not in copied_backends:
                    copied_backends.append(backend_name)
        print(f"Copied backends: {copied_backends}")
        backend_display = copied_backends + backend_display

    for question in questions:
        question_dir = output_dir / question["id"]
        question_dir.mkdir(exist_ok=True)
        prompt = build_prompt(question)
        all_responses.setdefault(question["id"], {})

        for display_name, backend_type, model_override in backend_entries:
            label = f"{display_name} ({model_override})" if model_override else display_name
            print(f"[{question['id']}] Running {label}...", end=" ", flush=True)
            try:
                text, messages = await run_backend(backend_type, prompt, model_override)
                print(f"OK ({len(text)} chars, {len(messages)} events)")
            except Exception as e:
                text = f"ERROR: {e}"
                print(f"FAILED: {e}")

            # Save raw response
            (question_dir / f"{display_name}.md").write_text(text, encoding="utf-8")
            all_responses[question["id"]][display_name] = text

    # Phase 2: Compare raw data
    print("\n--- Data Comparison ---\n")
    comparison_sections = []

    for question in questions:
        qid = question["id"]
        extracted = {}
        for name in backend_display:
            text = all_responses[qid].get(name, "")
            extracted[name] = extract_json_data(text)

        comparison = compare_results(extracted)
        section = format_comparison(qid, comparison)
        comparison_sections.append(section)
        print(section)

        # Save comparison data
        (output_dir / question["id"] / "comparison.json").write_text(
            json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Phase 3: Blind LLM eval
    blind_sections = []
    if not args.skip_blind:
        print("\n--- Blind LLM Evaluation ---\n")
        for question in questions:
            qid = question["id"]
            responses = all_responses[qid]
            if len(responses) < 2:
                print(f"[{qid}] Skipping blind eval (< 2 responses)")
                continue

            print(f"[{qid}] Running blind eval...", end=" ", flush=True)
            try:
                eval_text, label_map = run_blind_eval(
                    question["question"], responses
                )
                section = format_blind_eval(qid, eval_text, label_map)
                blind_sections.append(section)
                print("OK")

                # Save blind eval
                (output_dir / qid / "blind_eval.md").write_text(
                    section, encoding="utf-8"
                )
            except Exception as e:
                print(f"FAILED: {e}")
                blind_sections.append(f"### {qid}\n\nBlind eval failed: {e}\n")

    # Phase 4: Generate report
    report_lines = [
        f"# Eval Report — {run_id}\n",
        f"**Backends:** {', '.join(backend_display)}",
        f"**Questions:** {len(questions)}",
        f"**Date:** {datetime.now().isoformat()}\n",
        "## Data Comparison\n",
        *comparison_sections,
    ]
    if blind_sections:
        report_lines.extend([
            "## Blind LLM Evaluation\n",
            *blind_sections,
        ])

    report = "\n".join(report_lines)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"\nReport saved to {output_dir / 'report.md'}")


if __name__ == "__main__":
    asyncio.run(main())
