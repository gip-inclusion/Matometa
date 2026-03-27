"""Route admin : rejoue une conversation et mesure la latence / tokens / outils."""

import json
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse, StreamingResponse

from lib.tool_taxonomy import classify_tool

from . import config
from .agents import get_agent
from .database import store
from .deps import get_current_user

router = APIRouter()


@dataclass
class PromptResult:
    duration_s: float = 0
    events: int = 0
    tools: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""


def _original_metrics(conv):
    msgs = conv.messages
    user_indices = [i for i, m in enumerate(msgs) if m.type == "user"]

    prompt_durations: list[float] = []
    for k, idx in enumerate(user_indices):
        if k + 1 < len(user_indices):
            t_end = msgs[user_indices[k + 1]].created_at
        else:
            t_end = msgs[-1].created_at
        t_start = msgs[idx].created_at
        prompt_durations.append((t_end - t_start).total_seconds())

    tools: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    for m in msgs:
        if m.type != "tool_use":
            continue
        try:
            data = json.loads(m.content) if isinstance(m.content, str) else {}
            tools[data.get("tool", "?")] += 1
            if "category" in data:
                categories[data["category"]] += 1
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "prompt_durations": prompt_durations,
        "total_s": sum(prompt_durations),
        "tools": tools,
        "categories": categories,
        "msg_count": len(msgs),
        "prompt_count": len(user_indices),
        "input_tokens": conv.usage_input_tokens,
        "output_tokens": conv.usage_output_tokens,
    }


def _history_for_prompt(msgs, prompt_idx: int) -> tuple[str, list[dict]]:
    user_indices = [i for i, m in enumerate(msgs) if m.type == "user"]
    target = user_indices[prompt_idx]
    history = [{"role": m.type, "content": m.content} for m in msgs[:target] if m.type in ("user", "assistant")]
    return msgs[target].content, history


def _run_prompt_line(res: PromptResult) -> str:
    icon = "✓" if not res.error else "✗"
    parts = [f"{res.duration_s}s", f"{res.events} events"]
    if res.tools:
        parts.append(f"{len(res.tools)} tools")
    if res.input_tokens or res.output_tokens:
        parts.append(f"{res.input_tokens:,}↓ {res.output_tokens:,} tok")
    notable = [c for c in Counter(res.categories) if c.startswith(("API:", "Skill:", "Query:"))]
    if notable:
        parts.append(", ".join(notable))
    if res.error:
        parts.append(f"ERR: {res.error[:80]}")
    return f"  {icon} {' · '.join(parts)}\n"


async def _run_prompt(backend, prompt: str, history: list[dict], tag: str) -> PromptResult:
    result = PromptResult()
    t0 = time.monotonic()
    try:
        async for ev in backend.send_message(tag, prompt, history):
            result.events += 1
            if ev.type == "tool_use" and isinstance(ev.content, dict):
                tool = ev.content.get("tool", "")
                inp = ev.content.get("input", {})
                result.tools.append(tool)
                result.categories.append(classify_tool(tool, inp))
            elif ev.type == "system" and ev.raw.get("usage"):
                usage = ev.raw["usage"]
                result.input_tokens += usage.get("input_tokens", 0)
                result.output_tokens += usage.get("output_tokens", 0)
            elif ev.type == "error":
                result.error = str(ev.content)[:200]
    except Exception as e:
        # Why: une erreur agent ne doit pas couper le flux HTTP du benchmark.
        result.error = str(e)[:200]
    result.duration_s = round(time.monotonic() - t0, 1)
    return result


def _table_row(cells: list[str], widths: list[int]) -> str:
    return "  ".join(c.rjust(w) for c, w in zip(cells, widths)) + "\n"


def _yield_summary_table(
    user_n: int,
    runs: int,
    orig: dict,
    all_runs: list[list[PromptResult]],
) -> list[str]:
    w = [8, 10, 10, 10, 10] + ([10] if runs > 1 else [])
    headers = ["Prompt", "Original", "Mean", "Min", "Max"]
    if runs > 1:
        headers.append("Stdev")
    lines = [
        "=" * 60 + "\n",
        f"RESULTS  ({runs} run(s) × {user_n} prompt(s))\n",
        "=" * 60 + "\n\n",
        _table_row(headers, w),
        _table_row(["─" * x for x in w], w),
    ]
    for p in range(user_n):
        ds = [all_runs[r][p].duration_s for r in range(runs)]
        orig_d = orig["prompt_durations"][p] if p < len(orig["prompt_durations"]) else 0
        cells = [
            str(p + 1),
            f"{orig_d:.1f}",
            f"{statistics.mean(ds):.1f}",
            f"{min(ds):.1f}",
            f"{max(ds):.1f}",
        ]
        if runs > 1:
            cells.append(f"{statistics.stdev(ds):.1f}")
        lines.append(_table_row(cells, w))
    totals = [sum(all_runs[r][p].duration_s for p in range(user_n)) for r in range(runs)]
    total_cells = [
        "TOTAL",
        f"{orig['total_s']:.1f}",
        f"{statistics.mean(totals):.1f}",
        f"{min(totals):.1f}",
        f"{max(totals):.1f}",
    ]
    if runs > 1:
        total_cells.append(f"{statistics.stdev(totals):.1f}")
    lines.append(_table_row(["─" * x for x in w], w))
    lines.append(_table_row(total_cells, w))
    return lines


