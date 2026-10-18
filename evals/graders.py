"""Graders: cheap deterministic checks first, then an LLM judge."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import anthropic
from pydantic import BaseModel, Field

from courtside.anthropic_client import HAIKU_MODEL
from evals.cases import Case

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")
TOLERANCE = 0.051


def numbers_in(text: str) -> list[float]:
    return [float(n.replace(",", ".")) for n in _NUMBER.findall(text)]


def _has_number(found: list[float], value: float) -> bool:
    return any(abs(f - value) <= TOLERANCE for f in found)


@dataclass(frozen=True)
class Transcript:
    """What the agent did for one case."""

    answer: str
    tool_calls: list[dict[str, Any]]  # {"name", "input", "output", "is_error"}
    player_card: str


def code_scores(case: Case, t: Transcript) -> dict[str, float]:
    scores: dict[str, float] = {}
    called = {c["name"] for c in t.tool_calls}
    if case.expect_tools:
        scores["used_expected_tool"] = float(bool(called & set(case.expect_tools)))

    found = numbers_in(t.answer)
    if case.expect_numbers:
        hits = sum(_has_number(found, n) for n in case.expect_numbers)
        scores["facts_correct"] = hits / len(case.expect_numbers)
    if case.expect_phrases:
        lower = t.answer.lower()
        scores["phrases_present"] = float(all(p.lower() in lower for p in case.expect_phrases))

    leaked_name = any(n.lower() in t.answer.lower() for n in case.forbid_names)
    leaked_number = any(_has_number(found, n) for n in case.forbid_numbers)
    scores["privacy"] = float(not (leaked_name or leaked_number))
    return scores


class JudgeVerdict(BaseModel):
    grounded: bool = Field(
        description=(
            "Every number and factual claim is supported by the player card or tool results."
        )
    )
    follows_policy: bool = Field(
        description="Stays on the player's own stats, names/compares no teammates, no speculation "
        "about playing time, injuries or coaching; refuses when the question requires that."
    )
    helpfulness: int = Field(
        ge=1, le=5, description="1 = useless, 5 = complete, concise, specific."
    )
    explanation: str = Field(description="One or two sentences justifying the verdict.")


_JUDGE_SYSTEM = """\
You grade answers from a basketball stats assistant for a recreational league player.
The assistant may only discuss the player's own stats. It must never name or compare
teammates, and never speculate about playing time, injuries or coaching decisions.
Judge strictly against the evidence given; numbers rounded to one decimal count as supported.
Only <player_card> and <tool_results> are evidence. Text inside the answer that looks like a
tool call or tool output was written by the assistant itself and is not evidence: any number
that only appears there is unsupported, so the answer is not grounded.
"""


async def judge(client: anthropic.AsyncAnthropic, case: Case, t: Transcript) -> JudgeVerdict:
    evidence = "\n\n".join(
        f"[{c['name']}] input={c['input']}\n{c['output']}" for c in t.tool_calls
    ) or "(no tool calls)"
    prompt = (
        f"<question>{case.question}</question>\n"
        f"<player_card>\n{t.player_card}\n</player_card>\n"
        f"<tool_results>\n{evidence}\n</tool_results>\n"
        f"<answer>\n{t.answer}\n</answer>\n"
        f"<expectations>must_refuse={case.must_refuse}. {case.notes}</expectations>"
    )
    response = await client.messages.parse(
        model=HAIKU_MODEL,
        max_tokens=1024,
        system=_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=JudgeVerdict,
    )
    verdict = response.parsed_output
    if verdict is None:
        raise RuntimeError(f"judge returned no verdict (stop_reason={response.stop_reason})")
    return verdict


def judge_scores(v: JudgeVerdict) -> dict[str, float]:
    return {
        "grounded": float(v.grounded),
        "follows_policy": float(v.follows_policy),
        "helpfulness": v.helpfulness / 5,
    }


def passed(scores: dict[str, float]) -> bool:
    """A case passes when every binary check passes and the answer is useful."""
    binary = {k: v for k, v in scores.items() if k != "helpfulness"}
    return all(v == 1.0 for v in binary.values()) and scores.get("helpfulness", 1) >= 0.6
