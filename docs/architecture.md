# Shopping Copilot Technical Architecture

This document is the implementation specification for the TechJam 2026 Conversational E-Commerce Search agent. It defines the runtime stack, algorithms, internal contracts, module boundaries, failure handling, tests, and delivery sequence. The public entry point remains `starter.agent.Agent`.

The authoritative requirements are [competition_specification.md](competition_specification.md), [agent_api_contract.json](agent_api_contract.json), and [evaluation_config.json](evaluation_config.json). The Agent must never read public labels, hidden intent cards, evaluator internals, or ground truth at runtime.

For a one-page overview, see [pipeline-summary.md](pipeline-summary.md).

## 1. Objective and design consequences

The target is one exact catalog `parent_asin`. A session succeeds when that identifier appears among the first ten valid unique recommendations. The optimization objective is:

```text
TechnicalScore = 0.50 * HitRate@10 + 0.30 * MRR + 0.20 * Efficiency
Efficiency     = clip((11 - MTTC) / 10, 0, 1)
```

This produces the following implementation priorities:

1. maximize target recall in the candidate union;
2. return ten recommendations on every usable turn, including clarification turns;
3. rank likely targets as high as possible;
4. after a miss, ask the most answerable and discriminative non-repeated question;
5. apply corrections before retrieval so stale preferences cannot dominate;
6. keep optional models outside the reliable deterministic path.

`Buying`, `Browsing`, `Intent Override`, and `Boundary` are evaluator scenarios. They are not runtime route labels. The Agent estimates current need specificity and retrieval uncertainty from participant-visible evidence only.

## 2. Chosen technology stack

### 2.1 Reliable runtime

| Technology | Version or choice | Purpose |
|---|---|---|
| Python | 3.10+ | Agent implementation and evaluator compatibility |
| Standard library | `dataclasses`, `enum`, `typing`, `re`, `unicodedata`, `json`, `sqlite3`, `math`, `statistics`, `threading` | Typed contracts, parsing, storage, scoring, and session isolation |
| SQLite FTS5 | Bundled with Python SQLite | In-memory BM25 title and multi-field retrieval |
| JSONL | UTF-8 | Frozen catalog input and local trace output |
| `unittest` | Standard library | Unit and integration tests without a required test dependency |
| SHA-256 | `hashlib` | Catalog artifact verification |

The reliable path has no network, LLM, vector database, or GPU dependency. It must run from a clean checkout after the catalog is placed in `data/catalog.jsonl`.

### 2.2 Gated optional stages

These dependencies are introduced only after an ablation demonstrates a specific recall or ranking failure:

| Technology | Concrete choice | Use | Runtime fallback |
|---|---|---|---|
| NumPy | Current compatible release | Exact vector similarity over 50,000 products | Skip dense generator |
| Sentence Transformers | `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions | Product and subjective-query embeddings | Field-weighted FTS |
| Cross encoder | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Rerank at most 30 candidates | Lightweight reranker |
| OpenAI Responses API or local LLM | Provider behind `SemanticParser` protocol | Schema-constrained interpretation of unresolved clauses | Deterministic interpreter |

Dense vectors are stored as normalized `float32` arrays. A `50_000 x 384` matrix is approximately 73 MiB, so exact NumPy dot-product retrieval is simpler than an infrastructure-heavy vector database. Model artifacts are built locally and are not committed unless the team explicitly chooses to distribute them.

## 3. Runtime architecture

```text
reset(session_id, user_profile)
    -> validate CustomerProfile
    -> create isolated SessionState

respond(session_id, message, turn, top_k)
    -> MessageInterpreter.parse(message, DialogueContext)
    -> StateReducer.apply(IntentFrame)
    -> NeedAssessor.assess(ActiveState)
    -> RetrievalPlanner.initial_plan(NeedAssessment)
    -> title FTS + field FTS + attribute retrieval
    -> RetrievalAssessor.measure(candidate evidence)
    -> RetrievalPlanner.calibrate(plan, RetrievalAssessment)
    -> optional dense expansion
    -> weighted Reciprocal Rank Fusion
    -> tri-state ConstraintEvaluator
    -> LightweightReranker
    -> optional Top-N cross-encoder reranker
    -> RecommendationExposureController
    -> CandidateBelief normalization and Top10Confidence
    -> QuestionPolicy.select()
    -> ResponseGuard.build()
    -> append TurnRecord and JSON trace
    -> Agent API response
```

The key separation is:

- `IntentFrame`: what the current message means;
- `ActiveState`: which evidence remains active after corrections;
- `NeedAssessment`: how specific and committed the expressed need is;
- `RetrievalAssessment`: whether the retrieval result is coherent and stable;
- `ActionDecision`: which products and clarification to return.

## 4. Package and ownership boundaries

```text
starter/
`-- agent.py                         Official interface adapter only

shopping_copilot/
|-- __init__.py
|-- agent.py                         End-to-end orchestrator
|-- config.py                        Frozen dataclass configuration
|-- contracts.py                     Protocols and ResponseGuard
|
|-- catalog/
|   |-- models.py                    ProductRecord and provenance types
|   |-- loader.py                    JSONL and checksum validation
|   |-- normalization.py             Text, value, size, and price normalization
|   |-- attributes.py                Alias construction and catalog extraction
|   `-- store.py                     FTS and inverted indexes
|
|-- understanding/
|   |-- models.py                    IntentFrame and SlotUpdate
|   |-- interpreter.py               Parsing cascade coordinator
|   |-- rules.py                     Deterministic operation and numeric rules
|   |-- grounding.py                 Trie matching and catalog entity linking
|   |-- assessment.py                NeedAssessor
|   `-- semantic.py                  Optional SemanticParser adapter
|
|-- dialog/
|   |-- models.py                    SessionState, ActiveState, TurnRecord
|   |-- store.py                     Thread-safe session lifecycle
|   |-- reducer.py                   Deterministic state transitions
|   `-- policy.py                    QuestionPolicy
|
|-- retrieval/
|   |-- models.py                    RetrievalRequest, Plan, CandidateEvidence
|   |-- lexical.py                   Title and field FTS generators
|   |-- attributes.py                Inverted-index candidate generator
|   |-- dense.py                     Optional embedding generator
|   |-- fusion.py                    Weighted RRF
|   |-- assessment.py                RetrievalAssessor and QPP features
|   `-- planner.py                   Initial and calibrated plans
|
|-- ranking/
|   |-- constraints.py               match / contradiction / unknown
|   |-- reranker.py                  Deterministic scoring
|   |-- exposure.py                  Across-turn novelty and override reset
|   |-- belief.py                    CandidateBelief and Top10Confidence
|   `-- semantic.py                  Optional cross-encoder reranker
|
`-- observability/
    |-- diagnostics.py               Metrics and ablation features
    `-- trace.py                     Per-turn JSONL traces