@router.get("/benchmark/{conv_id}")
async def benchmark_conversation(
    conv_id: str,
    runs: int = Query(default=3, ge=1, le=10),
    user_email: str = Depends(get_current_user),
):
    if user_email not in config.ADMIN_USERS:
        return PlainTextResponse("Admin only", status_code=403)

    conv = store.get_conversation(conv_id, include_messages=True)
    if not conv:
        return PlainTextResponse(f"Conversation {conv_id} not found", status_code=404)

    user_msgs = [m for m in conv.messages if m.type == "user"]
    if not user_msgs:
        return PlainTextResponse("No user messages", status_code=400)

    orig = _original_metrics(conv)
    n_prompts = len(user_msgs)

    async def generate():
        yield f"BENCHMARK — {conv.title or conv_id}\n"
        yield "=" * 60 + "\n\n"
        yield f"Source: {orig['prompt_count']} prompt(s), {orig['msg_count']} messages\n"
        yield f"Original duration: {orig['total_s']:.0f}s ({orig['total_s'] / 60:.1f} min)\n"
        yield f"Original tokens: {orig['input_tokens']:,} in / {orig['output_tokens']:,} out\n"
        yield f"Planned: {runs} run(s) × {n_prompts} prompt(s)\n\n"

        try:
            backend = get_agent()
            all_runs: list[list[PromptResult]] = []

            for r in range(runs):
                yield f"━━━ Run {r + 1}/{runs} ━━━\n"
                run_results: list[PromptResult] = []
                run_t0 = time.monotonic()

                for p in range(n_prompts):
                    prompt, history = _history_for_prompt(conv.messages, p)
                    preview = prompt.replace("\n", " ")[:60]
                    yield f"  ▶ Prompt {p + 1}: {preview}…\n"

                    res = await _run_prompt(
                        backend,
                        prompt,
                        history,
                        f"bench-{r}-{p}-{int(time.time())}",
                    )
                    run_results.append(res)
                    yield _run_prompt_line(res)

                run_total = round(time.monotonic() - run_t0, 1)
                yield f"  ⏱  Run total: {run_total}s\n\n"
                all_runs.append(run_results)

            for line in _yield_summary_table(n_prompts, runs, orig, all_runs):
                yield line

            run_in_totals = [sum(r[p].input_tokens for p in range(n_prompts)) for r in all_runs]
            run_out_totals = [sum(r[p].output_tokens for p in range(n_prompts)) for r in all_runs]
            yield "\nTokens (per run):\n"
            yield f"  {'Run':<6} {'Input':>12} {'Output':>12}\n"
            yield f"  {'─' * 6} {'─' * 12} {'─' * 12}\n"
            for r in range(runs):
                yield f"  {r + 1:<6} {run_in_totals[r]:>12,} {run_out_totals[r]:>12,}\n"
            yield f"  {'─' * 6} {'─' * 12} {'─' * 12}\n"
            yield (
                f"  {'Mean':<6} {int(statistics.mean(run_in_totals)):>12,} "
                f"{int(statistics.mean(run_out_totals)):>12,}\n"
            )
            yield f"  {'Orig':<6} {orig['input_tokens']:>12,} {orig['output_tokens']:>12,}\n"

            replay_cats: Counter[str] = Counter()
            for run in all_runs:
                for res in run:
                    replay_cats.update(res.categories)

            all_cat_keys = sorted(set(replay_cats) | set(orig["categories"]))
            if all_cat_keys:
                yield "\nTool categories (replay total / original):\n"
                for cat in all_cat_keys:
                    r_count = replay_cats.get(cat, 0)
                    o_count = orig["categories"].get(cat, 0)
                    yield f"  {cat:<35} {r_count:>4} / {o_count}\n"

            yield "\nDone.\n"

        except Exception as exc:
            # Why: erreur inattendue (store, stats sur liste vide, etc.) → message dans le flux.
            yield f"\n\n❌ BENCHMARK ERROR: {type(exc).__name__}: {exc}\n"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")
