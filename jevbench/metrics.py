"""Scoring: accuracy, latency, calibration and cost per model and task."""
from __future__ import annotations

import statistics
from dataclasses import dataclass

# USD per million tokens (input, output). Update when prices change.
PRICES = {
    "jev": (0.042, 0.0),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-6-astra": (10.00, 50.00),
    "gpt-6.1-sol": (2.00, 10.00),
    "gpt-6-luna": (0.10, 0.50),
}


def price_for(model: str) -> tuple[float, float] | None:
    if model.startswith("jev"):
        return PRICES["jev"]
    if model.startswith("local:"):
        return (0.0, 0.0)  # runs on your own hardware
    return PRICES.get(model.removeprefix("openai:"))


@dataclass
class Summary:
    task: str
    model: str
    n: int
    errors: int
    accuracy: float
    p50_ms: float | None
    p95_ms: float | None
    ece: float | None
    brier: float | None
    cost_per_1k: float | None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
    return values[idx]


def expected_calibration_error(records, bins: int = 5) -> float | None:
    """Mean |confidence - accuracy| across confidence bins, weighted by bin size."""
    scored = [r for r in records if r["error"] is None and r["confidence"] is not None]
    if not scored:
        return None
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        in_bin = [r for r in scored if lo < r["confidence"] <= hi or (b == 0 and r["confidence"] == 0)]
        if in_bin:
            conf = statistics.fmean(r["confidence"] for r in in_bin)
            acc = statistics.fmean(r["predicted"] == r["expected"] for r in in_bin)
            total += len(in_bin) / len(scored) * abs(conf - acc)
    return total


def brier(records) -> float | None:
    """Multiclass Brier score: mean squared error of the probability vector vs the one-hot truth."""
    scored = [r for r in records if r["error"] is None and r["probabilities"]]
    if not scored:
        return None
    out = []
    for r in scored:
        truth = str(r["expected"])
        out.append(sum((p - (1.0 if label == truth else 0.0)) ** 2 for label, p in r["probabilities"].items()))
    return statistics.fmean(out)


def summarize(records: list[dict]) -> list[Summary]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        groups.setdefault((r["task"], r["model"]), []).append(r)
    out = []
    for (task, model), rs in groups.items():
        ok = [r for r in rs if r["error"] is None]
        lat = [r["latency_s"] * 1000 for r in ok if r["latency_s"] is not None]
        cost = None
        price = price_for(model)
        if price and ok and all(r["input_tokens"] is not None for r in ok):
            per_call = statistics.fmean(
                (r["input_tokens"] * price[0] + (r["output_tokens"] or 0) * price[1]) / 1e6 for r in ok)
            cost = per_call * 1000
        out.append(Summary(
            task=task, model=model, n=len(rs), errors=len(rs) - len(ok),
            accuracy=sum(r["predicted"] == r["expected"] for r in ok) / len(rs),
            p50_ms=percentile(lat, 0.5), p95_ms=percentile(lat, 0.95),
            ece=expected_calibration_error(rs), brier=brier(rs), cost_per_1k=cost,
        ))
    return out
