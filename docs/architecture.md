# Shopping Copilot Architecture and Implementation Map

This document turns the competition's four pillars into concrete modules, interfaces, tests, and ownership boundaries. The required public entry point remains `starter.agent.Agent`; all substantial implementation belongs in the `shopping_copilot/` package described below.

For the one-page version, see [pipeline-summary.md](pipeline-summary.md).

## Product thesis

The agent will find the exact hidden `parent_asin` through a deterministic, stateful retrieve–clarify–rerank loop optimized for immediate Top-10 discovery:

1. interpret the current customer message as typed state updates;
2. estimate a continuous `focus_probability` without assuming the hidden evaluation scenario;
3. run all cheap candidate generators and blend their weights instead of hard-switching pipelines;
4. use initial candidate diagnostics to recalibrate the retrieval plan;
5. fuse and rerank candidates using explicit constraints and current session state;
6. return the best available Top 10 on every turn and ask one clarification only when its expected future gain justifies the turn cost;
7. validate every response against the Agent API contract.

The public set is development data, not runtime knowledge. The Agent must never consume public ground truth, evaluator intent cards, or reconstructed purchase histories.

## Metric-aligned control objective

Intent labels are not scored. The runtime objective is to maximize the probability that the Target Product is in the current turn's Top 10, place the best candidate as high as possible for MRR, and avoid questions that delay discovery without enough expected benefit.

The control priorities are:

1. candidate recall — the target cannot be reranked if no generator retrieves it;
2. immediate Top-10 coverage — return recommendations on every turn, including clarification turns;
3. final ordering — move the most plausible target toward rank 1;
4. question value — ask only when the expected next-turn improvement exceeds the MTTC cost and miss risk;
5. conversational polish — useful, but subordinate to exact-ASIN discovery.

`focus_probability` is therefore a routing feature, not a prediction target. A value near `1.0` favors explicit-constraint precision; a value near `0.0` favors broad semantic exploration. It must never prevent otherwise useful cheap generators from contributing candidates.

## End-to-end flow

```text
reset(session_id, user_profile)
    -> validate and freeze CustomerProfile
    -> create isolated SessionState

respond(session_id, user_message, turn, top_k)
    -> MessageInterpreter.parse(current message, compact state)
    -> StateReducer.apply(IntentFrame)
    -> IntentAssessor estimate pre-retrieval focus_probability
    -> RetrievalPlanner build a blended initial plan
    -> cheap CandidateGenerators retrieve an initial union
    -> RetrievalDiagnostics measure agreement, spread, and constraint coverage
    -> RetrievalPlanner calibrate weights and gate optional stages
    -> optional semantic generator expand the union when justified
    -> ReciprocalRankFusion.merge candidate evidence
    -> ConstraintEvaluator assign match/contradiction/unknown
    -> Reranker order candidates and estimate Top10Confidence
    -> QuestionPolicy choose recommend or ask-and-recommend
    -> ResponseGuard validate and deduplicate exact parent_asin values
    -> append TurnRecord and diagnostics
    -> return Agent response
```

## Target package structure

```text
starter/
|-- agent.py                         Thin official-interface adapter

shopping_copilot/
|-- __init__.py
|-- agent.py                         End-to-end orchestrator
|-- config.py                        Typed defaults and experiment configuration
|-- contracts.py                     Internal protocol types and response guard
|
|-- catalog/
|   |-- models.py                    ProductRecord, PriceValue, field provenance
|   |-- loader.py                    Read-only JSONL validation and loading
|   |-- normalization.py             Conservative text/value normalization
|   |-- attributes.py                Catalog attribute extraction and aliases
|   `-- store.py                     Immutable product lookup and indexes
|
|-- understanding/
|   |-- models.py                    IntentFrame, SlotUpdate, ambiguity types
|   |-- interpreter.py               Extraction pipeline coordinator
|   |-- intent.py                    Pre-retrieval focus and stage assessment
|   |-- rules.py                     Price, size, negation, override, ANY rules
|   |-- grounding.py                 Link spans to catalog categories/attributes
|   `-- semantic.py                  Optional low-confidence semantic/LLM parser
|
|-- dialog/
|   |-- models.py                    CustomerProfile, SessionState, TurnRecord
|   |-- store.py                     session_id -> SessionState lifecycle
|   |-- reducer.py                   Deterministic state transitions
|   `-- policy.py                    Question selection and action policy
|
|-- retrieval/
|   |-- models.py                    RetrievalRequest, RetrievalPlan, CandidateHit
|   |-- lexical.py                   Title and field-weighted FTS generators
|   |-- attributes.py                Category/attribute candidate generator
|   |-- dense.py                     Optional in-memory semantic generator
|   |-- fusion.py                    Reciprocal Rank Fusion
|   `-- planner.py                   Soft weight blending and two-pass calibration
|
|-- ranking/
|   |-- constraints.py               match/contradiction/unknown evaluation
|   |-- reranker.py                  Focus-weighted lightweight reranker
|   |-- semantic.py                  Cost-gated semantic/LLM Top-N reranker
|   `-- diversity.py                 Optional exploratory-list diversification
|
`-- observability/
    |-- diagnostics.py               Pool uncertainty and generator contribution
    `-- trace.py                     Safe per-turn decision traces

