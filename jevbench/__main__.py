"""CLI.

  jev-bench tasks                                   list tasks
  jev-bench run [--models ...] [--tasks ...] [--limit N]
  jev-bench report results/<run-dir>                re-render a report
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .report import render
from .tasks import load_tasks

RESULTS = Path(__file__).resolve().parent.parent / "results"
DEFAULT_MODELS = ["jev-latest", "claude-opus-5"]


def load_dotenv(path: Path) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not key.startswith("#") and value.strip():
                os.environ.setdefault(key.strip(), value.strip())


def cmd_tasks(_args) -> None:
    for t in load_tasks():
        print(f"{t.name:<18} {t.kind:<7} {len(t.examples):>3} examples  {t.description}")


def cmd_run(args) -> None:
    from .runner import run  # imported late so `tasks` works without SDK credentials

    tasks = load_tasks(args.tasks)
    run_dir = RESULTS / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True)
    out = (run_dir / "records.jsonl").open("w")
    total = len(args.models) * sum(len(t.examples[:args.limit]) for t in tasks)
    done = 0

    def on_record(rec):
        nonlocal done
        done += 1
        out.write(json.dumps(rec.to_dict()) + "\n")
        out.flush()
        mark = "ERR" if rec.error else ("ok " if rec.correct else "miss")
        print(f"[{done:>4}/{total}] {rec.model:<18} {rec.task:<18} {rec.example_id:<8} {mark} "
              f"{(rec.latency_s or 0) * 1000:>7,.0f} ms" + (f"  {rec.error}" if rec.error else ""), flush=True)

    run(tasks, args.models, limit=args.limit, on_record=on_record)
    out.close()
    write_report(run_dir)


def write_report(run_dir: Path) -> None:
    records = [json.loads(l) for l in (run_dir / "records.jsonl").read_text().splitlines() if l.strip()]
    report = render(records, f"jev-bench run {run_dir.name}")
    (run_dir / "report.md").write_text(report)
    print("\n" + report)
    print(f"saved {run_dir / 'report.md'}")


def main(argv: list[str] | None = None) -> None:
    load_dotenv(Path.cwd() / ".env")
    p = argparse.ArgumentParser(prog="jev-bench", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tasks", help="list tasks").set_defaults(fn=cmd_tasks)
    r = sub.add_parser("run", help="run tasks against models")
    r.add_argument("--models", nargs="+", default=DEFAULT_MODELS,
                   help=f"model ids; jev* goes to TypeSafe, anything else to Claude (default: {' '.join(DEFAULT_MODELS)})")
    r.add_argument("--tasks", nargs="+", help="task names (default: all)")
    r.add_argument("--limit", type=int, help="max examples per task")
    r.set_defaults(fn=cmd_run)
    rep = sub.add_parser("report", help="re-render report.md for a run directory")
    rep.add_argument("run_dir", type=Path)
    rep.set_defaults(fn=lambda a: write_report(a.run_dir))
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