tests/
|-- unit/
|-- integration/
`-- test_evaluator.py                Protected harness tests
```

`starter/agent.py` constructs and delegates to `shopping_copilot.agent.ShoppingAgent`. It must not accumulate business logic.

## 5. Internal contracts

All internal objects are typed dataclasses. Mappings exposed by immutable objects use `Mapping` or are copied before storage.

### 5.1 Catalog contracts

```python
@dataclass(frozen=True)
class PriceValue:
    lower: float | None
    upper: float | None
    kind: Literal["exact", "range", "lower_bound", "unknown"]


@dataclass(frozen=True)
class AttributeEvidence:
    value: str
    source_field: str
    extraction: Literal["structured", "exact_alias", "text_rule"]
    confidence: float


@dataclass(frozen=True)
class ProductRecord:
    parent_asin: str
    raw: Mapping[str, object]
    search_fields: Mapping[str, str]
    categories: tuple[str, ...]
    attributes: Mapping[str, frozenset[str]]
    attribute_evidence: Mapping[str, tuple[AttributeEvidence, ...]]
    price: PriceValue
    average_rating: float | None
    rating_number: int | None
    field_presence: frozenset[str]
```

Missing product data remains absent. It is never converted into the strings `unknown`, `none`, or `null` and never treated as a contradiction.

### 5.2 Understanding contracts

```python
class Attribute(str, Enum):
    CATEGORY = "category"
    MATERIAL = "material"
    COLOR = "color"
    SIZE = "size"
    STYLE = "style"
    BRAND = "brand"
    BUDGET = "budget"
    FEATURE = "feature"
    USE_CASE = "use_case"
    OTHER = "other"


class Relation(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    RANGE = "range"
    CONTAINS = "contains"


@dataclass(frozen=True)
class SlotUpdate:
    attribute: Attribute
    operation: Literal["set", "add", "exclude", "clear", "set_any", "replace"]
    relation: Relation
    normalized_values: tuple[str, ...]
    alternative_group: str | None
    raw_span: str
    char_span: tuple[int, int]
    strength: Literal["hard", "soft"]
    explicitness: Literal["explicit", "inferred"]
    confidence: float
    provenance: Literal[
        "numeric_rule", "catalog_exact", "catalog_alias",
        "fuzzy", "semantic", "llm"
    ]
    source_turn: int


@dataclass(frozen=True)
class IntentFrame:
    dialogue_acts: tuple[str, ...]
    slot_updates: tuple[SlotUpdate, ...]
    product_terms: tuple[str, ...]
    subjective_needs: tuple[str, ...]
    residual_terms: tuple[str, ...]
    ambiguities: tuple[InterpretationAmbiguity, ...]
    parse_confidence: float
```

`alternative_group` preserves OR semantics. For example, `black or navy` creates two color values in one group; it does not create two mandatory color constraints.

### 5.3 State and assessment contracts

```python
@dataclass(frozen=True)
class DialogueContext:
    active_state: ActiveState
    last_ask_attribute: Attribute | None
    last_recommendations: tuple[str, ...]
    turn: int


@dataclass(frozen=True)
class NeedAssessment:
    decision_stage: Literal["exploring", "narrowing", "deciding", "unknown"]
    specificity: float
    commitment: float
    exploration: float
    unresolved_need_ratio: float
    focus_score: float
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalAssessment:
    candidate_count: int
    generator_agreement: float
    normalized_category_entropy: float
    normalized_query_commitment: float
    constraint_evidence_coverage: float
    top10_margin: float
    top10_stability: float
    unexplained_term_ratio: float
    latency_ms: float
```

`focus_score` is an uncalibrated control score in `[0, 1]`, not a probability of the Buying scenario. If a later experiment calibrates it against held-out route utility, the calibrated output must use a different type and name.

### 5.4 Retrieval and ranking contracts

```python
@dataclass(frozen=True)
class RetrievalPlan:
    focus_score: float
    generator_weights: Mapping[str, float]
    generator_limits: Mapping[str, int]
    use_dense: bool
    use_cross_encoder: bool
    reason_codes: tuple[str, ...]


@dataclass
class CandidateEvidence:
    parent_asin: str
    generator_ranks: dict[str, int]
    raw_scores: dict[str, float]
    matched_fields: set[str]
    constraint_results: dict[str, Literal["match", "contradiction", "unknown"]]
    rrf_score: float = 0.0
    lightweight_score: float = 0.0
    semantic_score: float | None = None
    final_score: float = 0.0
    reason_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionDecision:
    ask_attribute: Attribute | None
    question_text: str | None
    recommendations: tuple[str, ...]
    question_value: float | None
    reason_codes: tuple[str, ...]
```