tests/
|-- unit/
|   |-- test_catalog_loader.py
|   |-- test_normalization.py
|   |-- test_message_interpreter.py
|   |-- test_intent_assessor.py
|   |-- test_state_reducer.py
|   |-- test_retrieval_planner.py
|   |-- test_constraint_evaluator.py
|   |-- test_fusion.py
|   |-- test_top10_confidence.py
|   |-- test_question_policy.py
|   `-- test_response_guard.py
|-- integration/
|   |-- test_buying_session.py
|   |-- test_browsing_session.py
|   |-- test_override_session.py
|   `-- test_boundary_session.py
`-- test_evaluator.py                Existing official-harness tests
```

Do not create all files before they are needed. Add them in the implementation order at the end of this document.

## Shared domain contracts

The modules communicate through typed objects rather than unstructured dictionaries.

### Catalog types

```python
@dataclass(frozen=True)
class PriceValue:
    value: float | None
    kind: Literal["exact", "lower_bound", "unknown"]


@dataclass(frozen=True)
class ProductRecord:
    parent_asin: str
    raw: Mapping[str, object]
    search_fields: Mapping[str, str]
    categories: tuple[str, ...]
    attributes: Mapping[str, frozenset[str]]
    attribute_sources: Mapping[str, tuple[str, ...]]
    price: PriceValue
    average_rating: float | None
    rating_number: int | None
    field_presence: frozenset[str]
```

`ProductRecord` is immutable. Missing data remains missing; normalization must never invent product facts.

### Understanding types

```python
@dataclass(frozen=True)
class SlotUpdate:
    attribute: Attribute
    operation: Literal["set", "add", "exclude", "clear", "set_any", "refine"]
    raw_span: str
    normalized_values: tuple[str, ...]
    strength: Literal["hard", "soft"]
    confidence: float
    explicit: bool
    source_turn: int


@dataclass(frozen=True)
class IntentFrame:
    dialogue_acts: tuple[str, ...]
    slot_updates: tuple[SlotUpdate, ...]
    product_terms: tuple[str, ...]
    subjective_needs: tuple[str, ...]
    residual_terms: tuple[str, ...]
    ambiguities: tuple[str, ...]


@dataclass(frozen=True)
class IntentAssessment:
    decision_stage: Literal["exploring", "narrowing", "deciding", "unknown"]
    focus_probability: float
    reason_codes: tuple[str, ...]
```

The interpreter proposes an `IntentFrame`; only `dialog/reducer.py` may mutate session state.

### Session types

```python
@dataclass(frozen=True)
class CustomerProfile:
    purchase_frequency: str
    average_prior_rating: float | None
    rating_style: str
    preference_tags: tuple[str, ...]
    summary: str


@dataclass
class SlotState:
    mode: Literal["unknown", "any", "value"]
    included: dict[str, SlotEvidence]
    excluded: dict[str, SlotEvidence]
    overridden: list[SlotEvidence]


@dataclass
class SessionState:
    session_id: str
    profile: CustomerProfile
    decision_stage: Literal["exploring", "narrowing", "deciding", "unknown"]
    focus_probability: float
    slots: dict[Attribute, SlotState]
    asked_attributes: set[Attribute]
    turns: list[TurnRecord]
    last_diagnostics: RetrievalDiagnostics | None
    last_recommendations: tuple[str, ...]
```

