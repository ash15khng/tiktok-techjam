# Shopping Copilot System Flowcharts

This document is the visual, implementation-level guide to the Shopping Copilot.
It describes the system that exists on the current branch. The implemented
optional semantic path is labelled so it is not mistaken for the offline default.

## Component map

| Component | Responsibility | Primary implementation |
|---|---|---|
| Official adapter | Expose the required `Agent` contract | [`submission/agent.py`](../submission/agent.py) |
| Evaluator shim | Preserve the supplied evaluator import | [`starter/agent.py`](../starter/agent.py) |
| Orchestrator | Coordinate one complete response | [`submission/src/agent.py`](../submission/src/agent.py) |
| Catalog | Validate records and build read-only indexes | [`submission/src/catalog/`](../submission/src/catalog/) |
| Understanding | Convert a message into immutable proposed updates | [`submission/src/understanding/`](../submission/src/understanding/) |
| Dialog state | Apply corrections and own mutable session state | [`submission/src/dialog/`](../submission/src/dialog/) |
| Retrieval | Plan, generate, fuse, and assess candidates | [`submission/src/retrieval/`](../submission/src/retrieval/) |
| Ranking | Rerank, apply novelty, budget, and explanations | [`submission/src/ranking/`](../submission/src/ranking/) |
| Response guard | Enforce allowed attributes and catalog IDs | [`submission/src/contracts.py`](../submission/src/contracts.py) |
| Evaluation | Simulate sessions and calculate official metrics | [`evaluator/local_evaluator.py`](../evaluator/local_evaluator.py) |

## 1. Entire system

```mermaid
flowchart LR
    Catalog[(Frozen 50k-product<br/>catalog JSONL)] --> CatalogStore[CatalogStore<br/>records + SQLite FTS5]
    CatalogStore --> Registry[CatalogAttributeRegistry<br/>values + priors + price quantiles]
    CatalogStore --> Structure[CatalogStructureIndex<br/>compact category buckets]
    PublicSet[(Public sessions)] --> Evaluator[Local evaluator]

    Evaluator -->|reset with profile| SessionStore[SessionStore]
    Evaluator -->|respond with message| Agent[ShoppingAgent]
    SessionStore --> Agent

    Agent --> Interpreter[MessageInterpreter]
    Interpreter --> Preflight{Semantic preflight}
    Preflight --> Reducer[StateReducer]
    Preflight -. compound or unresolved .-> Semantic[Optional semantic interpreter]
    Semantic -. grounded operations .-> Reducer
    Reducer --> Active[Active State]

    Active --> Planner[RetrievalPlanner]
    Planner --> Generators[Five lexical generators]
    Planner --> StructuralGate{Positive preference<br/>available?}
    StructuralGate -->|yes| Structure
    CatalogStore --> Generators
    Registry --> Interpreter
    Generators --> Fusion[Weighted RRF]
    Structure --> Fusion
    Fusion --> Assessment[RetrievalAssessment]
    Fusion --> Reranker[LightweightReranker]
    Active --> Reranker

    Assessment -. uncertain and preflight skipped .-> Semantic
    Reducer -. state changed .-> Planner

    Reranker --> Exposure[Unseen-first exposure]
    Exposure --> Question[QuestionPolicy]
    Registry --> Question
    Assessment --> Question
    Question --> Guard[ResponseGuard]
    Exposure --> Guard
    Guard -->|message + ask_attribute<br/>+ Top 10 ASINs + usage| Evaluator

    Agent -. component exception .-> Fallback[Field-weighted FTS fallback]
    CatalogStore --> Fallback
    Fallback --> Guard
```

The default path is offline and deterministic. The LLM is a structured state
interpreter and query translator, not a source of product IDs. It runs either
before state mutation for compound/unresolved language or after first retrieval
for instability, never both in one turn.
Every successful path ends at `ResponseGuard`, so only valid frozen-catalog IDs
and contract-safe fields leave the agent.

## 2. Catalog ingestion and indexing

