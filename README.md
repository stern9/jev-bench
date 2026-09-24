# jev-bench

Benchmark **[Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)**, TypeSafe's *System One* model, against Claude on the kind of fast, structured decisions software makes all day: routing, yes/no checks and graded ratings.

Jev doesn't generate text. It answers typed questions (`choice`, `score`, `noul`) with a calibrated probability for every possible answer, in tens to hundreds of milliseconds. This harness asks both models **the exact same questions** and measures:

| Metric | What it tells you |
|---|---|
| **Accuracy** | Did it pick the right answer? |
| **Latency** (p50 / p95) | Wall-clock time per decision, same client machine for every model |
| **Calibration** (ECE, Brier) | When it says it's 90% sure, is it right 90% of the time? |
| **Cost** per 1k calls | From reported token usage and list prices |

The comparison is fair by construction. Jev is called via `typesafe-sdk`, and Claude is called via [`system-one-adapter`](https://github.com/typesafe-ai/system-one-adapter-python), a drop-in replacement for the same `system_one()` API backed by Claude's structured outputs. Every model gets identical questions and is scored by identical code.

## Results (2026-09-24)

72 labeled decisions across 3 tasks. Every model got identical questions.

| | `jev-latest` | `claude-haiku-4-5` | `claude-opus-5` |
|---|---|---|---|
| **Accuracy** (all 72) | **94.4%** | 91.7% | 98.6% |
| **p50 latency** | **~185 ms** | ~1.2 s | ~2.6 s |
| **$ per 1k decisions** | **~$0.02** | ~$0.82 | ~$6.40 |
| Speed vs Jev | 1× | ~7× slower | ~14× slower |

| Task | Jev | Haiku 4.5 | Opus 5 |
|---|---|---|---|
| `support_routing` (choice, 5 teams) | 96.2% · 183 ms | 92.3% · 1,530 ms | 100% · 2,548 ms |
| `phishing_check` (yes/no) | 100% · 175 ms | 100% · 1,156 ms | 100% · 2,547 ms |
| `incident_severity` (score 0–3) | 86.4% · 193 ms | 81.8% · 1,524 ms | 95.5% · 2,926 ms |

**Takeaways**

- **Jev vs Haiku (fast vs fast):** Jev was more accurate on 2 of 3 tasks and tied the third, while being ~7× faster and ~50× cheaper.
- **Jev vs Opus (the ceiling):** Opus 5 is the most accurate, but Jev reaches ~96% of its accuracy at ~1/14 the latency and a tiny fraction of the cost.
- **Calibration:** Jev's confidence was well calibrated on routing (ECE 0.025, best of the three). On severity, Opus was the most accurate but the least calibrated (ECE 0.24): it tended to sound less sure than its hit rate justified.
- **Where Jev missed:** adjacent severity levels (low vs medium), and one ticket that mixed login symptoms with a browser bug.

Full per-task tables, calibration metrics and every miss: [`docs/results-2026-09-24.md`](docs/results-2026-09-24.md).

> **Caveats:** a small hand-labeled set (72 examples) and a single run. Latency is measured end-to-end from one laptop, including network. Claude models ran with default settings through `system-one-adapter` (Opus 5 uses adaptive thinking). Treat these results as directional, and add your own tasks for your use case.

## Tasks

| Task | Type | Examples | Decision |
|---|---|---|---|
| `support_routing` | choice | 26 | Which of 5 teams should handle a support ticket |
| `phishing_check` | noul (yes/no) | 24 | Is this message a phishing or scam attempt |
| `incident_severity` | score (0–3) | 22 | How severe is this production alert |

Each task lives in `tasks/*.json` as one question plus labeled examples, including a few deliberately ambiguous ones.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env        # add TYPESAFE_API_KEY and ANTHROPIC_API_KEY

jev-bench tasks                                   # list tasks
jev-bench run --limit 5                           # quick sanity run
jev-bench run                                     # full run: jev-latest vs claude-opus-5
jev-bench run --models jev-latest claude-opus-5 claude-haiku-4-5
```

Each run writes `results/<timestamp>/records.jsonl` (every call, with its probabilities) and `report.md`.

## Add your own task

Drop a JSON file in `tasks/`:

```json
{
  "name": "refund_eligible",
  "description": "Is this refund request within policy",
  "question": {
    "type": "noul",
    "instructions": "Is this refund request eligible under a 30-day, unused-item policy?"
  },
  "examples": [
    {"id": "r-01", "state": "Bought 10 days ago, never opened.", "expected": true}
  ]
}
```

`expected` is a label for `choice`, an integer level (0-based) for `score`, and `true`/`false` for `noul`.

## Tests

```bash
pytest   # offline: fake model answers, real task files and scoring
```