The profile is immutable soft evidence. Explicit current-session evidence takes precedence. `unknown` means not discussed; `any` means the customer explicitly has no preference.

### Retrieval types

```python
@dataclass(frozen=True)
class RetrievalRequest:
    focus_probability: float
    lexical_terms: tuple[str, ...]
    subjective_needs: tuple[str, ...]
    hard_constraints: tuple[Constraint, ...]
    soft_preferences: tuple[Constraint, ...]
    exclusions: tuple[Constraint, ...]
    profile_tags: tuple[str, ...]
    turns_remaining: int
    candidate_limit: int


@dataclass(frozen=True)
class RoutingSignals:
    explicit_hard_constraint_count: int
    category_specificity: float
    commitment_cue_count: int
    exploration_cue_count: int
    unresolved_subjective_need_count: int
    candidate_count: int | None
    generator_agreement: float | None
    category_entropy: float | None
    top_score_margin: float | None
    constraint_evidence_coverage: float | None
    turns_remaining: int


@dataclass(frozen=True)
class RetrievalPlan:
    focus_probability: float
    generator_weights: Mapping[str, float]
    generator_limits: Mapping[str, int]
    use_dense: bool
    use_semantic_reranker: bool
    reason_codes: tuple[str, ...]


@dataclass
class CandidateHit:
    parent_asin: str
    generator_ranks: dict[str, int]
    generator_scores: dict[str, float]
    matched_fields: set[str]
    constraint_results: dict[str, str]
    fusion_score: float
    reranker_score: float
    final_score: float
    reasons: list[str]


@dataclass(frozen=True)
class RetrievalDiagnostics:
    candidate_count: int
    generator_counts: Mapping[str, int]
    generator_agreement: float
    category_entropy: float
    top_score_margin: float
    constraint_evidence_coverage: float
    top10_stability: float
    latency_ms: float


@dataclass(frozen=True)
class Top10Confidence:
    value: float
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ActionDecision:
    ask_attribute: Attribute | None
    recommend_count: int
    question_value: float | None
    reason_codes: tuple[str, ...]
```

Candidate scores remain inspectable. A single opaque score must not erase generator ranks or constraint evidence.

# Pillar I — Intent Routing and Hybrid Pipeline

## 1. CatalogStore

**Location:** `shopping_copilot/catalog/`

**Implement:**

- validate 50,000 unique `parent_asin` records;
- preserve raw records and create immutable normalized views;
- keep title, categories, features, details, store, and description separate;
- parse prices as exact, lower-bound, or unknown;
- extract category, material, color, size, style, brand, feature, and use-case evidence with provenance;
- build in-memory product, FTS, category, and attribute indexes;
- expose deterministic lookup by `parent_asin`.

**Missing-data rules:**

- never drop a valid ASIN because an optional field is absent;
- never index the literal strings `null`, `none`, or `unknown`;
- missing attribute evidence produces `unknown`, not contradiction;
- `store` is brand-like evidence, not guaranteed brand truth;
- missing price is retained as unknown and is not automatically out of budget.

**Tests:** malformed rows, empty fields, invalid price strings, lower-bound prices, duplicate ASIN detection, stable normalization.

## 2. MessageInterpreter

**Location:** `shopping_copilot/understanding/`

**Implement in layers:**

1. deterministic parsing for price, size, negation, alternatives, corrections, override markers, and no-preference language;
2. catalog-grounded extraction for categories, materials, colors, styles, stores/brands, features, and use cases;
3. explicit-versus-implicit classification so inferred attributes remain soft;
4. optional semantic parser only for unresolved subjective language;
5. schema and confidence validation before returning an `IntentFrame`.

Consumer utterances may be product-led (`black running shoes`), need-led (`comfortable for standing all day`), negative (`not polyester`), alternative (`black or navy`), corrective (`actually, white`), or indifferent (`no preference`). Preserve subjective phrases for semantic retrieval rather than forcing all language into hard slots.

**Tests:** one table-driven suite covering direct requests, softness, exclusions, alternatives, boundary answers, corrections, category overrides, relative language, subjective needs, and compound constraints.

