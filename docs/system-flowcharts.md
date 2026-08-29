# Shopping Copilot System Flowcharts

This document is the visual, implementation-level guide to the Shopping Copilot.
It describes the system that exists on the current branch. Optional or deferred
paths are labelled so they are not mistaken for the reliable default path.

## Component map

| Component | Responsibility | Primary implementation |
|---|---|---|
| Official adapter | Expose the required `Agent` contract | [`starter/agent.py`](../starter/agent.py) |
| Orchestrator | Coordinate one complete response | [`shopping_copilot/agent.py`](../shopping_copilot/agent.py) |
| Catalog | Validate records and build read-only indexes | [`shopping_copilot/catalog/`](../shopping_copilot/catalog/) |
| Understanding | Convert a message into immutable proposed updates | [`shopping_copilot/understanding/`](../shopping_copilot/understanding/) |
| Dialog state | Apply corrections and own mutable session state | [`shopping_copilot/dialog/`](../shopping_copilot/dialog/) |
| Retrieval | Plan, generate, fuse, and assess candidates | [`shopping_copilot/retrieval/`](../shopping_copilot/retrieval/) |
| Ranking | Rerank, apply novelty, budget, and explanations | [`shopping_copilot/ranking/`](../shopping_copilot/ranking/) |
| Response guard | Enforce allowed attributes and catalog IDs | [`shopping_copilot/contracts.py`](../shopping_copilot/contracts.py) |
| Evaluation | Simulate sessions and calculate official metrics | [`evaluator/local_evaluator.py`](../evaluator/local_evaluator.py) |

## 1. Entire system

```mermaid
flowchart LR
    Catalog[(Frozen 50k-product<br/>catalog JSONL)] --> CatalogStore[CatalogStore<br/>records + SQLite FTS5]
    PublicSet[(Public sessions)] --> Evaluator[Local evaluator]

    Evaluator -->|reset with profile| SessionStore[SessionStore]
    Evaluator -->|respond with message| Agent[ShoppingAgent]
    SessionStore --> Agent

    Agent --> Interpreter[MessageInterpreter]
    Interpreter --> Reducer[StateReducer]
    Reducer --> Active[Active State]

    Active --> Planner[RetrievalPlanner]
    Planner --> Generators[Five lexical generators]
    CatalogStore --> Generators
    Generators --> Fusion[Weighted RRF]
    Fusion --> Assessment[RetrievalAssessment]
    Fusion --> Reranker[LightweightReranker]
    Active --> Reranker

    Assessment -. uncertain language .-> Semantic[Optional semantic translator]
    Semantic -. grounded additions only .-> Reducer
    Reducer -. state changed .-> Planner

    Reranker --> Exposure[Unseen-first exposure]
    Exposure --> Question[QuestionPolicy]
    Assessment --> Question
    Question --> Guard[ResponseGuard]
    Exposure --> Guard
    Guard -->|message + ask_attribute<br/>+ Top 10 ASINs + usage| Evaluator

    Agent -. component exception .-> Fallback[Field-weighted FTS fallback]
    CatalogStore --> Fallback
    Fallback --> Guard
```

The default path is offline and deterministic. The LLM is not a recommender: it
is an optional translator used between the first retrieval and final decision.
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
    H --> I[(FTS5 vocabulary<br/>document frequencies)]
    F4 --> J[(Popularity ordering)]

    G --> K[Exact ID validation and metadata lookup]
    H --> L[BM25 candidate search]
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
    A->>I: parse_deterministic(message, last ask)
    I-->>A: IntentFrame
    A->>R: apply(state, frame)
    A->>Q: plan, generate, fuse, assess, rerank
    Q-->>A: RetrievalAssessment + ranked union

    opt semantics enabled and escalation approved
        A->>L: message + compact active context
        L-->>A: structured semantic hints or safe no-op
        A->>R: apply_semantic without advancing turn
        opt accepted evidence changed state
            A->>Q: rerun retrieval once
            Q-->>A: revised assessment + ranking
        end
    end

    A->>A: unseen-first partition
    A->>P: choose(state, top candidates, assessment, turn)
    P-->>A: QuestionDecision
    A->>G: message + attribute + ranked IDs + usage
    G-->>E: contract-safe response

    Note over A,G: Any component exception uses field-weighted FTS,<br/>then passes through the same guard.
