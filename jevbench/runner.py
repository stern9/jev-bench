"""Run tasks through Jev (TypeSafe API) or Claude (via system-one-adapter).

Both backends take the same `system_one(state, questions)` call and return a
typesafe_sdk.SystemOneResponse, so every model is scored the same way.
Latency is wall-clock time around each call, measured the same for all models.
"""
from __future__ import annotations

import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from typing import Any, Callable

from system_one_adapter import SystemOneAdapterClient
from system_one_adapter.providers.anthropic import AnthropicProvider
from typesafe_sdk import TypeSafeClient

from .tasks import QUESTION_KEY, Example, Task


@dataclass
class Record:
    task: str
    model: str
    example_id: str
    expected: Any
    predicted: Any = None
    confidence: float | None = None        # probability assigned to the predicted answer
    p_expected: float | None = None        # probability assigned to the correct answer
    probabilities: dict | None = None
    latency_s: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None

    @property
    def correct(self) -> bool:
        return self.error is None and self.predicted == self.expected

    def to_dict(self) -> dict:
        return asdict(self)


def is_jev(model: str) -> bool:
    return model.startswith("jev")


def make_caller(model: str, stack: ExitStack) -> Callable:
    if is_jev(model):
        client = stack.enter_context(TypeSafeClient(model=model))
        return lambda state, questions: client.system_one(state, questions)
    client = stack.enter_context(SystemOneAdapterClient(
        structured_outputs=True,
        llm_answer_mode="probabilities",
        normalize_probabilities=True,
        n_retry_malformed_structure=2,
        model=AnthropicProvider(model, max_tokens=16000),
    ))
    return lambda state, questions: client.system_one(state, questions)


def parse_answer(task: Task, answer) -> tuple[Any, float, dict]:
    """Return (predicted, confidence in the prediction, probability per answer)."""
    if task.kind == "choice":
        probs = dict(answer.probabilities)
        return answer.choice, probs.get(answer.choice, answer.confidence), probs
    if task.kind == "score":
        probs = {int(k): v for k, v in answer.probabilities.items()}
        level = max(probs, key=probs.get)
        return level, probs[level], probs
    p_true = float(answer.noul)
    probs = {True: p_true, False: 1 - p_true}
    predicted = p_true >= 0.5
    return predicted, probs[predicted], probs


def run_example(task: Task, ex: Example, model: str, call: Callable) -> Record:
    rec = Record(task.name, model, ex.id, ex.expected)
    start = time.perf_counter()
    try:
        response = call(ex.state, task.question())
    except Exception as e:  # record and keep going; one bad call shouldn't sink the run
        rec.latency_s = time.perf_counter() - start
        rec.error = f"{type(e).__name__}: {e}"[:300]
        return rec
    rec.latency_s = time.perf_counter() - start
    rec.predicted, rec.confidence, probs = parse_answer(task, response.answers[QUESTION_KEY])
    rec.probabilities = {str(k): v for k, v in probs.items()}
    rec.p_expected = probs.get(ex.expected, 0.0)
    usage = response.usage
    rec.input_tokens = getattr(usage, "input_tokens_total", None) or getattr(usage, "input_tokens", None)
    rec.output_tokens = getattr(usage, "output_tokens_total", None) or getattr(usage, "output_tokens", None)
    return rec


def run(tasks: list[Task], models: list[str], limit: int | None = None,
        on_record: Callable[[Record], None] | None = None) -> list[Record]:
    records: list[Record] = []
    for model in models:
        with ExitStack() as stack:
            call = make_caller(model, stack)
            for task in tasks:
                for ex in task.examples[:limit]:
                    rec = run_example(task, ex, model, call)
                    records.append(rec)
                    if on_record:
                        on_record(rec)
    return records
