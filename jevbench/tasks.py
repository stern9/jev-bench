"""Load task definitions from tasks/*.json.

A task is one typed question (choice | score | noul) plus labeled examples:

    {
      "name": "support_routing",
      "description": "...",
      "question": {"type": "choice", "instructions": "...", "criteria": {...}},
      "examples": [{"id": "sr-01", "state": "...", "expected": "billing"}]
    }

`expected` is a label for choice, an integer level for score, and a bool for noul.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from typesafe_sdk import Choice, Noul, Score

TASKS_DIR = Path(__file__).resolve().parent.parent / "tasks"
QUESTION_KEY = "answer"


@dataclass(frozen=True)
class Example:
    id: str
    state: str
    expected: Any


@dataclass(frozen=True)
class Task:
    name: str
    description: str
    kind: str
    spec: dict[str, Any]
    examples: list[Example]

    def question(self):
        args = {k: v for k, v in self.spec.items() if k != "type"}
        return {QUESTION_KEY: {"choice": Choice, "score": Score, "noul": Noul}[self.kind](**args)}


def load_task(path: Path) -> Task:
    raw = json.loads(path.read_text())
    spec = raw["question"]
    kind = spec["type"]
    examples = [Example(e["id"], e["state"], e["expected"]) for e in raw["examples"]]
    for e in examples:
        if kind == "choice" and e.expected not in spec["criteria"]:
            raise ValueError(f"{path.name}:{e.id}: unknown label {e.expected!r}")
        if kind == "score" and not (isinstance(e.expected, int) and 0 <= e.expected < len(spec["criteria"])):
            raise ValueError(f"{path.name}:{e.id}: score must be 0..{len(spec['criteria']) - 1}")
        if kind == "noul" and not isinstance(e.expected, bool):
            raise ValueError(f"{path.name}:{e.id}: noul expected must be true/false")
    return Task(raw["name"], raw.get("description", ""), kind, spec, examples)


def load_tasks(names: list[str] | None = None) -> list[Task]:
    tasks = [load_task(p) for p in sorted(TASKS_DIR.glob("*.json"))]
    if names:
        missing = set(names) - {t.name for t in tasks}
        if missing:
            raise SystemExit(f"unknown task(s): {', '.join(sorted(missing))}")
        tasks = [t for t in tasks if t.name in names]
    return tasks