## 3. IntentAssessor and soft routing

**Location:** `shopping_copilot/understanding/intent.py`

Intent assessment returns a decision stage and `focus_probability`; it does not predict the hidden Buying/Browsing scenario. The initial assessment uses only participant-visible evidence:

- explicit hard-constraint count;
- product/category specificity, estimated from catalog category pool size;
- numeric price or size constraints;
- commitment cues such as `must`, `need`, `only`, and explicit exclusions;
- exploration cues such as `exploring`, `not sure`, broad occasions, or requests for ideas;
- unresolved subjective-need count;
- active session constraints, `ANY` slots, corrections, and turns remaining.

The first implementation should be deterministic and configured through named weights. It must emit reason codes, not just a number. For example:

```python
IntentAssessment(
    decision_stage="narrowing",
    focus_probability=0.72,
    reason_codes=("specific_category", "explicit_material", "unresolved_use_case"),
)
```

Use this provisional, explicitly ablatable initialization:

```text
start at 0.50
+ 0.15 per explicit hard constraint, capped at +0.30
+ 0.10 × category_specificity
+ 0.05 per commitment cue, capped at +0.10
- 0.10 per exploration cue, capped at -0.20
- 0.10 when the request has subjective needs but no grounded product/category
clip to [0.05, 0.95]
```

`category_specificity` is normalized from the number of catalog products in the grounded category; a small leaf category is more specific than `clothing`. These constants belong in `config.py`, not inline parser rules, and E7 must compare them against uniform fusion and a hard 0/1 route.

Do not hard-code evaluator wording such as `key requirement` or `still exploring`. Cover those public templates, but test paraphrases and rely on extracted meaning.

The profile does not determine route intent. It is a soft prior applied after current session evidence and is suppressed by an explicit exclusion or `ANY` response.

## 4. RetrievalPlanner and candidate generators

**Location:** `shopping_copilot/retrieval/`

All generators implement:

```python
class CandidateGenerator(Protocol):
    name: str

    def retrieve(self, request: RetrievalRequest, limit: int) -> list[CandidateHit]:
        ...
```

Initial generators:

| Generator | Role | Initial depth |
|---|---|---:|
| Title FTS | High-precision product/category terms | 100 |
| Field-weighted FTS | Broad lexical recall | 150 |
| Category/attribute | Explicit normalized evidence | 100 |
| Dense semantic | Vague use cases and subjective needs; optional | 100 |

All cheap generators run for every non-empty request. `focus_probability` blends their endpoint weights rather than selecting one pipeline:

```python
weight[g] = (
    focus_probability * focused_weight[g]
    + (1.0 - focus_probability) * exploratory_weight[g]
)
```

Provisional endpoint weights and depths:

| Generator | Focused weight | Exploratory weight | Depth |
|---|---:|---:|---:|
| Title FTS | 1.0 | 0.7 | 100 |
| Field-weighted FTS | 0.8 | 1.0 | 150 |
| Category/attribute | 1.3 | 0.9 | 100 |
| Dense semantic | 0.6 | 1.2 | 100 when enabled |

These are starting controls, not claimed optimal values. All weights, depths, the RRF constant, and optional-stage budgets belong in immutable typed configuration recorded with each experiment.

The initial plan runs title FTS, field-weighted FTS, and category/attribute retrieval. It then measures:

- generator agreement, using overlap or rank correlation;
- candidate and category spread;
- score margin near the Top-10 boundary;
- proportion of active constraints with usable product evidence;
- Top-10 stability under small generator-weight perturbations;
- latency already consumed this turn.

`RetrievalPlanner.calibrate()` uses these diagnostics to update `focus_probability`, generator depths, and optional-stage gates. Dense retrieval is enabled only when subjective language or low lexical agreement indicates a recall problem. Semantic reranking is enabled only for a small uncertain Top-N pool and only within its latency/cost budget.

Buying and Browsing remain evaluator scenario labels that the Agent never receives. Focused and Exploratory are endpoints of a blended retrieval plan, not mutually exclusive runtime modes.

## 5. Fusion, constraint evaluation, and reranking

**Locations:** `retrieval/fusion.py`, `ranking/`

Fuse incomparable generator ranks with weighted Reciprocal Rank Fusion:

