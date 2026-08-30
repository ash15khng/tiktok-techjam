from __future__ import annotations

import math
import re
from typing import Mapping, Sequence

from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.ranking.constraints import evaluate_constraint
from shopping_copilot.retrieval.models import CandidateEvidence, RetrievalRequest

WORD_RE = re.compile(r"[\w\d]+", re.UNICODE)


class LightweightReranker:
    """Deterministic candidate reranker applying multi-signal scoring and hard contradiction demotion."""

    def __init__(self, catalog_index: CatalogIndex) -> None:
        self.catalog_index = catalog_index

    def rerank(
        self,
        candidate_evidence: Mapping[str, CandidateEvidence],
        request: RetrievalRequest,
        top_k: int = 10,
    ) -> list[CandidateEvidence]:
        """Scores and sorts candidate evidence records."""
        if not candidate_evidence:
            return []

        all_constraints = list(request.active_constraints) + list(request.exclusions)
        raw_tokens = []
        for phrase in request.raw_phrases + request.product_terms:
            raw_tokens.extend(WORD_RE.findall(phrase.lower()))
        raw_tokens = list(dict.fromkeys(raw_tokens))
        total_raw_idf = sum(self.catalog_index.compute_idf(t) for t in raw_tokens) if raw_tokens else 0.0

        scored_candidates: list[tuple[int, float, CandidateEvidence]] = []

        for asin, ev in candidate_evidence.items():
            record = self.catalog_index.get_product(asin)
            if not record:
                continue

            hard_matches = 0
            soft_matches = 0
            hard_contras = 0
            soft_contras = 0

            # Evaluate each constraint
            for c in all_constraints:
                res = evaluate_constraint(record, c)
                ev.constraint_results[f"{c.attribute.value}_{c.raw_span}"] = res

                if res == "match":
                    if c.strength == "hard":
                        hard_matches += 1
                    else:
                        soft_matches += 1
                elif res == "contradiction":
                    if c.strength == "hard":
                        hard_contras += 1
                    else:
                        soft_contras += 1

            total_constraints = max(len(all_constraints), 1)
            hard_match_ratio = hard_matches / total_constraints
            soft_match_ratio = soft_matches / total_constraints
            hard_contra_ratio = hard_contras / total_constraints
            soft_contra_ratio = soft_contras / total_constraints

            # Category match
            cat_match = 0.0
            if request.category and record.categories:
                cat_req = request.category.lower()
                if any(cat_req in c.lower() or c.lower() in cat_req for c in record.categories):
                    cat_match = 1.0

            # Constraint support in [-1, 1]
            raw_support = (
                0.30 * hard_match_ratio
                + 0.15 * soft_match_ratio
                + 0.10 * cat_match
                - 0.35 * hard_contra_ratio
                - 0.10 * soft_contra_ratio
            )
            constraint_support = min(1.0, max(-1.0, raw_support))
            normalized_support = (constraint_support + 1.0) / 2.0

            # Raw phrase IDF match in [0, 1]
            if total_raw_idf > 1e-9:
                searchable_text = " ".join(record.search_fields.values()).lower()
                matched_idf = sum(
                    self.catalog_index.compute_idf(t)
                    for t in raw_tokens
                    if t in searchable_text
                )
                raw_phrase_match = min(1.0, matched_idf / total_raw_idf)
            else:
                raw_phrase_match = 0.5

            # Popularity prior in [0, 1]
            num_ratings = record.rating_number or 0
            avg_rating = record.average_rating or 0.0
            popularity = min(1.0, (math.log1p(max(num_ratings, 0)) / math.log1p(1000)) * (max(avg_rating, 0.0) / 5.0))

            # Profile preference boost (dynamically weighted higher on early turns)
            profile_boost = 0.0
            if request.profile_preferences:
                searchable = " ".join(record.search_fields.values()).lower()
                matching_prefs = sum(1 for p in request.profile_preferences if p.lower() in searchable)
                weight_scale = max(0.02, 0.08 - 0.015 * len(all_constraints))
                profile_boost = (matching_prefs / len(request.profile_preferences)) * weight_scale

            # Combined final score
            final_score = (
                0.55 * ev.rrf_score
                + 0.30 * normalized_support
                + 0.10 * raw_phrase_match
                + 0.05 * popularity
                + profile_boost
            )

            ev.lightweight_score = round(normalized_support, 4)
            ev.final_score = round(final_score, 4)

            # Contradiction flag (0 if has hard contradiction, 1 if clean)
            is_clean = 0 if hard_contras > 0 else 1
            scored_candidates.append((is_clean, final_score, ev))

        # Sort: clean items first (descending), then score descending, then ASIN ascending
        scored_candidates.sort(key=lambda item: (-item[0], -item[1], item[2].parent_asin))
        return [item[2] for item in scored_candidates[:top_k]]

