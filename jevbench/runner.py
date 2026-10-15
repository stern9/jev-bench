"""Run tasks through Jev (TypeSafe API) or an LLM via system-one-adapter.

Model ids: `jev*` goes to TypeSafe, `openai:<model>` to the OpenAI API,
`local:<model>` to an OpenAI-compatible local server (llama.cpp, LM Studio,
Ollama) at JEVBENCH_LOCAL_BASE_URL, and anything else to Claude.

Both backends take the same `system_one(state, questions)` call and return a
typesafe_sdk.SystemOneResponse, so every model is scored the same way.
Latency is wall-clock time around each call, measured the same for all models.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from typing import Any, Callable

from system_one_adapter import SystemOneAdapterClient
from system_one_adapter.providers.anthropic import AnthropicProvider
from system_one_adapter.providers.base import Message, ProviderResult, translating
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


def _local_provider(model_name: str):
    from system_one_adapter.providers.openai import OpenAIProvider

    class LocalProvider(OpenAIProvider):
        """OpenAI-compatible local server (Ollama, LM Studio, llama.cpp).

        Hosted APIs show the response schema to the model, and the schema's field
        descriptions carry the actual questions. Local servers only use it to constrain
        decoding, so the model would answer without seeing the question; we put the
        schema in the system prompt. Some servers (LM Studio with Qwen) also return
        the JSON in `reasoning_content` and leave `content` empty.
        """

        def request(self, messages: list[Message], *, schema: dict[str, Any], structured: bool) -> ProviderResult:
            hint = "Respond with JSON matching this schema. Each field's description holds the question to answer:\n" + json.dumps(schema)
            rendered = [{"role": m.role, "content": m.content} for m in messages]
            if rendered and rendered[0]["role"] == "system":
                rendered[0]["content"] += "\n\n" + hint
            else:
                rendered.insert(0, {"role": "system", "content": hint})
            kwargs: dict[str, Any] = {"model": self.model_name, "messages": rendered}
            if structured:
                kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": "evaluation", "schema": schema, "strict": True}}
            with translating(self.translate_error):
                response = self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            if choice.finish_reason not in ("stop", None):
                raise RuntimeError(f"local completion did not complete: {choice.finish_reason}")
            text = choice.message.content or (choice.message.model_extra or {}).get("reasoning_content") or ""
            return ProviderResult(
                text=text,
                input_tokens=getattr(response.usage, "prompt_tokens", None),
                output_tokens=getattr(response.usage, "completion_tokens", None),
            )

    return LocalProvider(
        model_name,
        base_url=os.environ.get("JEVBENCH_LOCAL_BASE_URL", "http://localhost:8080/v1"),
        api_key=os.environ.get("JEVBENCH_LOCAL_API_KEY", "local"),
    )


def make_provider(model: str):
    if model.startswith("openai:"):
        from system_one_adapter.providers.openai import OpenAIProvider
        return OpenAIProvider(model.removeprefix("openai:"))
    if model.startswith("local:"):
        return _local_provider(model.removeprefix("local:"))
    return AnthropicProvider(model, max_tokens=16000)


def make_caller(model: str, stack: ExitStack) -> Callable:
    if is_jev(model):
        client = stack.enter_context(TypeSafeClient(model=model))
        return lambda state, questions: client.system_one(state, questions)
    client = stack.enter_context(SystemOneAdapterClient(
        # Native structured outputs reject very large choice schemas (e.g. 75 categories);
        # JEVBENCH_STRUCTURED_OUTPUTS=0 falls back to prompt-based JSON with retries.
        structured_outputs=os.environ.get("JEVBENCH_STRUCTURED_OUTPUTS", "1") != "0",
        llm_answer_mode="probabilities",
        normalize_probabilities=True,
        n_retry_malformed_structure=2,
        model=make_provider(model),
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
