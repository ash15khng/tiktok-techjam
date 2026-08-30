# Shopping Copilot Class Diagrams

This document covers every product-runtime class under `submission/` and the
two development-split data classes. Test-case classes are excluded because they
verify the design rather than participate in it. The evaluator is function-based
and has no product-domain classes.

## Relationship legend

| Symbol | Meaning in this codebase |
|---|---|
| `*--` | Composition: the owner creates/contains the part and controls its lifecycle |
| `o--` | Aggregation: a collaborator may be injected or wrapped and can exist independently |
| `-->` | Association: calls, reads, produces, or otherwise uses |
| `<|--` | Class inheritance |
| `<|..` | Structural implementation of a `Protocol` |
| `..>` | Short-lived dependency, normally an input or return value |

The design deliberately favors composition over class inheritance. The only
concrete inheritance is `SemanticParserError` from `RuntimeError`; polymorphism
is supplied through the two small protocols.

## 1. Whole runtime composition

```mermaid
classDiagram
    direction LR

    class Agent {
        +reset(session_id, user_profile)
        +respond(session_id, message, turn, top_k) dict
    }
    class ShoppingAgent {
        +reset(session_id, user_profile)
        +respond(session_id, message, turn, top_k) dict
        +diagnostics() dict
    }
    class AgentConfig
    class CatalogStore
    class SessionStore
    class MessageInterpreter
    class StateReducer
    class RetrievalPlanner
    class LexicalRetriever
    class LightweightReranker
    class QuestionPolicy
    class SemanticEscalationPolicy
    class ResponseGuard
    class SemanticParser {
        <<protocol>>
        +interpret(message, context) SemanticInterpretation
    }

    Agent *-- ShoppingAgent : competition adapter owns
    ShoppingAgent o-- AgentConfig : injected or default settings
    ShoppingAgent *-- CatalogStore : frozen catalog
    ShoppingAgent *-- SessionStore : conversations
    ShoppingAgent *-- MessageInterpreter : understanding
    ShoppingAgent *-- StateReducer : state mutation
    ShoppingAgent *-- RetrievalPlanner : route strategy
    ShoppingAgent *-- LexicalRetriever : candidates
    ShoppingAgent *-- LightweightReranker : final order
    ShoppingAgent *-- QuestionPolicy : clarification
    ShoppingAgent *-- SemanticEscalationPolicy : call decision
    ShoppingAgent *-- ResponseGuard : API safety
    ShoppingAgent o-- SemanticParser : injected or configured
```

Use notes:

- `Agent` is the thin class the organizer imports. It delegates the required API
  without exposing internal components.
- `ShoppingAgent` is the composition root and turn orchestrator. This is the
  best starting point for tracing a request.
- `AgentConfig` holds immutable retrieval, ranking, question, and LLM limits.
  Components share the same instance so one configuration controls a run.

## 2. Catalog and catalog-derived attributes

```mermaid
classDiagram
    direction LR

    class ProductRecord {
        <<frozen_dataclass>>
        +parent_asin: str
        +title: str
        +categories: tuple
        +features: tuple
        +details: tuple
        +price: float?
        +rating_number: int
        +search_text() str
    }
    class CatalogSearchResult {
        <<frozen_dataclass>>
        +parent_asin: str
        +raw_score: float
    }
    class CatalogStore {
        +products: dict
        +valid_ids: frozenset
        +attributes: CatalogAttributeRegistry
        +get(parent_asin) ProductRecord
        +search(terms, weights, limit) list
        +popular(limit) tuple
        +rare_terms(terms, limit) tuple
        +inverse_document_frequency(terms) dict
    }
    class AttributeSpec {
        <<frozen_dataclass>>
        +name: str
        +detail_key_fragments: tuple
        +question: str
    }
    class AttributeValueResolver {
        <<protocol>>
        +candidate_attributes(text, preferred) tuple
        +matched_values(text) tuple
    }
    class EmptyAttributeResolver {
        +candidate_attributes(text, preferred) tuple
        +matched_values(text) tuple
    }
    class CatalogAttributeRegistry {
        +candidate_attributes(text, preferred) tuple
        +matched_values(text) tuple
        +values_for_product(parent_asin, attribute) tuple
        +representative_value(parent_asin, attribute) str?
        +baseline_answerability(attribute) float
        +budget_bucket(price) str?
        +question_text(attribute) str?
    }

    CatalogStore "1" *-- "many" ProductRecord : normalizes and indexes
    CatalogStore *-- CatalogAttributeRegistry : derives after load
    CatalogStore ..> CatalogSearchResult : returns
    CatalogAttributeRegistry --> ProductRecord : derives values from
    CatalogAttributeRegistry ..> AttributeSpec : uses schema
    AttributeValueResolver <|.. EmptyAttributeResolver : implements
    AttributeValueResolver <|.. CatalogAttributeRegistry : implements
```