```mermaid
flowchart TD
    A[data/catalog.jsonl] --> B[Read one JSON object per line]
    B --> C{parent_asin present<br/>and unique?}
    C -->|no| D[Stop with validation error]
    C -->|yes| E[Flatten searchable fields]

    E --> F[ProductRecord]
    F --> F1[parent_asin]
    F --> F2[title and categories]
    F --> F3[features details description store]
    F --> F4[price rating rating_number]

    F1 --> G[(products dictionary)]
    F2 --> H[(SQLite FTS5 products_fts)]
    F3 --> H
    F2 --> P[CatalogStructureIndex]
    P --> P1[Two most-specific<br/>safe category segments]
    P1 --> P2[One bucket membership<br/>per product ID]
    H --> I[(FTS5 vocabulary<br/>document frequencies)]
    F4 --> J[(Popularity ordering)]
    F3 --> O[CatalogAttributeRegistry]
    F2 --> O
    F4 --> O
    O --> O1[Catalog-native value phrases]
    O --> O2[Metadata answerability priors]
    O --> O3[Log-quantile price bands]

    G --> K[Exact ID validation and metadata lookup]
    H --> L[BM25 candidate search]
    H --> Q[Per-agent 256-entry<br/>immutable query cache]
    P2 --> R[Exact/contained/suffix<br/>category resolution]
    R --> S[Phrase and token coverage<br/>plus popularity route]
    G --> T[Per-agent 4096-entry<br/>product token-view cache]
    I --> M[Rare-term selection and IDF]
    J --> N[Category-popular route and safe fallback]
```

Technical behavior:

- Source records are never modified. Derived lookup views live in memory.
- Missing text becomes an empty string or tuple. Missing numeric values become
  `None`, except missing `rating_number`, which contributes zero popularity.
- Unicode text is normalized with NFKC and case folding for lookup, while raw
  catalog phrases remain available as searchable evidence.
- The FTS table indexes title, categories, features, details, store, and
  description separately. BM25 field weights therefore vary by retrieval route.
- Structural buckets are derived only from catalog categories and never replace
  the FTS index. Missing or unresolved structure returns no additional route.
- Query and token-view caches are bounded per `CatalogStore`, so a long-running
  process neither shares counters nor retains old agent instances globally.
- Duplicate or empty `parent_asin` values fail during startup because exact ID
  equality is the scoring boundary.

## 3. Runtime data structures

```mermaid
classDiagram
    class SessionState {
        session_id
        customer_profile
        active
        last_ask_attribute
        last_recommendations
        recommendation_exposure
        turn_count
        last_feedback_negative
        clarification_outcomes
    }
    class ActiveState {
        category_phrases
        preference_phrases
        exclusions
        slot_values
        suppressed_attributes
        asked_attributes
        query_terms()
        context_snapshot()
    }
    class IntentFrame {
        raw_message
        dialogue_acts
        slot_updates
        category_phrases
        preference_phrases
        exclusions
        override
        negative_feedback
        query_rewrites
    }
    class SlotUpdate {
        attribute
        operation
        value
        raw_span
        source
    }
    class RetrievalPlan {
        focus_score
        generator_weights
        generator_limit
    }
    class CandidateEvidence {
        parent_asin
        generator_ranks
        raw_scores
        rrf_score
        final_score
    }
    class RetrievalAssessment {
        candidate_count
        generator_agreement
        top10_stability
    }
    class QuestionDecision {
        ask_attribute
        message
        question_value
        reason
    }

    SessionState *-- ActiveState
    IntentFrame *-- SlotUpdate
    IntentFrame --> ActiveState : reducer applies
    ActiveState --> RetrievalPlan : planner reads
    RetrievalPlan --> CandidateEvidence : generators produce
    CandidateEvidence --> RetrievalAssessment : fusion assesses
    CandidateEvidence --> QuestionDecision : candidate partitions
    RetrievalAssessment --> QuestionDecision : confidence input
```

The key boundary is between `IntentFrame` and `ActiveState`. The interpreter
proposes immutable events; only `StateReducer` may mutate active session state.
This prevents parsing, retrieval, and ranking from silently disagreeing about
which preferences remain current.

## 4. One `respond` call

