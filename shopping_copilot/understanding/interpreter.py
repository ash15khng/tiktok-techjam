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
    split_conjunction_items,
    strip_conversational_filler,
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

        # Handle simulator guidance / meta-prompt
        if re.search(r"\b(?:those options are not quite right|ask me about one specific attribute)\b", raw_message, re.IGNORECASE):
            return IntentFrame(
                dialogue_acts=("clarify",),
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
            # If the message is a pure indifference declaration without contrastive conjunctions, return immediately
            if not re.search(r"\b(?:but|however|instead|except|except for|only)\b", raw_message, re.IGNORECASE):
                return IntentFrame(
                    dialogue_acts=tuple(dialogue_acts),
                    slot_updates=tuple(slot_updates),
                    product_terms=(),
                    parse_confidence=1.0,
                )

        # -------------------------------------------------------------------
        # Step 1.5: Coarse Category Intent Pattern ("I'm looking for <CATEGORY>")
        # -------------------------------------------------------------------
        cat_match = re.search(
            r"\b(?:i'm looking for|im looking for|looking for|searching for|want to buy)\s+([a-zA-Z0-9\s&,'-]+?)(?:[.,;]|(?:\s+(?:but|with|style:|material:|color:|brand:|size:|budget:|feature:|for|under|around|my\s+preference))\b|$)",
            raw_message,
            re.IGNORECASE,
        )
        if cat_match:
            candidate_cat = cat_match.group(1).strip()
            candidate_cat = re.sub(r"^\b(?:a|an|the|some)\b\s*", "", candidate_cat, flags=re.IGNORECASE).strip()
            if candidate_cat and len(candidate_cat) > 2 and candidate_cat.lower() not in STOPWORDS:
                slot_updates.append(
                    SlotUpdate(
                        attribute=Attribute.CATEGORY,
                        operation="replace" if is_override else "set",
                        relation=Relation.EQ,
                        normalized_values=(candidate_cat.lower(),),
                        raw_span=candidate_cat,
                        char_span=cat_match.span(1),
                        strength="hard",
                        explicitness="explicit",
                        confidence=0.95,
                        provenance="coarse_category",
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
                        provenance="structured_prefix",
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
            # Check if inside a structured prefix or coarse category already handled
            if any(
                s.provenance in ("structured_prefix", "coarse_category")
                and s.char_span[0] <= char_span[0]
                and char_span[1] <= s.char_span[1]
                for s in slot_updates
            ):
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
        # Step 5: Elliptical / Contextual Fallback for Last Asked Attribute & Multi-Items
        # -------------------------------------------------------------------
        if not is_indifference:
            candidate_items = split_conjunction_items(raw_message)
            for item_phrase in candidate_items:
                # Check if this item phrase was already captured by previous steps
                if any(
                    item_phrase.lower() in (s.raw_span or "").lower()
                    or (s.raw_span or "").lower() in item_phrase.lower()
                    for s in slot_updates
                ):
                    continue

                # Check trie scan on this specific phrase
                item_trie_matches = self.trie.scan(item_phrase)
                if item_trie_matches:
                    for attr, canonical_val, r_span, c_span in item_trie_matches:
                        if not any(
                            s.attribute == attr and canonical_val in s.normalized_values
                            for s in slot_updates
                        ):
                            slot_updates.append(
                                SlotUpdate(
                                    attribute=attr,
                                    operation="replace" if is_override else ("set" if attr == Attribute.CATEGORY else "add"),
                                    relation=Relation.EQ,
                                    normalized_values=(canonical_val,),
                                    raw_span=r_span,
                                    char_span=(0, len(raw_message)),
                                    strength=default_strength,
                                    explicitness="explicit",
                                    confidence=self.config.confidence_catalog_exact,
                                    provenance="catalog_exact",
                                    source_turn=turn,
                                )
                            )
                    continue

                # If we asked a specific attribute, attempt linking or assign to last_ask
                target_attr = last_ask or Attribute.FEATURE
                linked_val, score, amb = self.linker.link_span(item_phrase, target_attr)
                if linked_val:
                    slot_updates.append(
                        SlotUpdate(
                            attribute=target_attr,
                            operation="replace" if is_override else "add",
                            relation=Relation.EQ,
                            normalized_values=(linked_val,),
                            raw_span=item_phrase,
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
                    norm_tok = normalize_token(item_phrase)
                    if norm_tok and len(norm_tok) > 2 and norm_tok not in STOPWORDS:
                        slot_updates.append(
                            SlotUpdate(
                                attribute=target_attr,
                                operation="replace" if is_override else "add",
                                relation=Relation.CONTAINS,
                                normalized_values=(norm_tok,),
                                raw_span=item_phrase,
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