Use notes:

- `ProductRecord` is the normalized immutable representation of one frozen
  catalog product. Missing fields become safe empty/unknown values here.
- `CatalogSearchResult` is the minimal result returned by an individual SQLite
  FTS or popularity route before cross-route fusion.
- `CatalogStore` owns the in-memory SQLite FTS5 index, normalized records,
  document-frequency helpers, valid IDs, and catalog popularity ordering.
- `AttributeSpec` defines one question-capable field and how it maps to catalog
  detail keys; the instances are module-level immutable schema data.
- `AttributeValueResolver` lets interpretation depend on catalog knowledge
  without depending on a concrete store implementation.
- `EmptyAttributeResolver` is the safe null-object implementation used when no
  catalog resolver is supplied.
- `CatalogAttributeRegistry` derives value vocabularies, product attributes,
  answerability priors, and price buckets from the frozen catalog.

## 3. Deterministic message understanding

```mermaid
classDiagram
    direction LR

    class Attribute {
        <<enum>>
        CATEGORY
        MATERIAL
        COLOR
        SIZE
        STYLE
        BRAND
        BUDGET
        FEATURE
        USE_CASE
        OTHER
    }
    class ResolvedReply {
        <<frozen_dataclass>>
        +attribute: Attribute?
        +value: str
        +source: str
    }
    class SlotUpdate {
        <<frozen_dataclass>>
        +attribute: Attribute
        +operation: str
        +value: str
        +raw_span: str
        +source: str
    }
    class IntentFrame {
        <<frozen_dataclass>>
        +raw_message: str
        +dialogue_acts: tuple
        +slot_updates: tuple
        +category_phrases: tuple
        +preference_phrases: tuple
        +exclusions: tuple
        +override: bool
        +query_rewrites: tuple
    }
    class MessageInterpreter {
        +parse(message, last_attribute, context) IntentFrame
        +parse_deterministic(message, last_attribute) IntentFrame
        +enrich_with_semantics(frame, context, force) IntentFrame
    }
    class AttributeValueResolver {
        <<protocol>>
    }
    class SemanticParser {
        <<protocol>>
    }

    ResolvedReply --> Attribute : identifies
    SlotUpdate --> Attribute : targets
    IntentFrame "1" *-- "many" SlotUpdate : contains deltas
    IntentFrame --> Attribute : optional no-preference field
    MessageInterpreter o-- AttributeValueResolver : catalog grounding
    MessageInterpreter o-- SemanticParser : optional enrichment
    MessageInterpreter ..> ResolvedReply : obtains from contextual resolver
    MessageInterpreter ..> IntentFrame : produces
```

Use notes:

- `Attribute` is the canonical field vocabulary shared with the competition
  contract.
- `ResolvedReply` represents one explicit or contextual value resolution before
  it becomes a state operation.
- `SlotUpdate` is an immutable state delta such as `replace color with black`,
  `set_any budget`, or `exclude leather`.
- `IntentFrame` is the complete immutable interpretation of one customer turn.
  It separates parsing from state mutation and makes behavior testable.
- `MessageInterpreter` performs deterministic parsing first and optionally
  merges locally grounded LLM operations. It never mutates session state.

## 4. Optional semantic interpretation

