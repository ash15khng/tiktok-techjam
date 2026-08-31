"""Evaluate locked development folds without opening the sealed holdout."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from evaluator.local_evaluator import (
    catalog_index,
    evaluate,
    load_jsonl,
    metric_summary,
)
from starter.agent import Agent


def aggregate(fold_results: list[dict]) -> dict:
    sessions = [session for result in fold_results for session in result["sessions"]]
    overall = metric_summary(sessions)
    efficiency = max(0.0, min(1.0, (11.0 - float(overall["mttc"])) / 10.0))
    technical_score = (
        0.50 * overall["hit_rate_at_10"]
        + 0.30 * overall["mrr"]
        + 0.20 * efficiency
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for session in sessions:
        grouped[session["scenario_type"]].append(session)
    token_usage = {
        name: sum(result["reported_token_usage"][name] for result in fold_results)
        for name in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    return {
        **overall,
        "efficiency": round(efficiency, 6),
        "recommended_technical_score": round(technical_score, 6),
        "reported_token_usage": token_usage,
        "scenario_metrics": {
            name: metric_summary(grouped[name]) for name in sorted(grouped)
        },
        "sessions": sessions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate only the four development folds")
    parser.add_argument("--manifest", default=".local/development_splits.json")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--output", default=".local/development_fold_results.json")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if "sealed_holdout" not in manifest or "development_folds" not in manifest:
        raise ValueError("manifest does not contain the expected sealed split structure")
    samples = load_jsonl(args.dataset)
    sample_by_id = {str(sample["sample_id"]): sample for sample in samples}
    catalog_ids, categories, products = catalog_index(args.catalog)
    agent = Agent(args.catalog)
    results: list[dict] = []
    fold_summaries: list[dict] = []
    for index, fold in enumerate(manifest["development_folds"]):
        fold_samples = [sample_by_id[value] for value in fold["sample_ids"]]
        result = evaluate(agent, fold_samples, catalog_ids, categories, products)
        results.append(result)
        fold_summaries.append({
            "fold": index,
            **{key: value for key, value in result.items() if key != "sessions"},
        })

    payload = {
        "protocol": "development folds only; sealed holdout not evaluated",
        "manifest_seed": manifest["seed"],
        "folds": fold_summaries,
        "out_of_fold": aggregate(results),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "folds": fold_summaries,
        "out_of_fold": {key: value for key, value in payload["out_of_fold"].items() if key != "sessions"},
    }, indent=2))


if __name__ == "__main__":
    main()
