"""Title and field-weighted SQLite FTS retrieval."""

from __future__ import annotations

from submission.src.catalog.store import (
    CATEGORY_WEIGHTS,
    CONSTRAINT_WEIGHTS,
    FIELD_WEIGHTS,
    TITLE_WEIGHTS,
    CatalogStore,
)
from submission.src.config import MVPConfig
from submission.src.dialog.models import ActiveState
from submission.src.retrieval.models import RetrievalPlan


class LexicalRetriever:
    def __init__(self, store: CatalogStore, config: MVPConfig) -> None:
        self.store = store
        self.config = config

    def retrieve(self, active: ActiveState, plan: RetrievalPlan) -> dict[str, list]:
        query_terms = active.query_terms()[: self.config.max_query_terms]
        category_terms = active.category_terms()[: self.config.max_query_terms]
        preference_terms = active.preference_terms()[: self.config.max_query_terms]
        focused_terms = self.store.rare_terms(preference_terms, self.config.max_focused_terms)

        constraint = self.store.search(
            focused_terms,
            weights=CONSTRAINT_WEIGHTS,
            limit=plan.generator_limit,
            require_all=True,
        )
        if not constraint and focused_terms:
            constraint = self.store.search(
                focused_terms,
                weights=CONSTRAINT_WEIGHTS,
                limit=plan.generator_limit,
            )
        category_pool = self.store.search(
            category_terms,
            weights=CATEGORY_WEIGHTS,
            limit=max(plan.generator_limit, self.config.category_pool_depth),
            require_all=True,
        )
        if not category_pool and category_terms:
            category_pool = self.store.search(
                category_terms,
                weights=CATEGORY_WEIGHTS,
                limit=max(plan.generator_limit, self.config.category_pool_depth),
            )
        category_popular = sorted(
            category_pool,
            key=lambda result: (
                -self.store.get(result.parent_asin).rating_number,
                result.raw_score,
                result.parent_asin,
            ),
        )[: plan.generator_limit]
        return {
            "field": self.store.search(query_terms, weights=FIELD_WEIGHTS, limit=plan.generator_limit),
            "title": self.store.search(category_terms or query_terms, weights=TITLE_WEIGHTS, limit=plan.generator_limit),
            "category": category_pool[: plan.generator_limit],
            "category_popular": category_popular,
            "constraint": constraint,
        }