```mermaid
classDiagram
    direction LR

    class SemanticParser {
        <<protocol>>
        +interpret(message, context) SemanticInterpretation
    }
    class DisabledSemanticParser {
        +interpret(message, context) SemanticInterpretation
    }
    class ResponsesSemanticParser {
        +interpret(message, context) SemanticInterpretation
        -parse_response(response) SemanticInterpretation
    }
    class GatedSemanticParser {
        +provider: SemanticParser
        +max_calls: int
        +cache_size: int
        +interpret(message, context) SemanticInterpretation
        +interpret_eligible(message, context) SemanticInterpretation
        +stats() dict
    }
    class SemanticParserError {
        <<exception>>
    }
    class RuntimeError
    class SemanticSlotHypothesis {
        <<frozen_dataclass>>
        +attribute: str
        +operation: str
        +value: str
        +confidence: float
        +evidence: str
    }
    class SemanticInterpretation {
        <<frozen_dataclass>>
        +query_rewrites: tuple
        +subjective_needs: tuple
        +slot_hypotheses: tuple
        +prompt_tokens: int
        +completion_tokens: int
    }
    class GroundedSemantic {
        <<frozen_dataclass>>
        +query_rewrites: tuple
        +slot_hypotheses: tuple
        +slot_updates: tuple
        +preference_phrases: tuple
        +category_phrases: tuple
        +exclusions: tuple
    }
    class SemanticEscalationDecision {
        <<frozen_dataclass>>
        +should_call: bool
        +reason: str
    }
    class SemanticEscalationPolicy {
        +decide(frame, active, assessment, exact_match) SemanticEscalationDecision
        +decide_before_retrieval(frame, active) SemanticEscalationDecision
        +record_outcome(applied)
        +stats() dict
    }
    class SlotUpdate

    SemanticParser <|.. DisabledSemanticParser : implements
    SemanticParser <|.. ResponsesSemanticParser : implements
    SemanticParser <|.. GatedSemanticParser : implements
    GatedSemanticParser o-- SemanticParser : wraps provider
    RuntimeError <|-- SemanticParserError : inherits
    SemanticInterpretation "1" *-- "many" SemanticSlotHypothesis : contains
    ResponsesSemanticParser ..> SemanticInterpretation : produces
    GatedSemanticParser ..> SemanticInterpretation : caches
    GroundedSemantic "1" *-- "many" SemanticSlotHypothesis : retains accepted
    GroundedSemantic "1" *-- "many" SlotUpdate : converts to
    SemanticEscalationPolicy ..> SemanticEscalationDecision : returns
```

Use notes:

- `SemanticParser` is the provider-neutral interface used by the interpreter.
- `DisabledSemanticParser` returns an empty result, keeping the complete offline
  path available when credentials, network, or permission are absent.
- `ResponsesSemanticParser` owns the Responses-compatible HTTP request and
  parses the forced function-tool arguments; it never selects catalog IDs.
- `GatedSemanticParser` wraps a provider with process call budget, LRU cache,
  timeout fallback metrics, and thread-safe counters.
- `SemanticParserError` is the sanitized provider failure type caught by the
  gate; it inherits normal `RuntimeError` behavior.
- `SemanticSlotHypothesis` is one untrusted model proposal with an evidence span
  and explicit operation.
- `SemanticInterpretation` is the complete provider result plus reported token
  usage before local grounding.
- `GroundedSemantic` contains only hypotheses, rewrites, and state deltas that
  passed local evidence and safety checks.
- `SemanticEscalationDecision` explains whether a billed call is justified.
- `SemanticEscalationPolicy` owns the mutually exclusive pre-retrieval and
  retrieval-aware call decisions plus non-secret outcome counters.

The grounding operation itself is intentionally a pure function in
`semantic_grounding.py`; it converts `SemanticInterpretation` into
`GroundedSemantic` without owning either object.

## 5. Conversation state and clarification

