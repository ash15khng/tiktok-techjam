"""MessageInterpreter coordinating the multi-step parsing cascade."""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping

from shopping_copilot.config import UnderstandingConfig
from shopping_copilot.dialog.models import DialogueContext
from shopping_copilot.understanding.grounding import (
    CatalogEntityLinker,
    CatalogTrie,
    build_default_trie,
    normalize_token,
)
from shopping_copilot.understanding.models import (
    Attribute,
    IntentFrame,
    InterpretationAmbiguity,
    Relation,
    SlotUpdate,
)
from shopping_copilot.understanding.rules import (
    detect_dialogue_acts,
    determine_modality_strength,
    extract_budget_slots,
    extract_negation_spans,
    extract_size_slots,
)

TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?", re.IGNORECASE)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
    "need", "im", "i'm", "what", "matters", "key", "requirement", "options",
    "quite", "right", "yet", "ask", "one", "specific", "preference", "judgment",
    "judgement", "earlier", "actually", "ignore", "preference", "use",
}

# Prefix patterns like "color: black", "material: cotton", "budget: under 50"
STRUCTURED_PREFIX_RE = re.compile(
    r"\b(material|color|size|style|brand|budget|feature|use_case)\s*[:=]\s*(.+?)(?=[;\n]|(?:\.\s)|$)",
    re.IGNORECASE,
)