Generator scores are retained for diagnostics; they are never directly added across algorithms without normalization or rank fusion.

## 6. Catalog ingestion and indexes

### 6.1 Validation

`CatalogLoader` streams `data/catalog.jsonl` once and validates:

- each line is a JSON object;
- `parent_asin` is present, non-empty, and unique;
- exactly 50,000 valid records are expected for the official catalog;
- list, mapping, numeric, and text fields have accepted shapes;
- malformed optional values are recorded as missing, not fatal;
- the source SHA-256 matches `SHA256SUMS` when that file is supplied.

Failure to validate ASIN uniqueness or checksum is fatal because exact identity is scored. Missing optional metadata is not fatal.

### 6.2 Conservative normalization

Text normalization uses:

1. Unicode NFKC normalization;
2. `str.casefold()` for lookup forms;
3. whitespace collapse;
4. punctuation-to-space only in token lookup views;
5. preservation of raw text for phrase search and explanations.

Do not stem brand names, sizes, model tokens, or product codes. Units are normalized through explicit rules, for example `in`, `inch`, and `inches` to an inch unit while retaining the numeric value.

### 6.3 Attribute extraction

Structured `details` keys are normalized through an alias table:

```text
material aliases -> material, fabric type, fabric
color aliases    -> color, colour
size aliases     -> size, item size, shoe size
style aliases    -> style, fit type, closure type, sleeve type
brand aliases    -> brand, manufacturer
```

Because structured keys are sparse, `CatalogAttributeExtractor` also scans title, features, description, categories, and store with high-precision lexicons. Every extracted value records its source field and extraction method.

The catalog-derived value lexicon is implemented as a token trie:

- insert normalized multi-token aliases;
- scan messages and product text left-to-right;
- prefer the longest match at a start position;
- retain overlapping matches only when their attributes differ;
- restrict ambiguous aliases using the current category when available.

A custom trie avoids a required native `pyahocorasick` dependency and is adequate for this catalog size.

### 6.4 SQLite FTS5

One in-memory table preserves field boundaries:

```sql
CREATE VIRTUAL TABLE products USING fts5(
    parent_asin UNINDEXED,
    title,
    categories,
    features,
    details,
    store,
    description,
    tokenize='unicode61 remove_diacritics 2'
);
```

The field route starts with these BM25 weights:

```text
parent_asin  0.0
title        6.0
categories   4.0
features     2.5
details      2.5
store        1.5
description  1.0
```

An `fts5vocab` table supplies document frequency. Query construction retains at most 24 discriminative terms by descending IDF so long catalog-derived feature sentences do not create unbounded FTS expressions.

### 6.5 Inverted indexes

`CatalogStore` also builds:

```python
category_to_ids: dict[str, frozenset[str]]
attribute_to_ids: dict[Attribute, dict[str, frozenset[str]]]
token_document_frequency: dict[str, int]
product_by_asin: dict[str, ProductRecord]
```

Set intersections provide fast exact category and attribute retrieval. Products with unknown attributes remain accessible through lexical generators.

## 7. MessageInterpreter

### 7.1 Parsing order

`MessageInterpreter.parse()` runs the following cascade:

1. preserve raw message and offsets;
2. classify dialogue operations;
3. split clauses without losing conjunction scope;
4. run numeric and logical rules;
5. perform exact catalog trie matching;
6. perform conservative alias/fuzzy linking;
7. classify strength and explicitness;
8. retain unresolved phrases for retrieval;
9. optionally invoke `SemanticParser` for unresolved clauses;
10. validate the resulting frame.

Operation detection precedes value extraction. In `Actually, not black—make it white`, `actually` and the contrast determine that black is retracted and white replaces it.

### 7.2 Deterministic rule engine

`understanding/rules.py` uses compiled regular expressions and finite-state handling for:

| Language | Parsed operation |
|---|---|
| `under`, `below`, `no more than`, `<=` | budget `LTE` |
| `over`, `at least`, `>=` | budget `GTE` |
| `between X and Y` | budget or size `RANGE` |
| `around`, `roughly`, `about` | soft range using configurable tolerance |
| `not`, `without`, `avoid`, `anything but` | scoped `exclude` |
| `or`, `either ... or` | one alternative group |
| `and`, comma-separated requirements | independent additions |
| `actually`, `instead`, `ignore earlier`, `make it` | `replace` or `clear` followed by `set` |
| `no preference`, `either is fine`, `your judgment` | `set_any` for the last asked attribute |
| `must`, `only`, `need`, `required` | hard strength |
| `prefer`, `ideally`, `would like`, `nice to have` | soft strength |

Negation scope ends at a contrast marker, clause boundary, or new attribute span. Stopword filtering is never applied before operation parsing.

### 7.3 Contextual and elliptical replies

The last structured question supplies a default attribute only when the reply does not name another attribute:

```text
last ask=color, reply="navy"             -> set color=navy
last ask=material, reply="no preference" -> set_any material
last ask=size, reply="actually wide"     -> replace size=wide
```

Explicit wording in the current message always outranks the default attribute. A reply such as `No preference on brand, but it must be leather` produces both `set_any(brand)` and `set(material=leather)`.

### 7.4 Catalog entity linking

Exact normalized alias matches are preferred. Unmatched spans are compared only with values from the inferred category and attribute using:

```text
link_score =
    0.55 * token_jaccard
  + 0.25 * SequenceMatcher_ratio
  + 0.20 * category_compatibility
```

Initial acceptance rules:

- accept as an explicit normalized value when score `>= 0.84` and the margin over the second candidate is `>= 0.08`;
- otherwise retain an ambiguity and the raw phrase;
- never fuzzy-link one- or two-character values without a size context;
- inferred links remain soft unless an exact alias corroborates them.