```mermaid
classDiagram
    direction LR

    class ActiveState {
        +category_phrases: list
        +preference_phrases: list
        +exclusions: list
        +slot_values: dict
        +search_rewrites: list
        +suppressed_attributes: set
        +asked_attributes: list
        +query_terms() tuple
        +context_snapshot(last_attribute) str
    }
    class SessionState {
        +session_id: str
        +customer_profile: dict
        +active: ActiveState
        +last_ask_attribute: str?
        +recommendation_exposure: set
        +clarification_outcomes: dict
        +semantic_call_count: int
        +answerability_posterior(prior, strength) float
    }
    class SessionStore {
        +reset(session_id, profile) SessionState
        +get(session_id) SessionState
    }
    class StateReducer {
        +apply(state, frame) SessionState
        +apply_semantic(state, frame) bool
    }
    class QuestionDecision {
        <<frozen_dataclass>>
        +ask_attribute: str?
        +message: str?
        +question_value: float?
        +reason: str
    }
    class QuestionPolicy {
        +choose(state, candidates, assessment, turn) QuestionDecision
    }
    class IntentFrame
    class CandidateEvidence
    class RetrievalAssessment
    class CatalogStore
    class AgentConfig
    class AttributeValueResolver {
        <<protocol>>
    }

    SessionState *-- ActiveState : current intent
    SessionStore "1" *-- "many" SessionState : owns by session ID
    StateReducer o-- AttributeValueResolver : correction grounding
    StateReducer --> SessionState : mutates only through
    StateReducer ..> IntentFrame : applies
    QuestionPolicy --> CatalogStore : candidate attributes
    QuestionPolicy --> AgentConfig : thresholds
    QuestionPolicy ..> SessionState : reads posterior/history
    QuestionPolicy ..> CandidateEvidence : partitions shortlist
    QuestionPolicy ..> RetrievalAssessment : reads confidence
    QuestionPolicy ..> QuestionDecision : returns
```

Use notes:

- `ActiveState` holds only the current customer intent. LLM rewrites are kept
  separate from durable customer facts so corrections can invalidate them.
- `SessionState` adds turn history, profile, product exposure, clarification
  outcomes, and the per-session semantic-call counter around `ActiveState`.
- `SessionStore` owns independent session objects behind a lock. It fails
  clearly if `respond` reaches `get` before the required `reset` call.
- `StateReducer` is the only intended writer of active intent. It applies each
  attribute operation independently so unrelated constraints persist.
- `QuestionDecision` is the immutable result of clarification scoring.
- `QuestionPolicy` scores candidate coverage, diversity, catalog answerability,
  session outcomes, and retrieval confidence while excluding already asked or
  suppressed fields.

## 6. Retrieval, fusion, and ranking

```mermaid
classDiagram
    direction LR

    class RetrievalPlan {
        <<frozen_dataclass>>
        +focus_score: float
        +generator_weights: dict
        +generator_limit: int
    }
    class CandidateEvidence {
        <<dataclass>>
        +parent_asin: str
        +generator_ranks: dict
        +raw_scores: dict
        +rrf_score: float
        +final_score: float
    }
    class RetrievalAssessment {
        <<frozen_dataclass>>
        +candidate_count: int
        +generator_agreement: float
        +top10_stability: float
    }
    class RetrievalPlanner {
        +plan(active) RetrievalPlan
    }
    class LexicalRetriever {
        +retrieve(active, plan) dict
    }
    class LightweightReranker {
        +rank(candidates, active, profile) list
    }
    class BudgetRange {
        <<frozen_dataclass>>
        +lower: float?
        +upper: float?
        +approximate: bool
    }
    class CatalogStore
    class CatalogSearchResult
    class ActiveState
    class AgentConfig
    class FusionFunctions {
        <<utility_module>>
        +reciprocal_rank_fusion(results, weights, k) list
        +assess_results(results, fused, overlap, scale) RetrievalAssessment
    }
    class RankingUtilities {
        <<utility_module>>
        +parse_budget(text) BudgetRange
        +price_signal(price, values) float
        +unseen_first(candidates, exposure) list
        +explain(active) str
    }

    RetrievalPlanner --> AgentConfig : focus and route weights
    RetrievalPlanner ..> ActiveState : reads
    RetrievalPlanner ..> RetrievalPlan : produces
    LexicalRetriever --> CatalogStore : five searches
    LexicalRetriever --> AgentConfig : depth limits
    LexicalRetriever ..> ActiveState : query terms
    LexicalRetriever ..> RetrievalPlan : route limit
    LexicalRetriever ..> CatalogSearchResult : produces lists of
    FusionFunctions ..> CatalogSearchResult : consumes
    FusionFunctions ..> CandidateEvidence : creates and updates
    FusionFunctions ..> RetrievalAssessment : produces
    LightweightReranker --> CatalogStore : product evidence and IDF
    LightweightReranker --> AgentConfig : score weights
    LightweightReranker ..> ActiveState : active constraints
    LightweightReranker --> CandidateEvidence : mutates final score
    RankingUtilities ..> BudgetRange : parses
    RankingUtilities ..> CandidateEvidence : exposure ordering
    RankingUtilities ..> ActiveState : explanation
```

