#!/usr/bin/env python3
"""
inspect_session.py - Interactive session inspector and conversation viewer.

Allows you to run and view turn-by-turn multi-turn dialog simulations for any
sample in data/public_set.jsonl using your Agent.

Usage examples:
    python3 inspect_session.py
    python3 inspect_session.py --index 0
    python3 inspect_session.py --sample-id public_0002
    python3 inspect_session.py --scenario intent_override
    python3 inspect_session.py --scenario browsing --limit 3
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from evaluator.local_evaluator import (
    ALLOWED_ATTRIBUTES,
    MAX_TURNS,
    TOP_K,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
    normalize_recommendations,
)
from starter.agent import Agent


def run_single_session(
    agent: Agent,
    sample: dict,
    catalog_ids: set[str],
    categories: dict[str, list[str]],
    products: dict[str, dict],
    verbose: bool = True,
) -> dict:
    sample_id = sample.get("sample_id", "unknown")
    scenario_type = sample.get("scenario_type", "unknown")
    target_asin = str(sample["ground_truth"]["parent_asin"])
    target_product = products.get(target_asin, {})
    
    session_id = f"inspect_{uuid.uuid4().hex[:8]}"
    agent.reset(session_id, sample["user_profile"])
    
    effective_intent_card, effective_behavior = materialize_hidden_fields(sample, products)
    effective_sample = {
        **sample,
        "intent_card": effective_intent_card,
        "behavior": effective_behavior,
    }

    if verbose:
        print("=" * 75)
        print(f" SESSION: {sample_id} | Scenario: {scenario_type.upper()}")
        print("=" * 75)
        print(f"Target ASIN    : {target_asin}")
        print(f"Product Title  : {target_product.get('title')}")
        print(f"Categories     : {' > '.join(categories.get(target_asin, []))}")
        print(f"Price          : ${target_product.get('price')}")
        print(f"User Profile   : {sample['user_profile'].get('summary')}")
        print(f"Hard Constraints: {effective_intent_card.get('hard_constraints')}")
        print(f"Soft Preferences: {effective_intent_card.get('soft_preferences')}")
        if scenario_type == "intent_override":
            override = effective_behavior.get("override", {})
            print(f"Override Turn  : Turn {override.get('turn')}")
            print(f"Override Value : {override.get('new_value')}")
        print("-" * 75)

    disclosed: set[str] = set()
    boundary_used = False
    override_applied = scenario_type != "intent_override"
    user_message = initial_message(
        effective_sample, coarse_category(categories.get(target_asin, [])), disclosed
    )
    
    hit_turn: int | None = None
    best_rank: int | None = None

    for turn in range(1, MAX_TURNS + 1):
        if verbose:
            print(f"\n[Turn {turn}] 👤 Customer:")
            print(f"  \"{user_message}\"")

        try:
            response = agent.respond(session_id, user_message, turn, TOP_K)
        except Exception as err:
            print(f"  [ERROR] Agent raised an exception: {err}")
            response = {"message": "", "ask_attribute": None, "recommendations": []}

        agent_message = response.get("message", "")
        ask_attr = response.get("ask_attribute")
        raw_recs = response.get("recommendations", [])
        ranked_asins = normalize_recommendations(raw_recs, catalog_ids)
        usage = response.get("usage", {})

        if verbose:
            print(f"\n[Turn {turn}] 🤖 Agent:")
            print(f"  Message       : \"{agent_message}\"")
            print(f"  Ask Attribute : {ask_attr}")
            if usage:
                print(f"  Token Usage   : {usage}")
            
            print(f"  Recommendations (Top {len(ranked_asins)}):")
            for rank, asin in enumerate(ranked_asins, 1):
                is_hit = (asin == target_asin)
                marker = "🎯 [TARGET HIT!]" if is_hit else f"#{rank}"
                p_title = products.get(asin, {}).get("title", "Unknown Title")
                short_title = p_title[:70] + ("..." if len(p_title) > 70 else "")
                print(f"    {marker:>16} {asin} | {short_title}")

        # Evaluation check
        if override_applied and target_asin in ranked_asins:
            best_rank = ranked_asins.index(target_asin) + 1
            hit_turn = turn
            if verbose:
                print(f"\n✨ Session SUCCESS on Turn {hit_turn} at Rank #{best_rank}!")
            break

        if turn == MAX_TURNS:
            if verbose:
                print(f"\n❌ Max turns reached (Turn {MAX_TURNS}). Session ended without target hit.")
            break

        # Simulate customer reply for next turn
        override = effective_sample.get("behavior", {}).get("override") or {}
        if not override_applied and turn + 1 == int(override.get("turn", 3)):
            override_applied = True
            new_value = str(override.get("new_value", ""))
            if new_value:
                disclosed.add(new_value)
            user_message = str(override.get("message", "Actually, please ignore my earlier preference."))
        else:
            user_message, boundary_used = customer_reply(
                effective_sample, ask_attr, disclosed, boundary_used
            )

    if verbose:
        print("=" * 75 + "\n")

    return {
        "sample_id": sample_id,
        "scenario_type": scenario_type,
        "hit": hit_turn is not None,
        "first_hit_turn": hit_turn,
        "best_rank": best_rank,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect turn-by-turn conversational shopping sessions")
    parser.add_argument("--catalog", default="data/catalog.jsonl", help="Path to catalog file")
    parser.add_argument("--dataset", default="data/public_set.jsonl", help="Path to public set")
    parser.add_argument("--sample-id", type=str, default=None, help="Specific sample ID to inspect (e.g. public_0001)")
    parser.add_argument("--index", type=int, default=None, help="0-based index of sample to inspect")
    parser.add_argument("--scenario", type=str, default=None, choices=["buying", "browsing", "intent_override", "boundary"], help="Filter by scenario")
    parser.add_argument("--limit", type=int, default=1, help="Number of sessions to run when inspecting")
    args = parser.parse_args()

    print("Loading catalog and public dataset...")
    catalog_ids, categories, products = catalog_index(args.catalog)
    samples = load_jsonl(args.dataset)

    # Filtering
    if args.sample_id:
        selected = [s for s in samples if s.get("sample_id") == args.sample_id]
        if not selected:
            print(f"Error: Sample ID '{args.sample_id}' not found in {args.dataset}")
            return
    elif args.index is not None:
        if 0 <= args.index < len(samples):
            selected = [samples[args.index]]
        else:
            print(f"Error: Index {args.index} out of range (0..{len(samples)-1})")
            return
    elif args.scenario:
        selected = [s for s in samples if s.get("scenario_type") == args.scenario][:args.limit]
    else:
        selected = samples[:args.limit]

    print(f"Running session inspection for {len(selected)} sample(s)...\n")
    agent = Agent(args.catalog)

    for sample in selected:
        run_single_session(agent, sample, catalog_ids, categories, products, verbose=True)


if __name__ == "__main__":
    main()

