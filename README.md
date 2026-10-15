# jev-bench

Benchmark **[Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)**, TypeSafe's *System One* model, against general-purpose LLMs (Claude, GPT, or local models) on the kind of fast, structured decisions software makes all day: routing, yes/no checks and graded ratings.

Jev doesn't generate text. It answers typed questions (`choice`, `score`, `noul`) with a calibrated probability for every possible answer, in tens to hundreds of milliseconds. This harness asks every model **the exact same questions** and measures:

| Metric | What it tells you |
|---|---|
| **Accuracy** | Did it pick the right answer? |
| **Latency** (p50 / p95) | Wall-clock time per decision, same client machine for every model |
| **Calibration** (ECE, Brier) | When it says it's 90% sure, is it right 90% of the time? |
| **Cost** per 1k calls | From reported token usage and list prices |

The comparison is fair by construction. Jev is called via `typesafe-sdk`, and every LLM is called via [`system-one-adapter`](https://github.com/typesafe-ai/system-one-adapter-python), a drop-in replacement for the same `system_one()` API backed by the LLM's structured outputs. Every model gets identical questions and is scored by identical code.

## Results (October 2026)

72 labeled decisions across 3 tasks, all run from the same laptop (Apple M5 Pro, 48 GB). Jev is listed first as the baseline, then models by accuracy. "Speed vs Jev" compares p50 latency.

**API models** (2026-10-14):

| Model | Accuracy (72) | p50 latency | $ per 1k decisions | Speed vs Jev |
|---|---|---|---|---|
| **`jev-latest`** | 94.4% | **171 ms** | **$0.017** | 1× |
| `openai:gpt-6.1-sol` | **100%** | 2.26 s | $1.31 | ~13× slower |
| `openai:gpt-6-astra` | **100%** | 2.26 s | $6.67 | ~13× slower |
| `claude-opus-5-5` | 97.2% | 2.12 s | $4.33 | ~12× slower |
| `openai:gpt-6-luna` | 97.2% | 1.90 s | $0.073 | ~11× slower |
| `claude-haiku-5-5` | 95.8% | 1.44 s | $0.12 | ~8× slower |
| `claude-sonnet-5-5` | 93.1% | 1.68 s | $2.14 | ~10× slower |

| Task | Jev | GPT-6.1 Sol | GPT-6 Astra | Opus 5.5 | GPT-6 Luna | Haiku 5.5 | Sonnet 5.5 |
|---|---|---|---|---|---|---|---|
| `support_routing` (choice, 5 teams) | 96.2% | 100% | 100% | 96.2% | 100% | 96.2% | 92.3% |
| `phishing_check` (yes/no) | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| `incident_severity` (score 0–3) | 86.4% | 100% | 100% | 95.5% | 90.9% | 90.9% | 86.4% |

**Local models** (2026-10-15; free, via LM Studio with MLX builds):

| Model | Accuracy (72) | p50 latency | Speed vs Jev | Routing | Phishing | Severity |
|---|---|---|---|---|---|---|
| `local:gemma-4-26b-a4b-it-mlx` | 97.2% | 619 ms | ~4× slower | 100% | 100% | 90.9% |
| `local:qwen3.6-27b-mlx` | 95.8% | 3.61 s | ~21× slower | 100% | 100% | 86.4% |
| `local:qwen3.6-35b-a3b-mlx` | 76.4% | 597 ms | ~3.5× slower | 88.5% | 70.8% | 68.2% |
| `local:google/gemma-4-e4b` | 70.8% | 889 ms | ~5× slower | 96.2% | 62.5% | 50.0% |

Model names are the exact `--models` ids used, so any row can be re-run as is.

## Verdict

**Jev is by far the fastest and cheapest; on accuracy it sits in the pack.** Most models, Jev included, land within 1–2 questions of each other (67–70 of 72), which is noise at this sample size. Only GPT-6.1 Sol and GPT-6 Astra clearly stand out, with all 72 right. All of Jev's misses but one are on severity (graded 0–3), where every API model except Sol and Astra dropped 1–3 questions.

| If you need… | Use | Why |
|---|---|---|
| Decisions in the request path, at high volume | **Jev** | 171 ms and $0.017 per 1k: 8–13× faster than the API models and 4–400× cheaper, with accuracy in the same band |
| Best accuracy, latency is OK | **GPT-6.1 Sol** | Perfect score at a fifth of Astra's price |
| Cheap API calls | **GPT-6 Luna** | Same accuracy band as Haiku 5.5, at about 60% of its cost |
| Free, private or offline | **Gemma 4 26B (A4B)** | 97% at 0.6 s on a laptop, faster than any API model |

**Takeaways**

- **Speed and cost are Jev's edge:** its p95 latency was 197 ms (slowest single call 247 ms), 8–13× faster than any API model here at p50 and 3.5× faster than the quickest local one. Per decision it cost about 4× less than the cheapest LLM (GPT-6 Luna) and about 400× less than GPT-6 Astra.
- **Accuracy is not a lead:** in September, Jev beat the fast model of the time (Haiku 4.5, 66/72) and trailed only Opus 5 (71/72). Haiku 5.5 now edges it (69 vs 68), and GPT-6.1 Sol and GPT-6 Astra got all 72 right.
- **Local models vary a lot:** Gemma 4 26B (A4B) matched Opus 5.5 and GPT-6 Luna. Qwen 3.6 35B (A3B) is just as fast but flagged ordinary messages as phishing. The small Gemma 4 E4B handled routing but not yes/no or severity.
- **Calibration:** on routing, Jev (ECE 0.025) matched the GPT models (0.023–0.030) and beat every Claude model (0.08–0.13). On severity, the Claude models were the least calibrated of the API models (ECE 0.15–0.25); only Gemma 4 E4B was worse (0.38).
- **Where Jev missed:** adjacent severity levels (low vs medium), and the same login-plus-browser-bug ticket (`sr-21`) that Haiku, Sonnet and Opus also missed.

Full per-task tables, calibration metrics and every miss: [`docs/results-2026-10-14.md`](docs/results-2026-10-14.md).

> **Caveats:** a small hand-labeled set (72 examples) and a single run per model. Latency is measured end-to-end from one laptop, including network. Every LLM ran with its default settings (including default thinking and effort) through `system-one-adapter`: Claude via the Anthropic API, GPT via the OpenAI Responses API, local models via LM Studio (where both Qwen models answered without thinking). Local models also see the response schema in their system prompt, since local servers don't show it to the model the way the hosted APIs do (see [OpenAI and local models](#openai-and-local-models)). Prices are list prices as of 2026-10-14. Treat these results as directional, and add your own tasks for your use case.

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
cp .env.example .env        # add TYPESAFE_API_KEY and ANTHROPIC_API_KEY (OPENAI_API_KEY optional)

jev-bench tasks                                   # list tasks
jev-bench run --limit 5                           # quick sanity run
jev-bench run                                     # full run: jev-latest vs claude-opus-5-5
jev-bench run --models jev-latest claude-opus-5-5 claude-haiku-5-5
```

Each run writes `results/<timestamp>/records.jsonl` (every call, with its probabilities) and `report.md`. To merge several runs into one report, as for the results above, run `jev-bench report results/<run-a> results/<run-b> ...`.

## OpenAI and local models

Model ids pick the backend: `jev*` goes to TypeSafe, `openai:<id>` to the OpenAI API, `local:<id>` to an OpenAI-compatible server on your machine, and anything else to Claude.

```bash
pip install -e '.[dev,openai]'

# OpenAI (set OPENAI_API_KEY in .env)
jev-bench run --models jev-latest openai:gpt-6-luna openai:gpt-6.1-sol

# Local: point JEVBENCH_LOCAL_BASE_URL at your server
JEVBENCH_LOCAL_BASE_URL=http://localhost:11434/v1 jev-bench run --models local:qwen3.6:35b   # Ollama
JEVBENCH_LOCAL_BASE_URL=http://localhost:1234/v1  jev-bench run --models local:gemma-4-26b-a4b-it-mlx   # LM Studio
JEVBENCH_LOCAL_BASE_URL=http://localhost:8080/v1  jev-bench run --models local:<model-id>    # llama.cpp llama-server
```

Local models are costed at $0, and their latency depends on your hardware. Local servers only use the response schema to constrain output, without showing it to the model, so the `local:` backend also puts the schema (which holds the questions) in the system prompt. LM Studio with MLX builds was the fastest setup on Apple Silicon in our runs; load the model first (`lms load <id>`) so load time isn't counted as latency.

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