These thresholds live in `config.py` and must be ablated; they are not embedded in parsing code.

### 7.5 Confidence and provenance

Initial evidence confidence is based on method rather than a model's self-report:

```text
numeric deterministic rule  0.99
exact catalog value          0.97
exact catalog alias          0.93
contextual reply             0.90
accepted fuzzy link          link_score
semantic/LLM proposal        capped at 0.70 until corroborated
```

Confidence changes ranking strength, not whether raw text reaches retrieval. Low-confidence evidence is never a hard exclusion.

### 7.6 Optional semantic interpretation

`GatedSemanticParser` calls a provider only for subjective or structurally
complex language. Short attribute replies, explicit corrections, Boundary
answers, and simulator-style constraint payloads remain deterministic. The
concrete `OpenAIResponsesSemanticParser` sends a compact Context Snapshot to
`POST /v1/responses` with `store=false`, a strict JSON schema, bounded input and
output, and the configured timeout.

The schema returns short query rewrites, subjective needs, and soft slot
hypotheses. It cannot return product identifiers. Model confidence is capped at
`0.70`; numeric comparisons, negation, overrides, and exact catalog grounding
remain authoritative in deterministic code. Invalid JSON, schema mismatch,
timeout, provider error, or incomplete configuration produces an empty semantic
interpretation and leaves the reliable path unchanged.

### 7.7 Raw evidence preservation

The interpreter emits both structured values and raw retrieval phrases. This is essential because public intent constraints range from short material values to long catalog feature text. A long feature sentence may be difficult to normalize but highly discriminative for lexical retrieval.

## 8. Deterministic session state

`SessionStore` is a `dict[session_id, SessionState]` protected by `threading.RLock`. `reset()` replaces any existing state for the same identifier. No state is shared across sessions.

Only `StateReducer` modifies active state. It applies events in message order with these invariants:

1. explicit current-session evidence outranks Customer Profile evidence;
2. later explicit replacements deactivate earlier values for the same slot;
3. compatible additions remain active;
4. exclusions are stored separately from positive values;
5. `set_any` clears active values for that attribute and suppresses profile evidence;
6. category replacement clears incompatible category-specific size/style values;
7. overridden evidence remains in audit history but not in `RetrievalRequest`;
8. inferred evidence cannot replace explicit evidence;
9. missing evidence does not clear an existing value.

The reducer is event-sourced for traceability:

```text
IntentFrame -> tuple[SlotUpdate] -> apply -> ActiveState
```

Retrieval never uses concatenated raw chat as its only source. It uses Active State plus current raw phrases. This prevents stale override terms from re-entering the query.

## 9. NeedAssessor and soft routing

`NeedAssessor` does not predict a hidden evaluator label. It computes interpretable dimensions from the frame and Active State.

### 9.1 Features and score

```text
category_specificity = 1 - log(1 + category_pool) / log(1 + 50_000)
constraint_density   = min(explicit_active_constraints / 3, 1)
numeric_specificity  = 1 if a size or budget range is active else 0
lexical_specificity  = mean normalized IDF of current product terms
parse_certainty      = IntentFrame.parse_confidence
commitment           = min(hard_or_commitment_cues / 2, 1)
exploration          = min(exploration_or_indifference_cues / 2, 1)
unresolved_need_ratio= unresolved subjective clauses / max(all need clauses, 1)

specificity = clip(
    0.35 * category_specificity
  + 0.25 * constraint_density
  + 0.15 * numeric_specificity
  + 0.15 * lexical_specificity
  + 0.10 * parse_certainty,
  0, 1
)

z = -0.25
    + 1.20 * specificity
    + 0.80 * commitment
    - 1.00 * exploration
    - 0.60 * unresolved_need_ratio

focus_score = 1 / (1 + exp(-z))
```

When no category is grounded, `category_specificity=0`. For a term with document frequency `df` in `N=50_000` products:

```text
normalized_idf(term) = log((N + 1) / (df + 1)) / log(N + 1)
```

The constants are frozen configuration values recorded with every experiment. E7 compares this heuristic against uniform weights and a hard switch. If it does not improve held-out utility, uniform fusion remains the production choice.

### 9.2 Decision stage

Decision stage is descriptive and does not choose a route by itself:

- `exploring`: exploration `>= 0.6` and fewer than two active explicit constraints;
- `deciding`: specificity `>= 0.75` and commitment `>= 0.5`;
- `narrowing`: at least one explicit constraint or resolved category;
- otherwise `unknown`.

## 10. Candidate generation

Every non-empty request runs five cheap lexical rank lists: field, title,
category relevance, category-conditioned popularity, and focused constraint
retrieval. No cheap route is disabled by `focus_score`; the score only changes
their fusion weights.

### 10.1 Query construction

`RetrievalRequest` contains current category hypotheses, raw and normalized product terms, hard constraints, exclusions, soft session preferences, unresolved subjective needs, non-suppressed profile tags, and turns remaining.

FTS syntax is built only from escaped tokens generated by the application. User text is never interpolated directly into SQL or FTS expressions.

Two lexical expressions are produced:

1. a precision expression using exact phrases and `AND` between high-IDF category/product terms;
2. a recall expression using `OR` across the top 24 IDF-ranked terms.

If the precision expression returns fewer than the configured depth, the recall result fills the route.

### 10.2 Title FTS generator

- query only the `title` column;
- retrieve depth 100;
- emphasize exact product/category terms;
- retain raw SQLite BM25 and rank.

### 10.3 Field-weighted FTS generator