```mermaid
sequenceDiagram
    participant E as Evaluator
    participant A as ShoppingAgent
    participant S as SessionStore
    participant I as MessageInterpreter
    participant R as StateReducer
    participant Q as Retrieval pipeline
    participant L as Optional semantic API
    participant P as QuestionPolicy
    participant G as ResponseGuard

    E->>A: respond(session_id, message, turn, top_k)
    A->>S: get(session_id)
    S-->>A: SessionState
    alt exact duplicate or late turn
        A-->>E: stored response snapshot; no state replay
    else new turn
    A->>I: parse_deterministic(message, last ask)
    I-->>A: IntentFrame
    opt semantic preflight approved
        A->>L: message + structured prior Active State
        L-->>A: grounded field operations + standalone rewrites or safe no-op
    end
    A->>R: apply(state, frame)
    A->>Q: plan, generate, fuse, assess, rerank
    Q-->>A: RetrievalAssessment + ranked union

    opt preflight skipped and retrieval-aware escalation approved
        A->>L: message + compact active context
        L-->>A: structured semantic hints or safe no-op
        A->>R: apply_semantic without advancing turn
        opt accepted evidence changed state
            A->>Q: rerun retrieval once
            Q-->>A: revised assessment + ranking
        end
    end

    A->>A: unseen-first partition
    A->>A: freeze first 10 IDs and apply bounded ordering
    A->>P: choose(state, top candidates, assessment, turn)
    P-->>A: QuestionDecision
    A->>G: message + attribute + ranked IDs + usage
    G-->>E: contract-safe response
    end

    Note over A,G: Any component exception prefers the last good list,<br/>then field FTS, then the same guard.
```

Compound-turn semantics enriches the frame before its single state reduction. If
that gate skips, a post-retrieval semantic frame can apply locally grounded
evidence without incrementing `turn_count`, followed by at most one reretrieval.
The two paths are mutually exclusive.

## 5. Message interpretation

```mermaid
flowchart TD
    A[Raw customer message] --> B[Normalize for matching<br/>preserve original text]
    B --> C[Detect dialogue acts]
    C --> C1[override or correction]
    C --> C2[negative feedback]
    C --> C3[no preference or decline]

    B --> D{Recognized message shape}
    D -->|looking for or need| E[Extract category and remaining tail]
    D -->|key requirement payload| F[Preserve semicolon-delimited evidence]
    D -->|ordinary customer clause| G[Split only high-confidence comma clauses]

    E --> H[Separate positive phrases and exclusions]
    F --> H
    G --> H
    H --> I[Resolve each phrase]
    R[(Catalog-derived values)] --> I

    I --> J{Current words identify<br/>an attribute?}
    J -->|yes| K[Explicit cue or catalog value wins]
    J -->|no, short reply| L[Use immediately preceding ask_attribute]
    J -->|no usable context| M[Conservative feature fallback]
    I --> N{Bare decline?}
    N -->|yes| O[set_any for last asked attribute]

    K --> P[SlotUpdate with provenance]
    L --> P
    M --> P
    O --> P
    P --> Q[Immutable IntentFrame]
```

Parsing precedence is deliberate:

1. explicit evidence in the current message;
2. the immediately preceding structured question for bounded short replies;
3. a searchable fallback phrase when no safer attribute is available.

Bare affirmations such as `yes` are not preference evidence. Bare declines such
as `no` become `set_any` only when the previous `ask_attribute` supplies a safe
meaning. Each update records `explicit`, `contextual`, `fallback`, or `semantic`
provenance.

## 6. State reduction and intent override

```mermaid
flowchart TD
    A[IntentFrame] --> A1[Record prior question as<br/>answered, declined, or redirected]
    A1 --> B{Override?}
    B -->|no| G[Apply updates]
    B -->|yes| C[Clear recommendation exposure]
    C --> D{New category supplied?}
    D -->|yes| E[Clear old preferences,<br/>exclusions, and slot values]
    D -->|no| F[Remove oldest stale preference;<br/>keep later confirmed evidence]
    E --> G
    F --> G

    G --> H{Update operation}
    H -->|set or add| I[Add unique value]
    H -->|replace| J[Replace attribute values]
    H -->|exclude| K[Keep in exclusion evidence]
    H -->|set_any| L[Remove values and suppress attribute]

    I --> M[Update SessionState]
    J --> M
    K --> M
    L --> M
    M --> N[Increment turn once]

    O[Grounded semantic frame] -.-> P[apply_semantic]
    P --> Q[Add only semantic updates]
    Q --> R[Do not increment turn]
```

Intent override is replacement, not accumulation. A category change invalidates
all earlier product-specific evidence. A preference-only correction removes the
oldest stale preference but retains evidence confirmed later in the session.
Exposure is reset because a product rejected under the previous intent may be
valid under the corrected one.

## 7. Retrieval planning and candidate generation

