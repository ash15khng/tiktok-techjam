"""End-to-end deterministic orchestrator with optional semantic hints."""

from __future__ import annotations

from pathlib import Path

from shopping_copilot.catalog.normalization import tokenize
from shopping_copilot.catalog.store import FIELD_WEIGHTS, CatalogStore
from shopping_copilot.config import MVPConfig
from shopping_copilot.contracts import ResponseGuard, SemanticParser
from shopping_copilot.dialog.policy import QuestionPolicy
from shopping_copilot.dialog.reducer import StateReducer
from shopping_copilot.dialog.store import SessionStore
from shopping_copilot.ranking.explanations import explain
from shopping_copilot.ranking.exposure import unseen_first
from shopping_copilot.ranking.reranker import LightweightReranker
from shopping_copilot.retrieval.fusion import assess_results, reciprocal_rank_fusion
from shopping_copilot.retrieval.lexical import LexicalRetriever
from shopping_copilot.retrieval.planner import RetrievalPlanner
from shopping_copilot.understanding.interpreter import MessageInterpreter
from shopping_copilot.understanding.semantic import semantic_parser_from_environment


class ShoppingAgent:
    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        *,
        config: MVPConfig | None = None,
        semantic_parser: SemanticParser | None = None,
    ) -> None:
        self.config = config or MVPConfig()
        self.catalog = CatalogStore(catalog_path)
        self.sessions = SessionStore()
        self.interpreter = MessageInterpreter(semantic_parser or semantic_parser_from_environment(self.config))
        self.reducer = StateReducer()
        self.planner = RetrievalPlanner(self.config)
        self.retriever = LexicalRetriever(self.catalog, self.config)
        self.reranker = LightweightReranker(self.catalog, self.config)
        self.question_policy = QuestionPolicy(self.catalog, self.config)
        self.guard = ResponseGuard(self.catalog.valid_ids, self.catalog.popular)

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.sessions.reset(session_id, user_profile)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        state = self.sessions.get(session_id)
        try:
            frame = self.interpreter.parse(
                user_message,
                last_ask_attribute=state.last_ask_attribute,
                context=state.active.context_snapshot(),
            )
            self.reducer.apply(state, frame)
            plan = self.planner.plan(state.active)
            generated = self.retriever.retrieve(state.active, plan)
            fused = reciprocal_rank_fusion(generated, plan.generator_weights, k=self.config.rrf_k)
            assessment = assess_results(generated, fused)
            ranked = self.reranker.rank(fused, state.active, state.customer_profile)
            ranked = unseen_first(ranked, state.recommendation_exposure)
            question = self.question_policy.choose(state, ranked, assessment, turn)
            recommendations = tuple(item.parent_asin for item in ranked)
            message = explain(state.active)
            if question.message:
                message = f"{message} {question.message}"
            state.last_ask_attribute = question.ask_attribute
            if question.ask_attribute:
                state.active.asked_attributes.append(question.ask_attribute)
            state.last_recommendations = recommendations[:10]
            response = self.guard.build(
                message=message,
                ask_attribute=question.ask_attribute,
                recommendations=recommendations,
                top_k=top_k,
                prompt_tokens=frame.prompt_tokens,
                completion_tokens=frame.completion_tokens,
            )
            state.recommendation_exposure.update(
                item["parent_asin"] for item in response["recommendations"]
            )
            return response
        except Exception:
            # A component failure must still produce valid frozen-catalog IDs.
            fallback_terms = tokenize(user_message)[: self.config.max_query_terms]
            fallback = self.catalog.search(
                fallback_terms,
                weights=FIELD_WEIGHTS,
                limit=min(int(top_k), 10),
            )
            return self.guard.build(
                message="I used the reliable catalog search fallback for these matches.",
                ask_attribute=None,
                recommendations=(item.parent_asin for item in fallback),
                top_k=top_k,
            )