```python
score(product) = sum(weight[g] / (60 + rank[g]))
```

Then evaluate every active constraint as `match`, `contradiction`, or `unknown`.

The reliable path uses the lightweight reranker. A `SemanticReranker` may then inspect only a small Top-N pool (for example 20–30 candidates) using compact current context. It must be timeout-bounded, return scores only for supplied ASINs, and fall back to the lightweight order. This implements the pillar's semantic-ranking direction without making an external model a single point of failure.

Focused-route ordering:

1. no verified hard contradictions;
2. more verified hard matches;
3. higher fused relevance;
4. soft session and profile preferences;
5. small normalized popularity prior;
6. stable ASIN tie-break.

Exploratory-route ordering emphasizes semantic/use-case relevance and may apply diversity after relevance ranking. Missing fields never earn false matches or automatic penalties.

The lightweight reranker must also emit a `Top10Confidence` estimate. It cannot use the hidden target. Initial features are generator agreement, constraint satisfaction, unknown-field rate, category concentration, score margin, and Top-10 stability. Calibrate thresholds offline on development folds; retain a deterministic heuristic fallback.

For the first heuristic, normalize each feature to `[0, 1]` and compute:

```text
Top10Confidence =
    0.30 × generator_agreement
    + 0.25 × constraint_evidence_coverage
    + 0.20 × top10_stability
    + 0.15 × normalized_score_margin
    + 0.10 × (1 - normalized_category_entropy)
```

Treat this as a confidence ordering rather than a calibrated probability until offline calibration demonstrates otherwise. Store both the score and feature values in diagnostics.

**Required diagnostics:** target recall at candidate depths 10/50/100/300, marginal recall per generator, fusion rank, final rank, pool size, Top-10 stability, confidence reason codes, and latency.

# Pillar II — Multi-Turn Scenario Evolution

## 1. Session lifecycle

**Locations:** `shopping_copilot/dialog/store.py`, `dialog/models.py`

`reset()` validates the anonymized profile and creates one isolated `SessionState`. `respond()` requires an existing session and applies exactly one ordered turn. No state is shared between sessions.

Raw turn history is retained for diagnostics, but retrieval consumes the active structured state rather than concatenated historical text.

`SessionState.focus_probability` is updated on every turn. It is not a permanent label: the same session may move from exploring to narrowing to deciding as constraints accumulate.

## 2. Deterministic StateReducer

**Location:** `shopping_copilot/dialog/reducer.py`

Transition invariants:

- additions preserve compatible active values;
- direct correction replaces the previous value for that slot;
- an exclusion is negative evidence, not a positive keyword;
- `set_any` clears values and suppresses profile evidence for that attribute;
- a category-changing override clears incompatible category-specific slots;
- explicit session evidence outranks the CustomerProfile;
- implicit or low-confidence evidence cannot become a hard filter;
- overridden values remain in audit history but not in `RetrievalRequest`.

After any correction or Intent Override, state replacement occurs before retrieval. The new Top 10 must be generated immediately from the replacement state; stale values cannot remain as query terms or hard filters.

## 3. QuestionPolicy

**Location:** `shopping_copilot/dialog/policy.py`

Choose between:

- recommend;
- ask and recommend.

The normal path always returns up to 10 recommendations, including on a clarification turn. An ask-only response gives up an immediate hit opportunity and requires explicit experimental evidence before it can be enabled.

For each unanswered attribute, estimate:

```text
QuestionValue(attribute) =
    partition_gain
    × answerability
    × estimated_next_top10_gain
    × remaining_turn_factor
    - turn_cost
    - repeat_or_boundary_risk
```

- `partition_gain`: how strongly the attribute divides plausible current candidates;
- `answerability`: candidate evidence coverage and likelihood that the customer has a preference;
- `estimated_next_top10_gain`: expected improvement over the current ranked list;
- `remaining_turn_factor`: decreases as the session approaches turn 10;
- `turn_cost`: MTTC cost plus the risk that the next result is still a miss;
- `repeat_or_boundary_risk`: penalty for previously asked, unavailable, or declined attributes.

The first implementation can estimate `partition_gain` from the top candidate pool using Gini impurity:

```text
partition_gain(attribute) = 1 - sum(p(value)²)
```

