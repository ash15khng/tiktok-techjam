"""Reproducible natural-language benchmark independent of the public simulator."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

from submission.src.agent import ShoppingAgent
from submission.src.contracts import DisabledSemanticParser, SemanticParser


DEFAULT_CASES = Path(__file__).with_name("hard_cases.json")


def load_cases(path: str | Path = DEFAULT_CASES) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_hard_cases(
    *,
    catalog_path: str | Path = "data/catalog.jsonl",
    cases_path: str | Path = DEFAULT_CASES,
    semantic_parser: SemanticParser | None = None,
) -> dict:
    fixture = load_cases(cases_path)
    agent = ShoppingAgent(
        catalog_path,
        semantic_parser=semantic_parser or DisabledSemanticParser(),
    )
    sessions: list[dict] = []
    prompt_tokens = 0
    completion_tokens = 0
    for case in fixture["cases"]:
        case_id = str(case["case_id"])
        target = str(case["target_parent_asin"])
        messages = [str(message) for message in case["messages"]]
        score_from_turn = int(case.get("score_from_turn", 1))
        agent.reset(f"hard::{case_id}", dict(case.get("profile") or {}))
        first_hit_turn: int | None = None
        best_rank: int | None = None
        turn_rows: list[dict] = []
        for turn, message in enumerate(messages, 1):
            response = agent.respond(f"hard::{case_id}", message, turn, 10)
            usage = response.get("usage") if isinstance(response, dict) else None
            if isinstance(usage, dict):
                prompt_tokens += max(0, int(usage.get("prompt_tokens") or 0))
                completion_tokens += max(0, int(usage.get("completion_tokens") or 0))
            ranked = [item["parent_asin"] for item in response.get("recommendations", [])]
            rank = ranked.index(target) + 1 if target in ranked else None
            turn_rows.append(
                {
                    "turn": turn,
                    "message": message,
                    "rank": rank,
                    "ask_attribute": response.get("ask_attribute"),
                }
            )
            if turn >= score_from_turn and rank is not None and first_hit_turn is None:
                first_hit_turn = turn
                best_rank = rank
                break
        sessions.append(
            {
                "case_id": case_id,
                "challenge": case["challenge"],
                "hit": first_hit_turn is not None,
                "first_hit_turn": first_hit_turn,
                "best_rank": best_rank,
                "reciprocal_rank": 0.0 if best_rank is None else 1.0 / best_rank,
                "turns": turn_rows,
            }
        )

    count = len(sessions)
    max_scripted_turns = max(len(case["messages"]) for case in fixture["cases"])
    hit_rate = sum(int(row["hit"]) for row in sessions) / count
    mrr = statistics.fmean(row["reciprocal_rank"] for row in sessions)
    mttc = statistics.fmean(
        row["first_hit_turn"] if row["first_hit_turn"] is not None else max_scripted_turns + 1
        for row in sessions
    )
    return {
        "fixture_version": fixture["version"],
        "sample_count": count,
        "hit_rate_at_script_end": round(hit_rate, 6),
        "mrr": round(mrr, 6),
        "mttc": round(mttc, 6),
        "challenge_counts": dict(sorted(Counter(row["challenge"] for row in sessions).items())),
        "reported_token_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "agent_diagnostics": agent.diagnostics(),
        "sessions": sessions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--output")
    args = parser.parse_args()
    result = evaluate_hard_cases(catalog_path=args.catalog, cases_path=args.cases)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "sessions"}, indent=2))


if __name__ == "__main__":
    main()