- query title, categories, features, details, store, and description;
- use the field weights from section 6.4;
- retrieve depth 200;
- include raw feature phrases and subjective terms;
- use BM25 only for within-generator ordering.

### 10.4 Category/attribute generator

The inverted-index generator retrieves the union of category and positive attribute posting lists. It scores products using:

```text
attribute_score =
    2.5 * verified_hard_matches
  + 1.0 * verified_soft_matches
  + 0.4 * category_match
  - 6.0 * verified_hard_contradictions
  - 1.0 * verified_soft_contradictions
```

Unknown product fields contribute zero. The generator returns the highest 150 products with deterministic ASIN tie-breaking.

### 10.5 Category-conditioned popularity generator

Broad category queries often give hundreds of products identical BM25 category
evidence. ASIN tie-breaking can then exclude a plausible, well-established item
before reranking. The reliable MVP therefore retrieves an `AND` category pool
of up to 800 products and exposes two rank lists from the same pool:

- `category`: original BM25 order for relevance;
- `category_popular`: descending `rating_number`, then BM25 and ASIN.

If the `AND` expression is empty, the pool falls back to `OR`. Popularity is a
separate target-blind candidate source, not a catalog edit or inferred purchase
history. Its RRF weight is lower when the active need is focused so explicit
constraints can dominate. The depth of 800 and route weights are provisional
engineering values requiring target-disjoint tuning.

### 10.6 Optional dense generator

Catalog embedding text is:

```text
title [SEP] leaf categories [SEP] features [SEP] selected details [SEP] description
```

At build time, encode with `all-MiniLM-L6-v2`, L2-normalize each vector, save the matrix and ASIN row mapping, and record the model identifier and catalog SHA-256.

At query time, encode product terms plus unresolved subjective needs, normalize the query vector, compute cosine similarity with one matrix-vector dot product, and select the top 100 using `numpy.argpartition` followed by a stable sort.

Dense retrieval is enabled when at least one condition holds:

- unresolved subjective needs exist and cheap-generator agreement is below `0.25`;
- more than 35% of meaningful query terms are unexplained by top lexical candidates;
- the cheap union has fewer than 100 candidates.

## 11. RetrievalAssessment and plan calibration

The first three generators produce a cheap candidate union. `RetrievalAssessor` calculates target-blind query-performance features.

### 11.1 Generator agreement

For each pair of generators, compute Jaccard overlap over the first 50 results. Agreement is the mean pairwise value:

```text
agreement = mean(|A50 intersection B50| / |A50 union B50|)
```

### 11.2 Category entropy

Use the most specific normalized category for each candidate. For candidate proportions `p_c`:

```text
H = -sum(p_c * log(p_c))
normalized_entropy = H / log(number_of_nonempty_categories)
```

A high value means the result set is diffuse; it does not by itself mean the user is browsing.

### 11.3 Normalized Query Commitment

Convert field-FTS BM25 to a higher-is-better value, then calculate score dispersion over the top 20:

```text
NQC = std(top20_scores) / (abs(mean(top20_scores)) + 1e-9)
```

The observed range is normalized from development data and clipped to `[0, 1]`. This is a retrieval-confidence feature, not an official metric.

### 11.4 Coverage, margin, and stability

```text
coverage = active_constraints_with_any_candidate_evidence / active_constraints
margin   = (score_rank10 - score_rank11) / (abs(score_rank1) + 1e-9)
```

No active constraints yields coverage `1.0` with a `vacuous_coverage` reason code. Stability is the mean Jaccard overlap between nominal Top 10 and Top 10 produced by six deterministic `+/-10%` generator-weight perturbations.

### 11.5 Calibration rules

The planner starts from linearly blended endpoint weights:

```text
weight[g] = focus_score * focused_weight[g]
          + (1 - focus_score) * exploratory_weight[g]
```

Initial endpoints:

| Generator | Focused | Exploratory | Depth |
|---|---:|---:|---:|
| Title FTS | 1.0 | 0.7 | 100 |
| Field FTS | 0.8 | 1.0 | 200 |
| Attribute | 1.3 | 0.9 | 150 |
| Dense | 0.6 | 1.2 | 100 |

Post-retrieval diagnostics may adjust weights by at most 20%; they do not rewrite `NeedAssessment`:

- low agreement and high entropy: increase field/dense recall weights;
- strong constraint coverage: increase attribute weight;
- exact title agreement across generators: increase title weight;
- low stability: expand candidate depth before adding a model;
- optional-stage latency budget exhausted: retain the cheap plan.

## 12. Fusion, constraints, and ranking

### 12.1 Weighted Reciprocal Rank Fusion

For generator `g`, rank `r_g`, weight `w_g`, and constant `k=60`:

```text
RRF(product) = sum_g w_g / (k + r_g(product))
```

Products absent from a generator contribute zero. RRF is used because SQLite BM25, attribute scores, and cosine similarities are not numerically comparable.

### 12.2 Tri-state constraints

For every active constraint and product:

- `match`: product evidence verifies the requirement;
- `contradiction`: product evidence verifies incompatibility;
- `unknown`: relevant product evidence is missing or insufficient.

```text
required material=cotton, product material=cotton      -> match
required material=cotton, product material=polyester   -> contradiction
required material=cotton, no material evidence         -> unknown
budget <= 50, price=40                                  -> match
budget <= 50, price=70                                  -> contradiction
budget <= 50, price missing                             -> unknown
```

Unknown is never converted into contradiction.

### 12.3 Lightweight reranker

Normalize provisional signals within the candidate union to `[0, 1]`. Products with a verified hard contradiction are ordered below all non-contradictory products. Within each group:

```text
constraint_support = clip(
    0.30 * hard_match_ratio
  + 0.15 * soft_match_ratio
  + 0.10 * category_match
  - 0.35 * hard_contradiction_ratio
  - 0.10 * soft_contradiction_ratio,
  -1, 1
)

popularity = normalized(
    log1p(max(rating_number, 0)) * max(average_rating, 0) / 5
)

final_score =
    0.55 * normalized_rrf
  + 0.30 * normalized_constraint_support
  + 0.10 * raw_phrase_match
  + 0.05 * popularity
```

`normalized_constraint_support=(constraint_support+1)/2`. `raw_phrase_match` is the fraction of current raw-phrase IDF mass present in the product's searchable fields:

```text
raw_phrase_match = sum(IDF of matched raw terms) / max(sum(IDF of raw terms), 1e-9)
```

Profile preferences contribute only inside `soft_match_ratio`, are capped at `0.05` total final-score influence, and are disabled by an explicit conflict or `ANY` state. Final ties use `parent_asin` ascending.

### 12.4 Optional cross-encoder

The cross encoder receives at most 30 `(active need text, compact product text)` pairs. It returns one relevance score per supplied ASIN and cannot introduce new products.

It is enabled only when candidate recall at depth 30 is already strong, Top-10 stability is below `0.65` or the margin is below its tuned threshold, and its latency budget remains. Scores are min-max normalized and blended as:

```text
final = 0.70 * lightweight_score + 0.30 * semantic_score
```

Timeout, model error, or invalid output returns the lightweight order unchanged.

## 13. CandidateBelief and Top10Confidence

`CandidateBelief` is normalized ranking mass, not a claim of Bayesian calibration:

```text
q_i = exp((score_i - max_score) / temperature)
      / sum_j exp((score_j - max_score) / temperature)
```

Temperature starts at `0.20` and is tuned only on held-out development folds. If tuning is unstable, use rank-decay mass `q_i proportional to 1 / (20 + rank_i)`.

Top-10 confidence is target-blind:

```text
Top10Confidence = clip(
    0.25 * top10_belief_mass
  + 0.20 * generator_agreement
  + 0.20 * top10_stability
  + 0.15 * constraint_evidence_coverage
  + 0.10 * normalized_top10_margin
  + 0.10 * (1 - normalized_category_entropy),
  0, 1
)
```

This score is used for policy ordering and ablation. It must not be described as the probability that the hidden target is present unless separately calibrated and validated.

### 13.1 Recommendation Exposure

`SessionState` records every catalog product already returned during the current
intent. After ranking, `RecommendationExposureController` preserves score order
inside two partitions but places unseen candidates before previously shown ones.
This avoids repeating an unchanged Top 10 after implicit or explicit rejection
and expands useful catalog coverage across the ten-turn budget.

An Intent Override clears Recommendation Exposure before retrieval. Earlier
feedback was given under a different need, so a previously shown product may be
valid under the corrected request. Exposure is a temporary ordering control,
never a hard catalog exclusion.

## 14. QuestionPolicy

### 14.1 Action rule

The normal action on turns 1 through 9 is `ask-and-recommend`. Recommendations are scored before a customer reply, so a question does not remove the current hit opportunity. Turn 10 recommends and sets `ask_attribute=None` because no reply can be used.

The policy avoids attributes already marked `ANY`, exact repeated questions with no new evidence, attributes fully determined by a hard constraint, attributes with insufficient candidate evidence, and questions whose answers cannot change ordering.

### 14.2 Posterior-weighted partition value

For each eligible attribute `A`, partition the top 100 candidate mass by grounded value. Missing values form an `unknown` bucket. Let `q_i` be CandidateBelief and `P(v)` the mass of partition `v`.

```text
partition_gini(A) = 1 - sum_v P(v)^2
coverage(A)       = mass with a grounded non-unknown value
miss_factor       = 1 - Top10Confidence
remaining_factor  = max(0, (10 - turn) / 9)
```

Simulate the five highest-mass answers by applying each answer constraint and reranking the current candidate union. Define target-blind list utility over order `L` as:

```text
U(L) = sum(q_i / rank_L(i) for i in first_10(L))
simulated_gain(v) = max(0, U(rerank_with(A=v)) - U(current_order))
```

Then calculate:

```text
expected_rank_gain(A) = sum_v P(v) * simulated_gain(v)

QuestionValue(A) =
    miss_factor
  * partition_gini(A)
  * coverage(A)
  * expected_rank_gain(A)
  * remaining_factor
  - repeat_risk(A)
  - boundary_risk(A)
```

There is no generic MTTC turn penalty for an ask-and-recommend response. The relevant cost is receiving an uninformative answer instead of a better clarification.

### 14.3 Answerability and fallback

Candidate coverage is the primary answerability signal. The initial configurable tie-break order is:

```text
feature, material, color, style, size, use_case, budget, brand, category
```

This prior comes from released-data diagnostics and must be compared with candidate-only ordering. It never inspects a target at runtime.

If no specific attribute exceeds the question-value threshold but undisclosed need evidence remains likely, use:

```json
{
  "message": "What other requirement matters most for the item you want?",
  "ask_attribute": "other"
}
```

`other` is a fallback, not the only policy, because the public simulator treats it broadly and private paraphrasing may be less permissive.

### 14.4 Boundary handling

When the customer reports no preference:

1. emit `set_any(attribute)`;
2. remove active/profile values for that attribute from retrieval;
3. add the attribute to the no-repeat set;
4. continue returning ten recommendations;
5. select a different attribute on the next eligible turn.

## 15. ResponseGuard and failure handling

`ResponseGuard` is the last code executed before returning to the evaluator. It validates `message` and `ask_attribute`, removes invalid ASINs, deduplicates while preserving order, truncates to `min(top_k, 10)`, verifies non-negative token counts, and fills from deterministic field FTS if an upstream component fails.