Compute it only over grounded values, then multiply by attribute evidence coverage. A practical target-blind approximation is:

```text
estimated_next_top10_gain =
    partition_gain
    × evidence_coverage
    × (1 - Top10Confidence)

remaining_turn_factor = max(0, (10 - turn) / 9)
```

All penalty constants and the ask threshold belong in `config.py`. Log the individual components so E10 can determine whether a bad decision came from answerability, partitioning, confidence, or thresholding.

Ask only when the best positive QuestionValue exceeds a calibrated threshold and `Top10Confidence` is insufficient. Set exactly one allowed `ask_attribute` matching the natural-language question.

Boundary behavior stores `ANY`, avoids repeating that attribute, and continues with valid recommendations. Raise the question threshold on late turns; turn 10 always recommends and never depends on another reply.

**Required action traces:** chosen attribute, value components, confidence, recommendations returned, turns remaining, and reason for asking or not asking.

## 4. ResponseGuard

**Location:** `shopping_copilot/contracts.py`

Before returning:

- validate `ask_attribute`;
- retain only catalog-valid ASINs;
- deduplicate while preserving rank;
- cap recommendations at `min(top_k, 10)`;
- validate non-negative usage values;
- fall back to deterministic lexical recommendations on component failure.

# Pillar III — Dynamic Context Programming

In this project, self-evolution means runtime adaptation within one session. It does not mean changing model weights, mutating the catalog, reconstructing purchase history, or learning across evaluator users.

## 1. Context distillation

**Locations:** `dialog/reducer.py`, `retrieval/planner.py`

Build a compact active snapshot after every message:

```text
focus_probability + decision stage
+ active hard constraints + exclusions + soft preferences
+ unresolved subjective needs + profile tags not overridden
+ attributes already asked + last recommendation summary
+ retrieval diagnostics + turns remaining
```

This snapshot replaces full-history prompt accumulation. It keeps current intent prominent, reduces token cost, and prevents stale override terms from re-entering retrieval.

## 2. Adaptive orchestration

**Locations:** `retrieval/planner.py`, `dialog/policy.py`, `shopping_copilot/agent.py`

Adapt from measurable state:

| Runtime evidence | Adaptation |
|---|---|
| Explicit category and hard constraints | Increase focus probability and precision weights |
| Vague use case or diffuse scores | Decrease focus probability and broaden semantic evidence |
| Verified contradiction removes most candidates | Ask before relaxing |
| Important values remain unknown | Retain unknown candidates below matches |
| Customer corrects category/value | Replace state and rerun retrieval |
| Customer says no preference | Mark `ANY`, suppress that question/filter |
| Candidate union lacks agreement | Increase candidate depth or enable dense retrieval |
| Top 10 is stable with high evidence agreement | Skip clarification and recommend |
| Few turns remain | Raise ask threshold and favor immediate recommendations |
| Optional model failure/timeout | Deterministic fallback |

Every adaptation records a reason in the turn trace. No runtime branch may inspect ground truth.

The orchestrator should follow this control structure:

```python
frame = interpreter.parse(user_message, state)
state = reducer.apply(state, frame)

pre_signals = intent_assessor.pre_retrieval_signals(state, frame, turn)
initial_plan = retrieval_planner.initial_plan(pre_signals)
initial_hits = cheap_generators.retrieve(request_from(state), initial_plan)

diagnostics = diagnose(initial_hits, state)
final_plan = retrieval_planner.calibrate(initial_plan, diagnostics)
candidate_hits = maybe_expand(initial_hits, final_plan)

fused = fusion.fuse(candidate_hits, final_plan.generator_weights)
ranked = reranker.rank(fused, state)
confidence = confidence_estimator.score(ranked, diagnostics, state)
action = question_policy.choose(ranked, confidence, diagnostics, state, turn)

response = response_guard.build(action, ranked[:10])
session_store.record(state, frame, diagnostics, action, response)
return response
```

## 3. Optional model boundary

**Locations:** `understanding/semantic.py`, `ranking/semantic.py`

An optional LLM may propose structured interpretations, rerank a small uncertain pool, or phrase a question. It must be isolated behind an interface with timeout, schema validation, token accounting, and deterministic fallback. It must not generate ASINs absent from the candidate pool.