Use notes:

- `RetrievalPlan` freezes the current Buying/Browsing focus score, blended route
  weights, and per-route depth for one retrieval pass.
- `CandidateEvidence` is the mutable cross-stage carrier: fusion records route
  ranks and RRF score, then the reranker adds `final_score`.
- `RetrievalAssessment` summarizes candidate count, generator agreement, and
  Top-10 stability for semantic gating and question confidence.
- `RetrievalPlanner` converts accumulated evidence into a soft focused versus
  exploratory blend rather than assigning a permanent scenario label.
- `LexicalRetriever` runs field, title, category, category-popularity, and
  focused-constraint candidate generators against the same frozen store.
- `LightweightReranker` combines normalized RRF, IDF coverage, exact phrases,
  capped profile/popularity evidence, budget fit, and exclusion penalties.
- `BudgetRange` is the normalized optional lower/upper price constraint returned
  by the function-based budget parser.

`FusionFunctions` and `RankingUtilities` are diagrammed as module nodes because
they are stateless functions, not instantiated classes.

## 7. Response boundary

```mermaid
classDiagram
    direction LR

    class ShoppingAgent
    class ResponseGuard {
        +build(message, ask_attribute, recommendations, top_k, tokens) dict
    }
    class CatalogStore {
        +valid_ids: frozenset
        +popular(limit) tuple
    }
    class QuestionDecision
    class CandidateEvidence

    ShoppingAgent --> QuestionDecision : chooses customer question
    ShoppingAgent --> CandidateEvidence : orders recommendations
    ShoppingAgent *-- ResponseGuard : owns final boundary
    CatalogStore --> ResponseGuard : supplies valid IDs and fallback order
```

Use note:

- `ResponseGuard` is the last API boundary. It removes invalid/duplicate IDs,
  caps recommendations at ten, validates `ask_attribute`, normalizes token
  counts, and fills safely from catalog popularity when needed.

## 8. Development split classes

```mermaid
classDiagram
    direction LR

    class SplitConfig {
        <<frozen_dataclass>>
        +seed: str
        +holdout_fraction: float
        +development_folds: int
    }
    class DevelopmentSplits {
        <<frozen_dataclass>>
        +seed: str
        +sealed_holdout: tuple
        +folds: tuple
        +group_by_sample: dict
        +scenario_by_sample: dict
        +training_ids(validation_fold) tuple
        +validation_ids(validation_fold) tuple
        +as_dict() dict
    }

    SplitConfig ..> DevelopmentSplits : controls construction of
```

Use notes:

- `SplitConfig` fixes the deterministic seed, release-check fraction, and number
  of development folds.
- `DevelopmentSplits` stores target/title-family-disjoint sample assignments and
  exposes rotating training/validation IDs. It is development-only and is never
  imported by submission runtime code.

## Reading order

For a first code trace, read the classes in this order:

1. `Agent` and `ShoppingAgent` for orchestration.
2. `IntentFrame`, `SlotUpdate`, `ActiveState`, and `StateReducer` for the
   interpretation-to-memory contract.
3. `RetrievalPlan`, `LexicalRetriever`, `CandidateEvidence`, and
   `LightweightReranker` for product ordering.
4. `QuestionPolicy` for the feedback loop.
5. `SemanticEscalationPolicy`, `GatedSemanticParser`, and
   `ResponsesSemanticParser` for optional LLM behavior.
6. `ResponseGuard` for the final competition-safe response.