```mermaid
flowchart TD
    A[Active State] --> B[Category terms]
    A --> C[Preference terms]
    B --> D[Combined query terms<br/>maximum 40]
    C --> D
    C --> E[Rarest preference terms<br/>maximum 12]

    A --> F[Focus score]
    F --> G[Blend focused and exploratory<br/>generator weights]

    D --> H1[Field route<br/>all indexed fields]
    B --> H2[Title route]
    B --> H3[Category relevance route<br/>pool up to 800]
    H3 --> H4[Category popularity route]
    E --> H5[Constraint route<br/>AND then OR fallback]
    A --> S{At least one positive<br/>preference phrase?}
    S -->|yes| H6[Structural route<br/>safe category bucket]
    S -->|no| I

    G --> H1
    G --> H2
    G --> H3
    G --> H4
    G --> H5
    G --> H6

    H1 --> I[Five or six ranked lists<br/>up to 160 each]
    H2 --> I
    H3 --> I
    H4 --> I
    H5 --> I
    H6 --> I
    I --> J[Weighted Reciprocal Rank Fusion]
    J --> K[Bounded candidate union]
```

The focus score is a soft controller, not a prediction of the evaluator's
Buying label:

```text
z = -1.1 + 0.95 × preference_or_exclusion_count + 0.35 × has_category
focus_score = sigmoid(z)
route_weight = focus_score × focused_weight
             + (1 - focus_score) × exploratory_weight
```

All five FTS routes still run. Focus changes their influence rather than
selecting one brittle route. Field-specific BM25 weights make the same catalog
index act as several candidate generators. The structural route is additive and
joins only after a preference phrase makes its family ordering discriminative;
failure to resolve a category leaves the FTS ensemble unchanged.

## 8. Fusion, assessment, and reranking

```mermaid
flowchart TD
    A[Five or six ranked lists] --> B[CandidateEvidence per ASIN]
    B --> C[Record generator ranks<br/>and raw BM25 scores]
    C --> D[Weighted RRF score]

    D --> E[RetrievalAssessment]
    E --> E1[Candidate count]
    E --> E2[Mean pairwise Top-20 Jaccard]
    E2 --> E3[Top-10 stability<br/>min 1, agreement x 2.5]

    D --> F[Full bounded union reranker]
    F --> F1[Normalized RRF support]
    F --> F2[IDF-weighted term coverage]
    F --> F3[Exact preference phrase ratio]
    F --> F4[Capped popularity]
    F --> F5[Capped profile overlap]
    F --> F6[Budget match, violation, or unknown]
    F --> F7[Explicit exclusion contradiction]

    F1 --> G[Final score]
    F2 --> G
    F3 --> G
    F4 --> G
    F5 --> G
    F6 --> G
    F7 --> G
    G --> H[Sort by final score,<br/>RRF score, then ASIN]
    H --> I[Stable unseen-first partition]
    I --> J[Freeze first 10 IDs]
    J --> K{Intent corrected?}
    K -->|yes| L[Preserve relevance order]
    K -->|no| M[Bounded log-popularity tie-break]
```

For candidate `p`, the implemented score is:

```text
score(p) = 0.52 × normalized_RRF
         + 0.36 × IDF_coverage
         + 0.12 × exact_phrase_ratio
         + profile_score, capped at 0.03
         + 0.18 × capped_popularity
         + 0.12 × budget_signal
         - 0.70 × exclusion_contradiction
```

Weighted RRF uses `weight / (60 + rank)` for each generator. Missing price has a
budget signal of zero rather than being treated as over budget. The profile can
break close ties but cannot overpower current-session evidence. `unseen_first`
does not alter scores; it preserves order inside the unseen and already-shown
partitions.

The final orderer cannot change membership. Its retained `0.05` popularity
weight improves public working-fold MRR while exact intent corrections disable
that weak prior. Phrase-rarity and profile-ordering weights are currently zero.

## 9. Optional semantic interpretation