# Pillar IV — Product and Efficiency Evaluation

## 1. Protected evaluation boundary

Do not modify `evaluator/local_evaluator.py`, public labels, scoring configuration, or official contracts for reported runs. The Agent never imports evaluator helpers or reads `ground_truth`.

## 2. Measurement layers

**Official outcome metrics:**

- Hit Rate@10;
- MRR;
- MTTC and Efficiency;
- TechnicalScore;
- the same metrics for Buying, Browsing, Intent Override, and Boundary.

**Engineering diagnostics:**

- target recall at candidate depths 10/50/100/300;
- marginal recall from each generator;
- immediate Top-10 hit rate and hit-turn distribution;
- focus-probability distribution and reason codes, without treating hidden scenario agreement as the objective;
- generator agreement, category entropy, score margin, and Top-10 stability;
- constraint match/unknown/contradiction counts;
- question frequency, estimated QuestionValue, answer outcome, and repeated-question count;
- ask-and-recommend versus recommend-only outcome deltas;
- override replacement correctness;
- startup time, per-turn latency, peak memory;
- token usage, model cost, fallback frequency, and contract failures.

Diagnostics may use public labels only in offline evaluation code, never inside `shopping_copilot/` runtime modules.

## 3. Experiment sequence

| ID | Change | Purpose |
|---|---|---|
| E0 | Original starter | Frozen control |
| E1 | CatalogStore with equivalent FTS | Prove cleaning introduces no regression |
| E2 | Separate title and field-weighted routes | Measure lexical union recall |
| E3 | Category/attribute generator | Measure explicit-constraint recall |
| E4 | Uniform Reciprocal Rank Fusion | Establish multi-route control |
| E5 | State accumulation and reducer | Measure multi-turn benefit |
| E6 | Override and Boundary transitions | Protect scenario correctness |
| E7 | Pre-retrieval soft focus blending | Compare against uniform fusion and hard routing |
| E8 | Two-pass diagnostic calibration | Test whether candidate evidence improves the plan |
| E9 | Constraint-aware reranker | Improve Top-10 rank and MRR |
| E10 | Always-recommend question policy | Compare against no-question and ask-only controls |
| E11 | Optional dense generator | Keep only if marginal recall justifies cost |
| E12 | Optional semantic/LLM stage | Keep only if score gain survives latency/cost |

Change one material variable at a time and retain the same evaluator conditions.

## Implementation ownership for five collaborators

Replace member placeholders with names in the team's coordination system.

| Workstream | Driver | Reviewer | Owned paths | Required handoff |
|---|---|---|---|---|
| Catalog and indexes | Member 1 | Member 2 | `shopping_copilot/catalog/`, catalog unit tests | Immutable `CatalogStore` API and benchmark |
| Retrieval and fusion | Member 2 | Member 4 | `shopping_copilot/retrieval/` | Candidate generators plus recall diagnostics |
| Understanding and dialog | Member 3 | Member 1 | `understanding/`, `dialog/` | `IntentFrame`, reducer, question policy tests |
| Ranking and evaluation | Member 4 | Member 5 | `ranking/`, experiment tooling | Valid ablations and scenario regression report |
| Integration and delivery | Member 5 | Member 3 | `shopping_copilot/agent.py`, `starter/agent.py`, README/demo | Canonical run path and deterministic fallback |

Member 4 owns experiment validity for the duration of the build. Member 5 is the only integration owner for the official `Agent` path; other workstreams integrate through reviewed module interfaces.

## Implementation order

### Slice 1 — Equivalent reliable path

Create only:

```text
shopping_copilot/catalog/models.py
shopping_copilot/catalog/loader.py
shopping_copilot/catalog/store.py
shopping_copilot/retrieval/models.py
shopping_copilot/retrieval/lexical.py
shopping_copilot/contracts.py
shopping_copilot/agent.py
```

Wire `starter/agent.py` to the new orchestrator and reproduce the original baseline before continuing.

### Slice 2 — Typed state loop

Add understanding models, deterministic rules, `IntentAssessor`, session models/store, and reducer. Integrate one complete `reset`/`respond` path and test one case for each scenario. Intent reason codes and state transitions must be traceable.