class MessageInterpreter:
    """Cascade coordinator parsing user messages into structured SlotUpdates and IntentFrames."""

    def __init__(
        self,
        config: UnderstandingConfig | None = None,
        trie: CatalogTrie | None = None,
        linker: CatalogEntityLinker | None = None,
    ) -> None:
        self.config = config or UnderstandingConfig()
        self.trie = trie or build_default_trie()
        self.linker = linker or CatalogEntityLinker(self.config)

    def parse(
        self,
        message: str,
        context: DialogueContext | None = None,
    ) -> IntentFrame:
        """Execute the parsing cascade on a user message."""
        raw_message = unicodedata.normalize("NFKC", message or "").strip()
        turn = context.turn if context else 1
        last_ask = context.last_ask_attribute if context else None

        if not raw_message:
            return IntentFrame(
                dialogue_acts=("empty",),
                slot_updates=(),
                product_terms=(),
                parse_confidence=1.0,
            )

        dialogue_acts = detect_dialogue_acts(raw_message)
        slot_updates: list[SlotUpdate] = []
        ambiguities: list[InterpretationAmbiguity] = []
        subjective_needs: list[str] = []

        is_override = "override" in dialogue_acts
        is_indifference = "indifference" in dialogue_acts
        default_strength = determine_modality_strength(raw_message, "hard" if turn == 1 else "hard")

        # -------------------------------------------------------------------
        # Step 1: Handle Indifference / Boundary (set_any)
        # -------------------------------------------------------------------
        if is_indifference:
            target_attr = last_ask or Attribute.OTHER
            # Check if a specific attribute was mentioned in the indifference sentence
            for attr in Attribute:
                if attr.value in raw_message.lower():
                    target_attr = attr
                    break

            slot_updates.append(
                SlotUpdate(
                    attribute=target_attr,
                    operation="set_any",
                    relation=Relation.EQ,
                    normalized_values=(),
                    raw_span=raw_message,
                    char_span=(0, len(raw_message)),
                    strength="soft",
                    explicitness="explicit",
                    confidence=self.config.confidence_contextual_reply,
                    provenance="numeric_rule",
                    source_turn=turn,
                )
            )

        # -------------------------------------------------------------------
        # Step 2: Handle Structured Prefixes ("color: black", "material: cotton")
        # -------------------------------------------------------------------
        for match in STRUCTURED_PREFIX_RE.finditer(raw_message):
            attr_name = match.group(1).lower()
            val_text = match.group(2).strip()
            attr = Attribute(attr_name)
            op = "replace" if is_override else "set"

            # Parse value
            if attr == Attribute.BUDGET:
                b_slots = extract_budget_slots(val_text, turn, self.config)
                if b_slots:
                    slot_updates.extend(b_slots)
                    continue
            elif attr == Attribute.SIZE:
                s_slots = extract_size_slots(val_text, turn, self.config)
                if s_slots:
                    slot_updates.extend(s_slots)
                    continue

            norm_val = normalize_token(val_text)
            if norm_val:
                slot_updates.append(
                    SlotUpdate(
                        attribute=attr,
                        operation=op,
                        relation=Relation.EQ,
                        normalized_values=(norm_val,),
                        raw_span=match.group(0),
                        char_span=match.span(),
                        strength=default_strength,
                        explicitness="explicit",
                        confidence=self.config.confidence_catalog_exact,
                        provenance="catalog_exact",
                        source_turn=turn,
                    )
                )

        # -------------------------------------------------------------------
        # Step 3: Numeric Budget & Size Rules
        # -------------------------------------------------------------------
        budget_slots = extract_budget_slots(raw_message, turn, self.config)
        if budget_slots:
            slot_updates.extend(budget_slots)

        size_slots = extract_size_slots(raw_message, turn, self.config)
        if size_slots:
            slot_updates.extend(size_slots)

        # -------------------------------------------------------------------
        # Step 4: Catalog Trie Grounding (Materials, Colors, Styles, Categories)
        # -------------------------------------------------------------------
        negation_spans = extract_negation_spans(raw_message)
        trie_matches = self.trie.scan(raw_message)

        # Check for alternative OR groups
        has_or = bool(re.search(r"\b(?:or|either\s+.*?\s+or)\b", raw_message, re.IGNORECASE))
        alt_group_id = "alt_grp_1" if has_or else None

        for attr, canonical_val, raw_span, char_span in trie_matches:
            # Check if inside a structured prefix already handled
            if any(s.char_span[0] <= char_span[0] and char_span[1] <= s.char_span[1] for s in slot_updates):
                continue

            # Check if within negation scope
            is_negated = any(
                neg_start <= char_span[0] and char_span[1] <= neg_end
                for _, (neg_start, neg_end) in negation_spans
            )

            if is_negated:
                op = "exclude"
                rel = Relation.NEQ
            elif is_override:
                op = "replace"
                rel = Relation.EQ
            else:
                op = "add" if attr != Attribute.CATEGORY else "set"
                rel = Relation.EQ

            slot_updates.append(
                SlotUpdate(
                    attribute=attr,
                    operation=op,
                    relation=rel,
                    normalized_values=(canonical_val,),
                    alternative_group=alt_group_id,
                    raw_span=raw_span,
                    char_span=char_span,
                    strength=default_strength,
                    explicitness="explicit",
                    confidence=self.config.confidence_catalog_exact,
                    provenance="catalog_exact",
                    source_turn=turn,
                )
            )

        # -------------------------------------------------------------------
        # Step 5: Elliptical / Contextual Fallback for Last Asked Attribute
        # -------------------------------------------------------------------
        if last_ask and not slot_updates and not is_indifference:
            # The entire reply might be a direct response to the asked attribute
            # E.g. last_ask=color, reply="navy and dark grey"
            clean_reply = raw_message.strip(" -;,.")
            if clean_reply:
                # Try fuzzy link or direct assignment
                linked_val, score, amb = self.linker.link_span(clean_reply, last_ask)
                if linked_val:
                    slot_updates.append(
                        SlotUpdate(
                            attribute=last_ask,
                            operation="replace" if is_override else "set",
                            relation=Relation.EQ,
                            normalized_values=(linked_val,),
                            raw_span=clean_reply,
                            char_span=(0, len(raw_message)),
                            strength=default_strength,
                            explicitness="explicit",
                            confidence=score,
                            provenance="fuzzy",
                            source_turn=turn,
                        )
                    )
                elif amb:
                    ambiguities.append(amb)
                else:
                    # Inferred value
                    slot_updates.append(
                        SlotUpdate(
                            attribute=last_ask,
                            operation="replace" if is_override else "set",
                            relation=Relation.CONTAINS,
                            normalized_values=(normalize_token(clean_reply),),
                            raw_span=clean_reply,
                            char_span=(0, len(raw_message)),
                            strength="soft",
                            explicitness="inferred",
                            confidence=self.config.confidence_inferred,
                            provenance="semantic",
                            source_turn=turn,
                        )
                    )

        # -------------------------------------------------------------------
        # Step 6: Extract Product Terms & Subjective Needs
        # -------------------------------------------------------------------
        tokens = [
            t.lower()
            for t in TOKEN_RE.findall(raw_message)
            if len(t) > 1 and t.lower() not in STOPWORDS
        ]
        product_terms = tuple(dict.fromkeys(tokens))[: self.config.max_terms_for_lexical]

        # Extract subjective need clauses (e.g. "for winter walking", "breathable and comfortable")
        # Split on sentence boundaries
        clauses = re.split(r"[;.\n]", raw_message)
        for clause in clauses:
            clause_clean = clause.strip()
            if len(clause_clean) > 15 and not any(
                clause_clean.lower().startswith(s)
                for s in ("i'm looking", "im looking", "here are", "those options")
            ):
                subjective_needs.append(clause_clean)

        # Calculate overall parse confidence
        if slot_updates:
            avg_conf = sum(s.confidence for s in slot_updates) / len(slot_updates)
        elif is_indifference or "explore" in dialogue_acts:
            avg_conf = 0.95
        else:
            avg_conf = 0.70

        return IntentFrame(
            dialogue_acts=tuple(dialogue_acts),
            slot_updates=tuple(slot_updates),
            product_terms=product_terms,
            subjective_needs=tuple(subjective_needs),
            residual_terms=product_terms,
            ambiguities=tuple(ambiguities),
            parse_confidence=round(avg_conf, 4),
        )
