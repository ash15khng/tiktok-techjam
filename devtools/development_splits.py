"""Create deterministic development folds without leaking targets into runtime.

The public 200 sessions are development data. This module reserves a sealed
holdout and builds cross-validation folds for parameter choices. Generated
manifests contain sample IDs only and belong under ``.local/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SplitConfig:
    seed: str = "techjam-2026-v1"
    holdout_fraction: float = 0.20
    development_folds: int = 4


@dataclass(frozen=True)
class DevelopmentSplits:
    seed: str
    sealed_holdout: tuple[str, ...]
    folds: tuple[tuple[str, ...], ...]
    group_by_sample: dict[str, str]
    scenario_by_sample: dict[str, str]

    def training_ids(self, validation_fold: int) -> tuple[str, ...]:
        if not 0 <= validation_fold < len(self.folds):
            raise IndexError(validation_fold)
        return tuple(
            sample_id
            for index, fold in enumerate(self.folds)
            if index != validation_fold
            for sample_id in fold
        )

    def validation_ids(self, validation_fold: int) -> tuple[str, ...]:
        return self.folds[validation_fold]

    def as_dict(self) -> dict:
        def counts(sample_ids: tuple[str, ...]) -> dict[str, int]:
            return dict(sorted(Counter(self.scenario_by_sample[value] for value in sample_ids).items()))

        return {
            "method": "scenario-stratified target-family-group holdout plus development cross-validation",
            "seed": self.seed,
            "sealed_holdout": {
                "sample_ids": list(self.sealed_holdout),
                "scenario_counts": counts(self.sealed_holdout),
            },
            "development_folds": [
                {"sample_ids": list(fold), "scenario_counts": counts(fold)} for fold in self.folds
            ],
            "group_by_sample": dict(sorted(self.group_by_sample.items())),
        }


def build_splits(
    samples: list[dict],
    products: dict[str, dict],
    config: SplitConfig | None = None,
) -> DevelopmentSplits:
    """Group exact-title product families, then balance scenario counts.

    Target ASIN is the fallback group, so no target can cross a boundary. Exact
    normalized-title collisions are grouped together to keep catalog duplicates
    or variants out of both tuning and validation partitions.
    """

    selected = config or SplitConfig()
    if not 0.0 < selected.holdout_fraction < 0.5:
        raise ValueError("holdout_fraction must be between 0 and 0.5")
    if selected.development_folds < 2:
        raise ValueError("development_folds must be at least 2")

    sample_by_id: dict[str, dict] = {}
    scenario_by_sample: dict[str, str] = {}
    group_by_sample: dict[str, str] = {}
    samples_by_group: dict[str, list[str]] = defaultdict(list)
    for sample in samples:
        sample_id = str(sample.get("sample_id") or "").strip()
        scenario = str(sample.get("scenario_type") or "").strip()
        target = str((sample.get("ground_truth") or {}).get("parent_asin") or "").strip()
        if not sample_id or sample_id in sample_by_id:
            raise ValueError(f"missing or duplicate sample_id: {sample_id!r}")
        if not scenario or not target or target not in products:
            raise ValueError(f"sample {sample_id!r} has invalid scenario or target")
        group = _target_family(target, products[target])
        sample_by_id[sample_id] = sample
        scenario_by_sample[sample_id] = scenario
        group_by_sample[sample_id] = group
        samples_by_group[group].append(sample_id)

    groups_by_stratum: dict[str, list[str]] = defaultdict(list)
    for group, sample_ids in samples_by_group.items():
        scenario_counts = Counter(scenario_by_sample[value] for value in sample_ids)
        primary = min(
            (scenario for scenario, count in scenario_counts.items() if count == max(scenario_counts.values())),
            key=str,
        )
        groups_by_stratum[primary].append(group)

    holdout_groups: set[str] = set()
    for scenario, groups in sorted(groups_by_stratum.items()):
        sample_target = round(
            sum(len(samples_by_group[group]) for group in groups) * selected.holdout_fraction
        )
        held = 0
        for group in sorted(groups, key=lambda value: _stable_key(selected.seed, "holdout", value)):
            if held >= sample_target:
                break
            holdout_groups.add(group)
            held += len(samples_by_group[group])

    development_groups = [group for group in samples_by_group if group not in holdout_groups]
    fold_groups: list[list[str]] = [[] for _ in range(selected.development_folds)]
    fold_scenarios: list[Counter[str]] = [Counter() for _ in range(selected.development_folds)]
    fold_sizes = [0 for _ in range(selected.development_folds)]
    ordered_groups = sorted(
        development_groups,
        key=lambda value: (-len(samples_by_group[value]), _stable_key(selected.seed, "fold", value)),
    )
    for group in ordered_groups:
        group_scenarios = Counter(scenario_by_sample[value] for value in samples_by_group[group])
        fold_index = min(
            range(selected.development_folds),
            key=lambda index: (
                sum(fold_scenarios[index][scenario] for scenario in group_scenarios),
                fold_sizes[index],
                _stable_key(selected.seed, group, str(index)),
            ),
        )
        fold_groups[fold_index].append(group)
        fold_scenarios[fold_index].update(group_scenarios)
        fold_sizes[fold_index] += len(samples_by_group[group])

    holdout = _sample_ids(holdout_groups, samples_by_group, selected.seed, "holdout-order")
    folds = tuple(
        _sample_ids(groups, samples_by_group, selected.seed, f"fold-{index}")
        for index, groups in enumerate(fold_groups)
    )
    result = DevelopmentSplits(
        selected.seed,
        holdout,
        folds,
        group_by_sample,
        scenario_by_sample,
    )
    assert_disjoint(result)
    return result


def assert_disjoint(splits: DevelopmentSplits) -> None:
    """Reject sample or target-family leakage across every partition."""

    partitions = (splits.sealed_holdout, *splits.folds)
    seen_samples: set[str] = set()
    seen_groups: set[str] = set()
    for partition in partitions:
        sample_ids = set(partition)
        groups = {splits.group_by_sample[value] for value in partition}
        if seen_samples & sample_ids:
            raise AssertionError("sample leakage across development partitions")
        if seen_groups & groups:
            raise AssertionError("target-family leakage across development partitions")
        seen_samples.update(sample_ids)
        seen_groups.update(groups)
    if seen_samples != set(splits.group_by_sample):
        raise AssertionError("some samples were not assigned")


def load_jsonl(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _target_family(target: str, product: dict) -> str:
    title = _normalize_title(product.get("title"))
    return f"title:{title}" if title else f"asin:{target}"


def _normalize_title(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def _stable_key(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()


def _sample_ids(
    groups: set[str] | list[str],
    samples_by_group: dict[str, list[str]],
    seed: str,
    namespace: str,
) -> tuple[str, ...]:
    values = [sample_id for group in groups for sample_id in samples_by_group[group]]
    return tuple(sorted(values, key=lambda value: _stable_key(seed, namespace, value)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build leakage-resistant public development splits")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--output", default=".local/development_splits.json")
    parser.add_argument("--seed", default=SplitConfig.seed)
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    products = {
        str(product.get("parent_asin") or ""): product for product in load_jsonl(args.catalog)
    }
    splits = build_splits(samples, products, SplitConfig(seed=args.seed))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(splits.as_dict(), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "holdout_count": len(splits.sealed_holdout),
        "development_fold_counts": [len(value) for value in splits.folds],
    }, indent=2))


if __name__ == "__main__":
    main()