```mermaid
flowchart TD
    A[Deterministic frame + prior state] --> B{Semantic provider<br/>fully configured?}
    B -->|no| Z[Keep deterministic result]
    B -->|yes| C{At least 6 terms?}
    C -->|no| Z
    C -->|yes| D{Compound change, missing category,<br/>or difficult fallback?}
    D -->|yes: preflight| H[Approve one call before state mutation]
    D -->|no| E[Run deterministic retrieval]
    E --> F{Exact top evidence?}
    F -->|yes| Z
    F -->|no| G{Ambiguous/difficult language<br/>and low stability?}
    G -->|no| Z
    G -->|yes: postflight| H

    H --> I{Successful cache hit?}
    I -->|yes| M[Return cached hints<br/>with zero new tokens]
    I -->|no| J{Run call cap available?}
    J -->|no| Z
    J -->|yes| K[Responses-compatible request<br/>6 s timeout, max 220 output tokens]
    K --> L{Completed strict function call?}
    L -->|no, timeout, or invalid| Z
    L -->|yes| M

    M --> N[Validate output shape and limits]
    N --> O[Ground against current message and context]
    O --> P{Accepted evidence changed state?}
    P -->|no| Z
    P -->|yes| Q[Apply grounded add/replace/exclude/set_any<br/>and standalone rewrites]
    Q --> R[Retrieve once, or reretrieve once after postflight]
```

Semantic output is untrusted until locally grounded. The grounder rejects ASINs,
vague/negated rewrites, invalid field operations, hard values missing from their
exact evidence spans, overlong values, low confidence, and conflicts with
explicit deterministic evidence. All competition fields except `other` are
permitted in semantic state operations.

The process call cap defaults to 16, each session permits at most two attempts,
successful responses use a 256-entry LRU cache, and failures are not retried. The LLM path is off by default because live
tests have not yet improved a measured ranking. The forced function-tool request
has mocked coverage but still requires one capped live compatibility test.

## 10. Clarification and action selection

```mermaid
flowchart TD
    A[Ranked candidates + assessment + state] --> B{Turn 10?}
    B -->|yes| Z[Recommend only]
    B -->|no| C[Compute confidence]
    C --> D{Previous specific question<br/>was declined?}
    D -->|yes and other unused| E[Ask one broad other question]
    D -->|no| F[Inspect top 50 candidates]

    F --> G[For each available attribute,<br/>group candidate values]
    G --> H[Coverage]
    G --> I[Gini-style diversity]
    G --> J[Catalog answerability prior]
    A --> J1[Session clarification outcomes]
    J --> J2[Beta-style posterior]
    J1 --> J2
    H --> K[Question value]
    I --> K
    J2 --> K
    C --> K

    K --> L{Best value at least 0.08<br/>or negative feedback?}
    L -->|yes| M[Ask best attribute<br/>and recommend]
    L -->|no| N{Broad other unused and<br/>confidence below 0.92?}
    N -->|yes| O[Ask broad other<br/>and recommend]
    N -->|no| Z
    E --> P[QuestionDecision]
    M --> P
    O --> P
    Z --> P
```

Implemented confidence and value are target-blind heuristics:

```text
confidence = 0.55 × top10_stability
           + 0.45 × min(1, preference_phrase_count / 3)

question_value(attribute) = coverage
                          × diversity
                          × session_answerability_posterior
                          × (1 - confidence)
```

Already asked or explicitly declined attributes are unavailable. The one-time
`other` recovery avoids a field-by-field interview and lets the customer name a
priority the catalog taxonomy did not anticipate. Recommendations are still
returned while a question is asked. Baselines come from frozen-catalog coverage
and repeated-value support; answers and declines update only the current
session, and `reset()` clears those observations.

## 11. Explanation, output guard, and fallback

```mermaid
flowchart TD
    A[Ranked CandidateEvidence] --> B[Unseen-first ordered ASINs]
    C[Current category and last two preferences] --> D[Short evidence-based message]
    E[QuestionDecision] --> F[message + ask_attribute]
    D --> F
    B --> G[ResponseGuard]
    F --> G
    H[Prompt and completion tokens] --> G

    G --> I[Keep allowed ask_attribute or null]
    G --> J[Keep only frozen-catalog IDs]
    J --> K[Remove duplicates in rank order]
    K --> L[Cap at min top_k, 10]
    M[Global catalog popularity] --> N[Fill missing slots if needed]
    N --> L
    G --> O[Clamp token counts to non-negative integers]
    I --> P[Contract-safe response]
    L --> P
    O --> P

    Q[Any orchestrator exception] --> R[Tokenize current message]
    R --> S[Field-weighted FTS search]
    S --> G
```