```

The deterministic frame is applied before the first retrieval. A semantic frame
can add only locally grounded evidence and does not increment `turn_count`. At
most one semantic reretrieval occurs in a response.

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

    I --> J{Current words identify<br/>an attribute?}
    J -->|yes| K[Explicit attribute wins]
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
    A[IntentFrame] --> B{Override?}
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

    G --> H1
    G --> H2
    G --> H3
    G --> H4
    G --> H5

    H1 --> I[Five ranked lists<br/>up to 160 each]
    H2 --> I
    H3 --> I
    H4 --> I
    H5 --> I
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

All cheap routes still run. Focus changes their influence rather than selecting
one brittle route. Field-specific BM25 weights make the same catalog index act
as several candidate generators.

## 8. Fusion, assessment, and reranking

```mermaid
flowchart TD
    A[Five ranked lists] --> B[CandidateEvidence per ASIN]
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

## 9. Optional semantic interpretation

```mermaid
flowchart TD
    A[Deterministic frame and first ranking] --> B{Semantic provider<br/>fully configured?}
    B -->|no| Z[Keep deterministic result]
    B -->|yes| C{At least 6 terms?}
    C -->|no| Z
    C -->|yes| D{Missing category?}
    D -->|yes| H[Approve call]
    D -->|no| E{Exact multi-term preference<br/>in top product?}
    E -->|yes| Z
    E -->|no| F{Ambiguous category and<br/>stability below 0.40?}
    F -->|yes| H
    F -->|no| G{Difficult or implicit language and<br/>stability below 0.12?}
    G -->|no| Z
    G -->|yes| H

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
    P -->|yes| Q[Apply soft feature, style, or use_case<br/>and anchored rewrites]
    Q --> R[Reretrieve exactly once]
```

Semantic output is untrusted until locally grounded. The grounder rejects ASINs,
negated rewrites, unanchored text, overlong values, unsupported evidence spans,
low-confidence hypotheses, and semantic attributes already determined by the
rules. Structured hypotheses are limited to `feature`, `style`, and `use_case`.

The process call cap defaults to 16, successful responses use a 256-entry LRU
cache, and failures are not retried. The LLM path is off by default because live
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
    G --> J[Answerability prior]
    H --> K[Question value]
    I --> K
    J --> K
    C --> K

    K --> L{Best value at least 0.08<br/>or negative feedback?}
    L -->|yes| M[Ask best attribute<br/>and recommend]
    L -->|no| N{Broad other unused and<br/>confidence below 0.92?}
    N -->|yes| O[Ask broad other<br/>and recommend]
    N -->|no| Z
```

Implemented confidence and value are target-blind heuristics:

```text
confidence = 0.55 × top10_stability
           + 0.45 × min(1, preference_phrase_count / 3)

question_value(attribute) = coverage
                          × diversity
                          × answerability_prior
                          × (1 - confidence)
```

Already asked or explicitly declined attributes are unavailable. The one-time
`other` recovery avoids a field-by-field interview and lets the customer name a
priority the catalog taxonomy did not anticipate. Recommendations are still
returned while a question is asked.

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

## 13. Failure-containment view

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
4. Treat the semantic diagram as an optional second pass, not the main pipeline.
5. Use clarification, guard, and evaluator diagrams to verify changes against the
   ten-turn and exact-ASIN objective.

For formulas, tuning rationale, deferred alternatives, and ownership, continue
with [`architecture.md`](architecture.md). For measured experiments and rejected
approaches, see [`findings.md`](findings.md).
