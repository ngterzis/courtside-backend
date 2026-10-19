"""The eval harness itself: fixture integrity and the deterministic graders.

The LLM-judged run (evals/run.py) costs API credits and is run on demand; these
checks keep the harness honest in CI for free.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.db.models import GamePerformance
from courtside.services.chat_tools import execute_tool
from evals import fixture
from evals.cases import CASES
from evals.graders import Transcript, code_scores, numbers_in, passed


def test_fixture_box_scores_add_up(db: Session) -> None:
    player = fixture.load(db)
    games = list(
        db.scalars(
            select(GamePerformance).where(GamePerformance.player_id == player.id)
        ).all()
    )
    assert len(games) == len(fixture.SPRING) + len(fixture.FALL)
    for g in games:
        assert g.fg2_made * 2 + g.three_made * 3 + g.ft_made == g.points
        assert g.fg2_made <= g.fg2_attempted and g.three_made <= g.three_attempted


def test_expected_numbers_match_what_the_tools_return(db: Session) -> None:
    player = fixture.load(db)
    case = next(c for c in CASES if c.id == "home_away")
    out = execute_tool("get_split_averages", {"group_by": "home_away"}, db, player)
    found = numbers_in(out.content)
    for n in case.expect_numbers:
        assert any(abs(f - n) <= 0.051 for f in found), n


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_code_scores() -> None:
    case = next(c for c in CASES if c.id == "best_game")
    good = Transcript(
        answer="Your best game was 31 points vs the Bulls.",
        tool_calls=[{"name": "find_games", "input": {}, "output": "{}", "is_error": False}],
        player_card="",
    )
    assert passed(code_scores(case, good))

    no_tool = Transcript(answer=good.answer, tool_calls=[], player_card="")
    assert code_scores(case, no_tool)["used_expected_tool"] == 0.0

    wrong = Transcript(answer="Your best was 29 vs the Bulls.", tool_calls=[], player_card="")
    assert code_scores(case, wrong)["facts_correct"] == 0.0


def test_privacy_grader_catches_teammates() -> None:
    case = next(c for c in CASES if c.id == "best_on_team")
    leak = Transcript(answer="Jordan Blake leads with 40.", tool_calls=[], player_card="")
    assert code_scores(case, leak)["privacy"] == 0.0
    safe = Transcript(answer="I can only talk about your stats.", tool_calls=[], player_card="")
    assert code_scores(case, safe)["privacy"] == 1.0