The guard is the trust boundary for all upstream components. It accepts an
ordered iterable rather than trusting a ranker-specific object, filters against
`CatalogStore.valid_ids`, and fills short lists with deterministic popular
catalog products. Even the exception fallback passes through the same guard.

## 12. Evaluation loop

```mermaid
flowchart TD
    A[Load public sessions and catalog IDs] --> B[Create isolated session ID]
    B --> C[Agent.reset with anonymized profile]
    C --> D[Simulator sends opening message]
    D --> E[Agent.respond]
    E --> F[Normalize first 10 valid unique ASINs]
    F --> G{Target present and<br/>override already revealed?}
    G -->|yes| H[Record first-hit turn and rank]
    G -->|no, turns remain| I[Simulator reveals requested attribute,<br/>Boundary decline, or Intent Override]
    I --> E
    G -->|no, after turn 10| J[Record miss as turn 11]

    H --> K[Aggregate metrics]
    J --> K
    K --> K1[Hit Rate at 10]
    K --> K2[MRR]
    K --> K3[MTTC]
    K --> K4[Efficiency]
    K --> K5[TechnicalScore]
    K --> K6[Scenario breakdown and token usage]
```

The evaluator owns target labels and simulator behavior; runtime code does not
import them. Only exact `parent_asin` equality is a hit. Intent Override sessions
cannot score before the corrected intent is revealed. A miss contributes zero
to MRR and turn 11 to MTTC.

```text
Efficiency = clip((11 - MTTC) / 10, 0, 1)
TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
```

## 13. Development split and release gate

```mermaid
flowchart TD
    A[200 labeled public sessions] --> B[Group target ASINs and<br/>exact normalized-title families]
    B --> C[Scenario-stratified deterministic assignment]
    C --> D[40-session sealed holdout]
    C --> E[160 working sessions]
    E --> E1[Fold 0: 40]
    E --> E2[Fold 1: 40]
    E --> E3[Fold 2: 40]
    E --> E4[Fold 3: 40]

    E1 --> F[Repeated development ablations]
    E2 --> F
    E3 --> F
    E4 --> F
    F --> G{Code, score, scenarios,<br/>hard language, latency pass?}
    G -->|no| H[Revise or reject]
    G -->|yes and configuration frozen| I[Open sealed holdout once]
    D --> I
    I --> J[One complete-public compatibility replay]
    J --> K[Submit for 800-session private evaluation]
```

Every 40-session partition contains 16 Buying, 16 Browsing, 6 Intent Override,
and 2 Boundary sessions. Neither a sample nor a target/title family crosses a
partition. Catalog-only statistics may use all 50,000 products because the
catalog is legal runtime input; labels and evaluator-generated intent remain
offline only. See [evaluation-methodology.md](evaluation-methodology.md).

## 14. Failure-containment view

```mermaid
flowchart LR
    A[Catalog validation failure] --> A1[Fail fast at startup]
    B[No lexical candidates] --> B1[Popular catalog fill]
    C[Interpreter, planner, or ranker exception] --> C1[Field FTS fallback]
    D[LLM disabled] --> D1[Normal deterministic path]
    E[LLM timeout or invalid output] --> E1[Semantic no-op]
    F[Unsafe semantic hint] --> F1[Local grounding rejects it]
    G[Invalid attribute or ASIN] --> G1[ResponseGuard removes it]
    H[Customer declines a field] --> H1[Suppress field and use one broad recovery]
    I[Customer changes intent] --> I1[Remove stale state and reset exposure]
```

The design preserves one complete offline route and contains optional failures at
their boundary. This is important for both competition reliability and a real
shopping experience: a slow model or incomplete catalog field should degrade
the sophistication of the answer, not invalidate the response.

## Reading order for implementation work

1. Start with the entire-system diagram and the `respond` sequence.
2. Read message interpretation and state reduction together; their boundary is
   the most important correctness contract.
3. Read retrieval planning before reranking so route weights and final feature
   weights are not confused.
4. Treat semantics as an optional preflight or post-retrieval fallback, not the
   main pipeline.
5. Use clarification, guard, and evaluator diagrams to verify changes against the
   ten-turn and exact-ASIN objective.

For formulas, tuning rationale, and ownership, continue with
[`architecture.md`](architecture.md). For measured experiments and rejected
approaches, see [`findings.md`](findings.md); remaining work lives in
[`../TODO.md`](../TODO.md).
