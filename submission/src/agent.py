"""
Inputs:
    As per competition defined in submission_rules.md:
    - Agent(catalog_path: str | Path = "data/catalog.jsonl") -> None:
        - The competition contract omits ``catalog_path``; this implementation
          supplies the frozen catalog's default location.
    - reset(self, session_id: str, user_profile: dict) -> None:
    - respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:

Outputs:
    respond():
        dict {
            "message": user facing message,
            "ask_attribute": one permitted competition attribute or null,
            "recommendations": [{"parent_asin": "B000..."}] [up to 10],
            "usage": {"prompt_tokens": int, "completion_tokens": int} (nullable if no usage)
        }
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from submission.src.catalog.normalization import tokenize
from submission.src.catalog.store import FIELD_WEIGHTS, CatalogStore
from submission.src.config import AgentConfig
from submission.src.contracts import DisabledSemanticParser, ResponseGuard, SemanticParser
from submission.src.dialog.policy import QuestionPolicy
from submission.src.dialog.reducer import StateReducer
from submission.src.dialog.models import SessionState
from submission.src.dialog.store import SessionStore
from submission.src.ranking.explanations import explain
from submission.src.ranking.exposure import unseen_first
from submission.src.ranking.reranker import LightweightReranker
from submission.src.retrieval.fusion import assess_results, reciprocal_rank_fusion
from submission.src.retrieval.lexical import LexicalRetriever
from submission.src.retrieval.models import CandidateEvidence, RetrievalAssessment
from submission.src.retrieval.planner import RetrievalPlanner
from submission.src.understanding.interpreter import MessageInterpreter
from submission.src.understanding.escalation import SemanticEscalationPolicy
from submission.src.understanding.semantic import semantic_parser_from_environment


class ShoppingAgent:

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        *,
        config: AgentConfig | None = None,
        semantic_parser: SemanticParser | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.catalog = CatalogStore(catalog_path)
        self.sessions = SessionStore()
        self.semantic_parser = semantic_parser or semantic_parser_from_environment(self.config)
        self.interpreter = MessageInterpreter(
            self.semantic_parser,
            semantic_min_confidence=self.config.semantic_min_confidence,
            semantic_max_rewrite_terms=self.config.semantic_max_rewrite_terms,
            attribute_resolver=self.catalog.attributes,
        )
        self.reducer = StateReducer(self.catalog.attributes)
        self.planner = RetrievalPlanner(self.config)
        self.retriever = LexicalRetriever(self.catalog, self.config)
        self.reranker = LightweightReranker(self.catalog, self.config)
        self.question_policy = QuestionPolicy(self.catalog, self.config)
        self.semantic_escalation = SemanticEscalationPolicy(self.config)
        self.guard = ResponseGuard(self.catalog.valid_ids, self.catalog.popular)

    def reset(self, session_id: str, user_profile: dict) -> None:
        """Create fresh mutable state for session."""
        self.sessions.reset(session_id, user_profile)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        """Interpret, retrieve, rank, ask if useful, and return a safe response."""

        state = self.sessions.get(session_id)
        requested_turn = int(turn)
        cached = state.responses_by_turn.get(requested_turn)
        if cached is not None:
            return deepcopy(cached)
        if requested_turn <= state.last_completed_turn:
            # A late out-of-order request must not replay state transitions.
            latest = state.responses_by_turn.get(state.last_completed_turn)
            if latest is not None:
                return deepcopy(latest)
        try:
            # Parse the turn into an immutable delta before mutating session state.
            frame = self.interpreter.parse_deterministic(
                user_message,
                last_ask_attribute=state.last_ask_attribute,
            )
            semantic_called = False
            semantic_available = (
                not isinstance(self.semantic_parser, DisabledSemanticParser)
                and state.semantic_call_count < self.config.semantic_max_calls_per_session
            )
            if semantic_available:
                preflight = self.semantic_escalation.decide_before_retrieval(
                    frame,
                    state.active,
                )
                if preflight.should_call:
                    state.semantic_call_count += 1
                    frame = self.interpreter.enrich_with_semantics(
                        frame,
                        context=state.active.context_snapshot(
                            last_ask_attribute=state.last_ask_attribute,
                        ),
                        force=True,
                    )
                    semantic_called = True
                    self.semantic_escalation.record_outcome(
                        applied=bool(frame.query_rewrites or frame.semantic_hypotheses),
                    )
            self.reducer.apply(state, frame)
            assessment, ranked = self._retrieve_and_rank(state)
            if not semantic_called and semantic_available:
                decision = self.semantic_escalation.decide(
                    frame,
                    state.active,
                    assessment,
                    top_exact_preference_match=self._top_exact_preference_match(state, ranked),
                )
                if decision.should_call:
                    state.semantic_call_count += 1
                    frame = self.interpreter.enrich_with_semantics(
                        frame,
                        context=state.active.context_snapshot(
                            last_ask_attribute=state.last_ask_attribute,
                        ),
                        force=True,
                    )
                    applied = self.reducer.apply_semantic(state, frame)
                    self.semantic_escalation.record_outcome(applied=applied)
                    if applied:
                        # Rerank once because semantic evidence changed Active State.
                        assessment, ranked = self._retrieve_and_rank(state)
            ranked = unseen_first(ranked, state.recommendation_exposure)
            question = self.question_policy.choose(
                state,
                ranked,
                assessment,
                requested_turn,
            )
            recommendations = tuple(item.parent_asin for item in ranked)
            message = explain(state.active)
            if question.message:
                message = f"{message} {question.message}"
            state.last_ask_attribute = question.ask_attribute
            if question.ask_attribute:
                state.active.asked_attributes.append(question.ask_attribute)
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
            return self._remember_response(state, requested_turn, response)
        except Exception:
            # Preserve the last successful list before attempting fresh FTS.
            # A nested fallback guard keeps even catalog-search failures safe.
            fallback_ids = state.last_recommendations
            if not fallback_ids:
                try:
                    fallback_terms = tokenize(user_message)[: self.config.max_query_terms]
                    fallback = self.catalog.search(
                        fallback_terms,
                        weights=FIELD_WEIGHTS,
                        limit=min(int(top_k), self.config.max_recommendations),
                    )
                    fallback_ids = tuple(item.parent_asin for item in fallback)
                except Exception:
                    fallback_ids = ()
            response = self.guard.build(
                message="I used the reliable catalog search fallback for these matches.",
                ask_attribute=None,
                recommendations=fallback_ids,
                top_k=top_k,
            )
            return self._remember_response(state, requested_turn, response)

    @staticmethod
    def _remember_response(
        state: SessionState,
        turn: int,
        response: dict,
    ) -> dict:
        """Store one bounded response snapshot and return an isolated copy."""

        snapshot = deepcopy(response)
        state.responses_by_turn[int(turn)] = snapshot
        state.last_completed_turn = max(state.last_completed_turn, int(turn))
        state.last_recommendations = tuple(
            item["parent_asin"] for item in snapshot["recommendations"]
        )
        return deepcopy(snapshot)

    def diagnostics(self) -> dict[str, dict[str, int | float]]:
        """Return credential-free semantic gate/provider counters."""

        provider_stats = getattr(self.semantic_parser, "stats", None)
        return {
            "semantic_escalation": self.semantic_escalation.stats(),
            "semantic_provider": provider_stats() if callable(provider_stats) else {},
        }

    def _retrieve_and_rank(
        self,
        state: SessionState,
    ) -> tuple[RetrievalAssessment, list[CandidateEvidence]]:
        plan = self.planner.plan(state.active)
        generated = self.retriever.retrieve(state.active, plan)
        fused = reciprocal_rank_fusion(
            generated,
            plan.generator_weights,
            k=self.config.rrf_k,
        )
        assessment = assess_results(
            generated,
            fused,
            overlap_depth=self.config.assessment_overlap_depth,
            stability_scale=self.config.assessment_stability_scale,
        )
        ranked = self.reranker.rank(fused, state.active, state.customer_profile)
        return assessment, ranked

    def _top_exact_preference_match(
        self,
        state: SessionState,
        ranked: list[CandidateEvidence],
    ) -> bool:
        if not ranked:
            return False
        product_text = self.catalog.product_token_text(ranked[0].parent_asin)
        for phrase in state.active.preference_phrases:
            phrase_terms = tokenize(phrase, drop_stopwords=False)
            if (
                len(phrase_terms) >= self.config.semantic_exact_phrase_min_terms
                and " ".join(phrase_terms) in product_text
            ):
                return True
        return False
