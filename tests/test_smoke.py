"""Offline smoke test: fake model answers, real task files, SDK question types, scoring and report."""
import random
from types import SimpleNamespace

from jevbench import runner
from jevbench.metrics import summarize
from jevbench.report import render
from jevbench.tasks import load_tasks


def fake_caller(accuracy):
    rng = random.Random(0)

    def call(state, questions):
        task = next(t for t in load_tasks() for e in t.examples if e.state == state)
        ex = next(e for e in task.examples if e.state == state)
        right = rng.random() < accuracy
        if task.kind == "choice":
            labels = list(task.spec["criteria"])
            pick = ex.expected if right else next(l for l in labels if l != ex.expected)
            probs = {l: (0.8 if l == pick else 0.2 / (len(labels) - 1)) for l in labels}
            answer = SimpleNamespace(choice=pick, confidence=0.8, probabilities=probs)
        elif task.kind == "score":
            n = len(task.spec["criteria"])
            pick = ex.expected if right else (ex.expected + 1) % n
            answer = SimpleNamespace(score=float(pick), probabilities={i: (0.7 if i == pick else 0.1) for i in range(n)})
        else:
            answer = SimpleNamespace(noul=0.9 if ex.expected == right else 0.1)
        return SimpleNamespace(answers={"answer": answer}, usage=SimpleNamespace(input_tokens=120, output_tokens=0))
    return call


def test_end_to_end(monkeypatch):
    tasks = load_tasks()
    for t in tasks:
        t.question()  # builds real typesafe_sdk Choice/Score/Noul objects
    monkeypatch.setattr(runner, "make_caller",
                        lambda model, stack: fake_caller(0.9 if model.startswith("jev") else 0.95))
    records = [r.to_dict() for r in runner.run(tasks, ["jev-latest", "claude-opus-5"])]
    assert len(records) == 2 * sum(len(t.examples) for t in tasks)
    assert not any(r["error"] for r in records)
    rows = summarize(records)
    assert len(rows) == 2 * len(tasks)
    assert all(0 <= s.accuracy <= 1 and s.ece is not None and s.brier is not None for s in rows)
    jev = next(s for s in rows if s.model == "jev-latest")
    assert abs(jev.cost_per_1k - 120 * 0.042 / 1e6 * 1000) < 1e-9
    md = render(records, "smoke")
    assert "## Headline" in md and "| Model | Accuracy" in md


def test_merge_runs(tmp_path, monkeypatch):
    import json
    from jevbench import __main__ as cli
    monkeypatch.setattr(cli, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "make_caller", lambda model, stack: fake_caller(0.9))
    tasks = load_tasks(["phishing_check"])
    for name, models in [("20260101-000000", ["jev-latest", "claude-opus-5"]),
                         ("20260102-000000", ["jev-latest", "claude-haiku-4-5"])]:
        d = tmp_path / name
        d.mkdir()
        (d / "records.jsonl").write_text("".join(json.dumps(r.to_dict()) + "\n" for r in runner.run(tasks, models)))
    cli.main(["report", str(tmp_path / "20260101-000000"), str(tmp_path / "20260102-000000")])
    combined = next(tmp_path.glob("combined-*"))
    records = [json.loads(l) for l in (combined / "records.jsonl").read_text().splitlines()]
    assert {r["model"] for r in records} == {"jev-latest", "claude-opus-5", "claude-haiku-4-5"}
    assert len(records) == 3 * len(tasks[0].examples)  # duplicate jev rows collapsed
    assert "claude-haiku-4-5" in (combined / "report.md").read_text()
