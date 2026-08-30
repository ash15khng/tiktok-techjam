from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from shopping_copilot.catalog.loader import CatalogLoader
from shopping_copilot.dialog.models import CustomerProfile, DialogueContext, TurnRecord
from shopping_copilot.dialog.reducer import StateReducer
from shopping_copilot.dialog.store import SessionStore
from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.policy.question import QuestionPolicy
from shopping_copilot.ranking.reranker import LightweightReranker
from shopping_copilot.retrieval.attributes import AttributeCandidateGenerator
from shopping_copilot.retrieval.fusion import WeightedRRFFusion
from shopping_copilot.retrieval.lexical import FieldWeightedFTSGenerator, TitleFTSGenerator
from shopping_copilot.retrieval.models import RetrievalRequest
from shopping_copilot.retrieval.planner import RetrievalPlanner
from shopping_copilot.understanding.assessment import NeedAssessor
from shopping_copilot.understanding.grounding import CatalogTrie, build_default_trie
from shopping_copilot.understanding.interpreter import MessageInterpreter
from shopping_copilot.understanding.models import Attribute


class ShoppingAgent:
    """End-to-end intelligent shopping copilot agent with multi-turn state tracking and clarification policy."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self.catalog_path = Path(catalog_path)
        loader = CatalogLoader()
        self.catalog_index = CatalogIndex()
        self.catalog_index.build_from_records(loader.stream_file(self.catalog_path))

        # Grounding trie built from default aliases and catalog vocabulary
        self.catalog_trie = build_default_trie()
        for attr, values in self.catalog_index.get_vocabulary_by_attribute().items():
            for val in values:
                self.catalog_trie.insert(val, attr, val)

        # Component 2 subsystems
        self.interpreter = MessageInterpreter(trie=self.catalog_trie)
        self.need_assessor = NeedAssessor()
        self.state_reducer = StateReducer()
        self.session_store = SessionStore()

        # Component 3 subsystems
        self.title_gen = TitleFTSGenerator(self.catalog_index)
        self.field_gen = FieldWeightedFTSGenerator(self.catalog_index)
        self.attr_gen = AttributeCandidateGenerator(self.catalog_index)
        self.fusion = WeightedRRFFusion()
        self.planner = RetrievalPlanner()
        self.reranker = LightweightReranker(self.catalog_index)

        # Component 4 subsystems
        self.policy = QuestionPolicy(self.catalog_index)
        self._asked_attributes: dict[str, set[str]] = defaultdict(set)

    def reset(self, session_id: str, user_profile: dict[str, Any]) -> None:
        """Initializes or resets session state with optional customer profile."""
        profile = CustomerProfile.from_dict(user_profile)
        self.session_store.reset(session_id, profile)
        self._asked_attributes[session_id].clear()

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Processes user message, updates session state, retrieves candidates, and decides dialog action."""
        try:
            session = self.session_store.get_session(session_id)
        except KeyError:
            raise RuntimeError(f"Session '{session_id}' must be initialized with reset() before calling respond()")

        # 1. Prepare dialogue context
        context = self.session_store.get_dialogue_context(session_id, turn)

        # 2. Extract intent frame
        intent_frame = self.interpreter.parse(user_message, context)

        # 3. Assess user decision stage and focus score
        assessment = self.need_assessor.assess(session.active_state, intent_frame)

        # 4. Reduce state with invariant guarantees
        new_active_state = self.state_reducer.reduce(session.active_state, intent_frame, turn=turn)
        self.session_store.update_active_state(session_id, new_active_state)

        # 5. Build retrieval request and execution plan
        turns_remaining = max(0, 11 - turn)
        retrieval_req = RetrievalRequest.from_active_state(new_active_state, turns_remaining=turns_remaining)
        plan = self.planner.plan(assessment.focus_score)

        # 6. Candidate generation across three complementary routes
        title_candidates = self.title_gen.generate(retrieval_req, limit=plan.generator_limits["title_fts"])
        field_candidates = self.field_gen.generate(retrieval_req, limit=plan.generator_limits["field_fts"])
        attr_candidates = self.attr_gen.generate(retrieval_req, limit=plan.generator_limits["attribute_posting"])

        # 7. Candidate fusion via Weighted Reciprocal Rank Fusion
        evidence_map = self.fusion.fuse(
            {
                "title_fts": title_candidates,
                "field_fts": field_candidates,
                "attribute_posting": attr_candidates,
            },
            plan.generator_weights,
        )

        # 8. Tri-state constraint evaluation and multi-signal reranking
        reranked_evidence = self.reranker.rerank(evidence_map, retrieval_req, top_k=50)

        # 9. Adaptive clarification policy
        decision = self.policy.decide_action(
            active_state=new_active_state,
            candidate_evidence=reranked_evidence,
            turn=turn,
            focus_score=assessment.focus_score,
            asked_attributes_in_session=self._asked_attributes[session_id],
            top_k=top_k,
        )

        if decision.ask_attribute:
            self._asked_attributes[session_id].add(decision.ask_attribute)

        # 10. Update session store history
        ask_attr_enum = None
        if decision.ask_attribute:
            try:
                ask_attr_enum = Attribute(decision.ask_attribute)
            except ValueError:
                ask_attr_enum = Attribute.OTHER

        turn_record = TurnRecord(
            turn=turn,
            user_message=user_message,
            intent_frame=intent_frame,
            recommendations=decision.recommendations,
            ask_attribute=ask_attr_enum,
            question_text=decision.message,
        )
        self.session_store.record_turn(
            session_id=session_id,
            turn_record=turn_record,
            ask_attribute=ask_attr_enum,
            recommendations=decision.recommendations,
        )

        return {
            "message": decision.message,
            "ask_attribute": decision.ask_attribute,
            "recommendations": [{"parent_asin": asin} for asin in decision.recommendations[:top_k]],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