### Slice 3 — Multi-route retrieval

Add category/attribute retrieval, uniform Reciprocal Rank Fusion, and candidate-recall diagnostics. Run every cheap generator without route gating. Dense retrieval remains deferred.

### Slice 4 — Soft intent and two-pass planning

Add pre-retrieval `focus_probability`, blended generator weights, `RoutingSignals`, retrieval-plan calibration, and Top-10 stability diagnostics. Compare soft blending against uniform fusion and hard switching.

### Slice 5 — Reranking and metric-aware questions

Add tri-state constraint evaluation, lightweight reranking, `Top10Confidence`, and the always-recommend QuestionPolicy. Run the complete public evaluation and diagnose scenario and hit-turn regressions.

### Slice 6 — Optional improvements

Add dense retrieval or model assistance only when the preceding ablation identifies a specific recall, semantic interpretation, or ranking failure that it can address.

## Definition of done

- One documented command runs the Agent from a clean checkout.
- The official evaluator and protected inputs are unchanged.
- All recommendations are valid, unique frozen-catalog ASINs.
- Every normal turn returns up to 10 recommendations when valid candidates exist.
- Buying, Browsing, Intent Override, and Boundary have integration tests.
- The central multi-route/stateful contribution has a controlled ablation.
- Uniform fusion, hard switching, and soft two-pass routing have been compared.
- Question policy has been compared against recommend-only and ask-only controls.
- Overall and scenario metrics, latency, memory, token use, and cost are recorded.
- Optional services have timeouts, validation, and a deterministic fallback.
- No claimed capability or metric is undocumented or unreproduced.

## Options to consider after the reliable path

These are experiment options, not committed dependencies. Adopt an option only when a measured failure identifies its purpose.

| Option | Use when | Keep only if |
|---|---|---|
| Local dense embeddings | Lexical/attribute union misses subjective or vocabulary-mismatch targets | Marginal recall improves enough to justify memory and latency |
| Content-derived product graph | Category aliases and attribute co-occurrence need controlled expansion | It improves recall without leaking labels or over-broadening |
| Learned fusion or lightweight learning-to-rank | Heuristic RRF/reranking has adequate recall but poor final rank | Development-fold gains survive a local holdout and remain interpretable |
| LLM structured interpretation | Deterministic extraction leaves material subjective language unresolved | Schema-valid outputs improve end-to-end metrics within budget |
| LLM/cross-encoder Top-N reranking | Candidate recall is high but MRR remains low | It improves MRR without unacceptable latency, cost, or variance |
| Maximal marginal relevance | Exploratory Top 10 contains near-duplicates | Browsing improves without reducing overall target hits |
| Synthetic utterance robustness suite | Parser rules cover only evaluator templates | It tests paraphrases without being reported as official evaluation data |

Do not pursue collaborative filtering, sequence models over purchase history, multimodal retrieval, social signals, or fraud detection: the Agent does not receive the required histories, images, interactions, reviews, or identities, and multimodal processing is out of scope.

## References

### Authoritative challenge material

- [Competition specification](competition_specification.md)
- [Agent API contract](agent_api_contract.json)
- [Evaluation configuration](evaluation_config.json)
- [Published baseline](baseline_results.json)
- [Submission rules](submission_rules.md)
- [Amazon Reviews 2023 dataset documentation](https://amazon-reviews-2023.github.io/)

### Technical background

- [Implicit query parsing for product search](https://www.amazon.science/publications/implicit-query-parsing-for-product-search) — distinguishes explicit from implicit product attributes.
- [AVEN-GR: Attribute value extraction and normalization using product graphs](https://www.amazon.science/publications/aven-gr-attribute-value-extraction-and-normalization-using-product-graphs) — motivates separate extraction and catalog entity linking.
- [End-to-End Conversational Search for Online Shopping with Utterance Transfer](https://aclanthology.org/2021.emnlp-main.280/) — discusses conversational retrieval under imperfect product schemas.
- [Towards Translating Objective Product Attributes Into Customer Language](https://aclanthology.org/2024.naacl-industry.20/) — motivates retaining subjective customer needs alongside objective attributes.
- [Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods](https://doi.org/10.1145/1571941.1572114) — basis for rank-level fusion across incomparable generators.
