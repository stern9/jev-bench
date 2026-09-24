"""Render a Markdown report from a run's records."""
from __future__ import annotations

from collections import defaultdict

from .metrics import Summary, summarize


def _fmt(v, spec: str, suffix: str = "") -> str:
    return "—" if v is None else f"{v:{spec}}{suffix}"


def render(records: list[dict], title: str) -> str:
    rows = summarize(records)
    by_task: dict[str, list[Summary]] = defaultdict(list)
    for s in rows:
        by_task[s.task].append(s)

    lines = [f"# {title}", ""]
    lines += _headline(rows)
    for task, summaries in by_task.items():
        lines += [f"## {task}", "",
                  "| Model | Accuracy | p50 latency | p95 latency | ECE ↓ | Brier ↓ | $ / 1k calls | Errors |",
                  "|---|---|---|---|---|---|---|---|"]
        for s in sorted(summaries, key=lambda s: -s.accuracy):
            lines.append(
                f"| `{s.model}` | {s.accuracy:.1%} | {_fmt(s.p50_ms, ',.0f', ' ms')} | {_fmt(s.p95_ms, ',.0f', ' ms')} "
                f"| {_fmt(s.ece, '.3f')} | {_fmt(s.brier, '.3f')} | {_fmt(s.cost_per_1k, ',.4f')} | {s.errors}/{s.n} |")
        lines.append("")
        misses = [r for r in records if r["task"] == task and r["error"] is None and r["predicted"] != r["expected"]]
        if misses:
            lines += ["<details><summary>Misses</summary>", "",
                      "| Model | Example | Expected | Predicted | Confidence |", "|---|---|---|---|---|"]
            lines += [f"| `{r['model']}` | {r['example_id']} | {r['expected']} | {r['predicted']} | {r['confidence']:.2f} |"
                      for r in misses]
            lines += ["", "</details>", ""]
    lines += ["---", "",
              "**ECE** (expected calibration error): how far stated confidence is from actual accuracy; 0 is perfect.  ",
              "**Brier**: squared error of the full probability distribution vs the truth; lower is better.  ",
              "Latency is wall-clock per call from this machine, including network."]
    return "\n".join(lines) + "\n"


def _headline(rows: list[Summary]) -> list[str]:
    """One line per (task, Jev model, LLM) comparing accuracy and p50 speed."""
    jev = [s for s in rows if s.model.startswith("jev")]
    llm = [s for s in rows if not s.model.startswith("jev")]
    out = []
    for a in jev:
        for b in (s for s in llm if s.task == a.task):
            speed = b.p50_ms / a.p50_ms if a.p50_ms and b.p50_ms else None
            out.append(f"- **{a.task}**: `{a.model}` {a.accuracy:.0%} vs `{b.model}` {b.accuracy:.0%} accuracy"
                       + (f", **{speed:,.0f}× faster** at p50" if speed else ""))
    return ["## Headline", "", *out, ""] if out else []
