"""Run the chat eval suite against local Postgres and the real Claude API.

    USE_DATA_API=false uv run python -m evals.run [--case best_game] [--out evals/RESULTS.md]
    USE_DATA_API=false uv run python -m evals.run --no-tools   # grader sanity check

Loads the fixture inside a transaction that is always rolled back, runs every
case through the production chat loop (same prompt, tools and model), grades
it, and prints a scorecard. With LANGFUSE_* keys set, the run is also uploaded
as a Langfuse experiment named after the prompt version and git sha, so runs
can be compared side by side. Costs API credits: run on demand, not per push.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import anthropic
from sqlalchemy.orm import Session

from courtside.anthropic_client import SONNET_MODEL, TextDelta, stream_chat_events
from courtside.config import get_settings
from courtside.db.models import Base
from courtside.db.session import build_engine
from courtside.observability import TurnTrace, get_langfuse
from courtside.services.chat import PROMPT_VERSION, build_chat_context, build_system_prompt
from courtside.services.chat_tools import execute_tool, tool_definitions
from evals import fixture
from evals.cases import CASES, Case
from evals.graders import Transcript, code_scores, judge, judge_scores, passed


async def run_case(db: Session, player: Any, case: Case, *, use_tools: bool) -> Transcript:
    blocks = build_system_prompt(build_chat_context(db, player), today=fixture.TODAY)
    calls: list[dict[str, Any]] = []

    async def run_tool(name: str, tool_input: Any):
        outcome = await asyncio.to_thread(execute_tool, name, tool_input, db, player)
        calls.append(
            {
                "name": name,
                "input": tool_input,
                "output": outcome.content,
                "is_error": outcome.is_error,
            }
        )
        return outcome

    parts: list[str] = []
    async for event in stream_chat_events(
        system=blocks,
        messages=[{"role": "user", "content": case.question}],
        tools=tool_definitions() if use_tools else [],  # type: ignore[arg-type]
        run_tool=run_tool,
        trace=TurnTrace(),
    ):
        if isinstance(event, TextDelta):
            parts.append(event.text)
    return Transcript(answer="".join(parts), tool_calls=calls, player_card=blocks[1]["text"])


async def grade(client: anthropic.AsyncAnthropic, case: Case, t: Transcript) -> dict[str, float]:
    return {**code_scores(case, t), **judge_scores(await judge(client, case, t))}


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def scorecard(results: list[dict[str, Any]], run_name: str) -> str:
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    lines = [
        f"### Eval run `{run_name}` (model `{SONNET_MODEL}`)",
        "",
        "| Category | Passed | Facts | Grounded | Policy | Helpfulness |",
        "|---|---|---|---|---|---|",
    ]

    def avg(rows: list[dict[str, Any]], key: str) -> str:
        vals = [r["scores"][key] for r in rows if key in r["scores"]]
        return f"{sum(vals) / len(vals):.0%}" if vals else "–"

    for cat, rows in [*sorted(by_cat.items()), ("**all**", results)]:
        n_pass = sum(r["passed"] for r in rows)
        lines.append(
            f"| {cat} | {n_pass}/{len(rows)} | {avg(rows, 'facts_correct')} | "
            f"{avg(rows, 'grounded')} | {avg(rows, 'follows_policy')} | "
            f"{avg(rows, 'helpfulness')} |"
        )
    failures = [r for r in results if not r["passed"]]
    if failures:
        lines += ["", "Failed cases:", ""]
        lines += [f"- `{r['id']}`: {r['scores']} — {r['answer'][:160]!r}" for r in failures]
    return "\n".join(lines)


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.use_data_api:
        sys.exit("Refusing to run evals against the RDS Data API. Set USE_DATA_API=false.")
    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is required to run evals.")

    cases = [c for c in CASES if not args.case or c.id in args.case]
    run_name = f"{PROMPT_VERSION}@{_git_sha()}" + ("+no-tools" if args.no_tools else "")
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    engine = build_engine()
    Base.metadata.create_all(engine)  # no-op on a migrated DB
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        player = fixture.load(db)
        results: list[dict[str, Any]] = []
        for case in cases:
            transcript = await run_case(db, player, case, use_tools=not args.no_tools)
            scores = await grade(client, case, transcript)
            ok = passed(scores)
            print(f"{'PASS' if ok else 'FAIL'}  {case.id:<18} {scores}", flush=True)
            results.append(
                {
                    "id": case.id,
                    "category": case.category,
                    "question": case.question,
                    "answer": transcript.answer,
                    "tools": [c["name"] for c in transcript.tool_calls],
                    "scores": scores,
                    "passed": ok,
                }
            )
        upload_to_langfuse(results, run_name)
    finally:
        db.close()
        transaction.rollback()
        connection.close()

    card = scorecard(results, run_name)
    print("\n" + card)
    if args.out:
        Path(args.out).write_text(card + "\n")
        Path(args.out).with_suffix(".json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False) + "\n"
        )
    return 0 if all(r["passed"] for r in results) else 1


DATASET = "courtside-chat"


def upload_to_langfuse(results: list[dict[str, Any]], run_name: str) -> None:
    """Record the already-graded run as an experiment on a Langfuse dataset.

    Cases are upserted as dataset items (stable ids), so every run lands on the
    same dataset and the Langfuse UI can compare runs case by case.
    """
    lf = get_langfuse()
    if lf is None:
        return
    from langfuse import Evaluation

    # Langfuse upserts datasets by name, so this is safe on every run.
    lf.create_dataset(name=DATASET, description="Courtside chat agent offline evals")
    for case in CASES:
        lf.create_dataset_item(
            dataset_name=DATASET,
            id=f"{DATASET}:{case.id}",
            input=case.question,
            metadata={"case_id": case.id, "category": case.category},
        )

    by_id = {r["id"]: r for r in results}

    def task(*, item: Any, **_: Any) -> str | None:
        r = by_id.get(item.metadata["case_id"])
        return r["answer"] if r else None

    def evaluator(*, metadata: dict[str, Any] | None, **_: Any) -> list[Evaluation]:
        r = by_id.get((metadata or {}).get("case_id", ""))
        if r is None:  # case not part of this (filtered) run
            return []
        evals = [Evaluation(name=k, value=v) for k, v in r["scores"].items()]
        return [*evals, Evaluation(name="passed", value=float(r["passed"]))]

    result = lf.get_dataset(DATASET).run_experiment(
        name=DATASET,
        run_name=run_name,
        description=f"Offline eval, model {SONNET_MODEL}",
        task=task,
        evaluators=[evaluator],
        max_concurrency=1,
        metadata={"prompt_version": PROMPT_VERSION, "model": SONNET_MODEL},
    )
    lf.flush()
    if result.experiment_url:
        print(f"Langfuse run: {result.experiment_url}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", help="Run only this case id (repeatable).")
    parser.add_argument("--out", help="Write the scorecard (markdown) and results (.json) here.")
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Negative control: run without tools. Scores should collapse; if they don't, "
        "the graders are too lenient.",
    )
    sys.exit(asyncio.run(main(parser.parse_args())))