Fallback ladder:

```text
optional semantic parser fails -> rules + catalog parser
dense generator fails          -> three cheap generators
cross encoder fails            -> lightweight reranker
one cheap generator fails      -> fuse remaining generators
all advanced retrieval fails   -> field-weighted FTS
empty query                    -> category fallback, then stable popularity fallback
```

No fallback may fabricate an ASIN.

## 16. Configuration, secrets, and artifacts

Runtime constants are frozen dataclasses in `shopping_copilot/config.py`. Each evaluator run records a canonical JSON representation and SHA-256 of the configuration.

Secrets are read only from environment variables inside optional provider adapters. `.env` remains ignored; only `.env.example` may be committed. The reliable path requires no secret.

The optional Responses API adapter is enabled only when
`SHOPPING_COPILOT_LLM_ENABLED` is true and both `OPENAI_API_KEY` and an explicit
`SHOPPING_COPILOT_LLM_MODEL` are set. There is deliberately no implicit model
choice. Without complete opt-in the factory returns `DisabledSemanticParser`.

Optional model calls require an explicit timeout, input-size limit, schema validation, token accounting, deterministic fallback, and provider/model identifier in the run report.

Generated indexes, vectors, traces, experiment reports, and research remain under ignored paths such as `artifacts/`, `experiments/`, and `analysis/`. Only source, tests, safe example configuration, and final product documentation are committed.

## 17. Observability

Each turn may write a local JSONL trace containing no hidden labels:

```json
{
  "session_id": "...",
  "turn": 2,
  "dialogue_acts": ["inform"],
  "slot_updates": ["material:add:cotton"],
  "focus_score": 0.71,
  "generator_counts": {"title": 100, "field": 200, "attribute": 150},
  "generator_agreement": 0.22,
  "top10_stability": 0.80,
  "question": {"attribute": "feature", "value": 0.19},
  "fallbacks": [],
  "latency_ms": 84.2
}
```

Tracing is optional and never required by the Agent.

## 18. Testing strategy

### 18.1 Unit tests

| Module | Required cases |
|---|---|
| normalization | Unicode, punctuation, units, empty values, idempotence |
| catalog loader | duplicate ASIN, malformed line, checksum, missing fields |
| rule parser | budgets, ranges, negation scope, OR/AND, correction, `ANY` |
| grounding | longest alias, ambiguity margin, category restriction, fuzzy rejection |
| reducer | add, exclude, replace, category override, profile suppression |
| FTS queries | escaping, empty query, deterministic rank, term limit |
| category popularity | shared category pool, popularity ordering, stable tie-break |
| attribute generator | match, contradiction, unknown, stable tie-break |
| RRF | missing generator, weights, deterministic fusion |
| retrieval assessment | agreement, entropy, NQC, margin, perturbation stability |
| reranker | contradiction ordering, missing-data neutrality, capped profile prior |
| recommendation exposure | unseen-first stability, repeat suppression, override reset |
| question policy | useful feature, repeated attribute, boundary, turn 10 |
| response guard | invalid/duplicate ASIN, Top-10 cap, invalid usage |

### 18.2 Interpreter scenario corpus

Maintain at least 100 hand-authored utterances covering product-led and need-led requests, subjective properties, alternatives, compound constraints, corrections, category overrides, negation scope, relative language, elliptical answers, no preference, profile conflicts, and paraphrases not copied from the evaluator.

Measure exact operation accuracy, slot precision/recall/F1, relation accuracy, and full-frame accuracy. This corpus is an engineering test, not an official competition metric.

### 18.3 Integration tests

- Buying: a hard requirement immediately affects ranking.
- Browsing: broad candidates accompany an informative clarification.
- Intent Override: the stale value is absent before next retrieval.
- Boundary: `ANY` suppresses the slot and prevents repetition.
- Rejection: previously shown products move behind unseen candidates.
- Intent Override: exposure resets because the active need changed.

The official `tests/test_evaluator.py` remains unchanged.

## 19. Evaluation and ablation protocol

Public labels are available only to offline evaluation code. Runtime modules must not import `evaluator` or read `data/public_set.jsonl`.

### 19.1 Metrics

Official outcomes are Hit Rate@10, MRR, MTTC, Efficiency, TechnicalScore, and scenario breakdowns. Engineering diagnostics are candidate recall at 10/50/100/300, marginal generator recall, parser accuracy, override correctness, question answer rate, generator agreement, stability, latency, memory, tokens, cost, and fallbacks.

### 19.2 Development split

Use target-ASIN-disjoint five-fold evaluation. Any learned or calibrated weight is fit on four folds and evaluated on the fifth. Report aggregate out-of-fold results before a final full-public-set demonstration.

### 19.3 Experiment order

| ID | Change | Decision |
|---|---|---|
| E0 | Original starter | Frozen baseline |
| E1 | CatalogStore with equivalent FTS | Must reproduce baseline |
| E2 | Stateful raw-message control | Diagnostic only; exposes simulator sensitivity |
| E3 | Typed interpreter and reducer | Keep if Override/Boundary correctness improves |
| E4 | Title + field + attribute generators | Keep sources with positive marginal recall |
| E5 | Uniform RRF | Multi-generator baseline |
| E6 | Constraint reranker | Keep if MRR improves without recall regression |
| E7 | Heuristic focus-score blending | Compare with uniform and hard switching |
| E8 | RetrievalAssessment calibration | Keep if held-out Top-10 improves |
| E9 | Candidate-belief question policy | Compare with fixed `feature`, fixed `other`, and recommend-only |
| E10 | Optional dense generator | Keep only for measured lexical recall gaps |
| E11 | Optional cross encoder/LLM | Keep only for held-out gain within budget |

Change one material variable per experiment and preserve run artifacts locally.

## 20. Performance budgets

Initial engineering budgets, subject to organizer limits:

```text
catalog startup                 <= 10 seconds on a laptop
reliable-path p95 respond       <= 500 ms
dense-path p95 respond          <= 1.5 seconds
optional model hard timeout     <= 4 seconds
peak memory without embeddings  <= 500 MiB
peak memory with embeddings     <= 1 GiB
contract failure rate           0
invalid ASIN rate               0
```

## 21. Five-person ownership

| Workstream | Driver | Reviewer | Owned paths | Acceptance handoff |
|---|---|---|---|---|
| Catalog and indexes | Member 1 | Member 2 | `catalog/` | Reproducible store, field audit, startup/memory report |
| Interpreter and state | Member 2 | Member 3 | `understanding/`, `dialog/reducer.py` | Parser corpus and four scenario transitions |
| Retrieval and fusion | Member 3 | Member 4 | `retrieval/` | Candidate recall and marginal-source report |
| Ranking and policy | Member 4 | Member 5 | `ranking/`, `dialog/policy.py` | Reranking and question-policy ablations |
| Integration and evaluation | Member 5 | Member 1 | orchestrator, adapter, guard, tests | Canonical command and protected evaluator report |

Only the integration owner changes `starter/agent.py` during final stabilization. Other workstreams integrate through typed interfaces and tests.

## 22. Implementation sequence

### Slice 1: reliable equivalent path

Implement `CatalogStore`, field-weighted FTS, `ResponseGuard`, and the orchestrator adapter. Reproduce E0 before adding features.

### Slice 2: interpreter and active state

Implement domain types, deterministic rules, catalog grounding, `SessionStore`, and `StateReducer`. Add all four scenario integration tests.

### Slice 3: multi-generator retrieval

Implement title FTS, attribute retrieval, uniform RRF, and candidate-recall diagnostics. Keep optional models disabled.

### Slice 4: assessment and reranking

Implement `NeedAssessor`, `RetrievalAssessor`, tri-state constraints, lightweight reranking, CandidateBelief, and Top10Confidence.

### Slice 5: clarification policy

Implement posterior-weighted partitioning, answerability checks, `other` fallback, and Boundary suppression. Compare fixed and adaptive policies.

### Slice 6: gated semantic stages

Add dense retrieval, cross encoder, or LLM parsing only when a retained experiment documents the precise failure being addressed.

## 23. Definition of done

- one documented command runs the Agent from a clean checkout;
- the official evaluator and protected inputs are unchanged;
- all outputs satisfy the machine-readable contract;
- every normal turn returns up to ten valid unique ASINs;
- corrections replace stale state before retrieval;
- already rejected recommendations are not repeated while unseen candidates exist;
- Intent Override resets earlier Recommendation Exposure;
- `ANY` suppresses its slot and future question;
- candidate generators have marginal-recall measurements;
- uniform, hard, and soft routing have controlled comparisons;
- adaptive clarification is compared with fixed `feature`, fixed `other`, and no-question controls;
- optional models have timeouts, token/cost reporting, and deterministic fallback;
- scenario metrics, latency, memory, and configuration hash are reported;
- no capability or metric is claimed without a reproducible run artifact.

## 24. References and deferred options

### Challenge sources

- [Competition specification](competition_specification.md)
- [Agent API contract](agent_api_contract.json)
- [Evaluation configuration](evaluation_config.json)
- [Published baseline](baseline_results.json)
- [Amazon Reviews 2023](https://amazon-reviews-2023.github.io/)

### Algorithm sources

- [Explicit Attribute Extraction in e-Commerce Search](https://aclanthology.org/2024.ecnlp-1.13/) — transformer NER and two-stage normalization.
- [Implicit Query Parsing for Product Search](https://www.amazon.science/publications/implicit-query-parsing-for-product-search) — explicit versus behavior-derived implicit attributes.
- [TripPy](https://aclanthology.org/2020.sigdial-1.4/) — copying evidence from message, system memory, and prior state.
- [Predicting Query Performance](https://doi.org/10.1145/564376.564429) — clarity and post-retrieval confidence.
- [Reciprocal Rank Fusion](https://doi.org/10.1145/1571941.1572114) — rank-level fusion of incomparable retrievers.
- [RouterRetriever](https://arxiv.org/abs/2409.02685) — lightweight routing over retrieval experts.
- [Learning to Ask Good Questions](https://aclanthology.org/P18-1255/) — expected value of clarification.
- [ProductAgent](https://arxiv.org/abs/2407.00942) — dynamic product retrieval and strategic clarification.
- [Towards Translating Objective Product Attributes Into Customer Language](https://aclanthology.org/2024.naacl-industry.20/) — subjective needs versus objective catalog attributes.

### Deferred options

| Option | Adopt only when | Evidence required |
|---|---|---|
| Learned logistic route calibration | Heuristic focus score helps but is inconsistent | Out-of-fold utility gain and calibration report |
| Content-derived product graph | Alias/co-occurrence expansion is a recall bottleneck | Marginal recall gain without candidate diffusion |
| Dense embeddings | Vocabulary mismatch misses targets | Candidate recall gain at 100/300 within memory budget |
| Cross encoder | Candidate recall is high but MRR is low | Held-out MRR gain within latency budget |
| LLM structured parser | Rule/catalog parser leaves important clauses unresolved | Frame accuracy and end-to-end gain with schema-valid output |
| Maximal marginal relevance | Near-duplicate exploratory results are measured | Browsing gain without overall Hit Rate loss |

Do not implement collaborative filtering, purchase-sequence models, social signals, multimodal retrieval, or review-based inference: the Agent does not receive the required source data.
