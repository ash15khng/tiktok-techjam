# Component 2 Walkthrough: Message Understanding & Dialog State Tracking

This document outlines the architecture, implementation, and testing guide for **Component 2: Message Understanding & Dialog State Tracking** (`shopping_copilot/understanding/` and `shopping_copilot/dialog/`).

---

## 1. Subsystem Architecture & Data Flow

Component 2 translates raw natural language shopper messages into structured slot updates, quantitative customer readiness assessments, and deterministically tracked dialogue state across multi-turn sessions.

```
+-------------------------------------------------------------------------------+
|                                USER MESSAGE                                   |
+-------------------------------------------------------------------------------+
                                       |
                                       v
                     +-----------------------------------+
                     |        MessageInterpreter         |
                     |  (10-Step Cascade Coordinator)    |
                     +-----------------------------------+
                       /               |               \
                      /                |                \
                     v                 v                 v
          +-----------------+ +-----------------+ +--------------------+
          |   Regex Rules   | |   CatalogTrie   | | CatalogEntityLinker|
          | (Budget, Sizes, | | (Longest-Match  | | (Conservative Fuzzy|
          |   Acts, Mods)   | |  Entity Lexicon)| |   Linking/Jaccard) |
          +-----------------+ +-----------------+ +--------------------+
                      \                |                /
                       \               |               /
                        v              v              v
                     +-----------------------------------+
                     |            IntentFrame            |
                     | (Acts, SlotUpdates, ProductTerms) |
                     +-----------------------------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
                   v                                       v
     +---------------------------+           +---------------------------+
     |       StateReducer        |           |       NeedAssessor        |
     | (Enforces 9 Invariants)   |           | (Continuous Routing Score)|
     +---------------------------+           +---------------------------+
        |                     |                            |
        v                     v                            v
+---------------+     +---------------+            +---------------+
| Next Active   |     | Thread-Safe   |            | NeedAssessment|
| State Snapshot|     | SessionStore  |            | (Focus Score &|
+---------------+     +---------------+            | DecisionStage)|
                                                   +---------------+
```

---

## 2. Implemented Modules and Files

### A. Core Package & Configuration
- [`shopping_copilot/config.py`](../shopping_copilot/config.py): Frozen configuration dataclasses controlling parsing thresholds, fuzzy linking margins, and scoring weights.
  - `UnderstandingConfig`: Rule tolerances, confidence priors, fuzzy linking thresholds (`fuzzy_min_score=0.84`, `fuzzy_min_margin=0.08`).
  - `NeedAssessorConfig`: Specificity weights, logistic sigmoid coefficients, and decision stage thresholds.
  - `DialogConfig`: Max turn history and profile weighting defaults.

### B. Understanding Subsystem (`shopping_copilot/understanding/`)
- [`shopping_copilot/understanding/models.py`](../shopping_copilot/understanding/models.py):
  - `Attribute`: Standardized enumeration covering `CATEGORY`, `MATERIAL`, `COLOR`, `SIZE`, `STYLE`, `BUDGET`, `USE_CASE`, `FEATURE`, `BRAND`, `GENDER`, `FIT`, `OCCASION`, `SEASON`, `OTHER`.
  - `Relation`: Operators `EQ`, `NEQ`, `LTE`, `GTE`, `RANGE`, `CONTAINS`, `ONE_OF`.
  - `SlotUpdate`: Atomic slot mutation descriptor (`set`, `add`, `replace`, `exclude`, `set_any`, `clear`), character offsets, modality strength (`hard` vs `soft`), and confidence.
  - `IntentFrame`: Preserves parsed dialogue acts, slot updates, product terms, subjective needs, residual search terms, and parse confidence.
  - `InterpretationAmbiguity`: Captures competing interpretation candidates when disambiguation is required.
- [`shopping_copilot/understanding/rules.py`](../shopping_copilot/understanding/rules.py):
  - **Budget Extraction**: Deterministic regex extraction for LTE (`under $50`, `<= 50`), GTE (`at least $30`, `>= 30`), Ranges (`$25 - $75`, `between $20 and $50`), and Approximate (`budget around $50` with configurable tolerance).
  - **Size Extraction**: Alpha sizes (`S`, `M`, `L`, `XL`, `plus size`), numeric apparel/shoe sizes (`10.5 wide`, `size 8`), and size ranges.
  - **Negations & Exclusions**: Scopes negative contexts (e.g. `"not black or red"`, `"avoid synthetic"`) and maps them to `Relation.NEQ` / `operation="exclude"`.
  - **Dialogue Acts**: Classifies `override`, `indifference`, `explore`, `commit`, and `inform`.
  - **Modality Strength**: Distinguishes `hard` requirements from `soft` preferences.
- [`shopping_copilot/understanding/grounding.py`](../shopping_copilot/understanding/grounding.py):
  - **`CatalogTrie`**: Token trie executing fast longest-match entity extraction over catalog aliases for materials, colors, categories, styles, use cases, and features.
  - **`CatalogEntityLinker`**: Conservative fuzzy linking combining token and character 2-gram Jaccard, `difflib.SequenceMatcher`, and category compatibility. Emits `InterpretationAmbiguity` if competing candidates have narrow margin.
- [`shopping_copilot/understanding/assessment.py`](../shopping_copilot/understanding/assessment.py):
  - **`NeedAssessor`**: Computes continuous features (`category_specificity`, `constraint_density`, `numeric_specificity`, `lexical_specificity`, `parse_certainty`, `commitment`, `exploration`, `unresolved_need_ratio`).
  - Produces continuous routing `focus_score` (via logistic sigmoid) and discrete `decision_stage` (`exploring`, `narrowing`, `deciding`, `unknown`).
- [`shopping_copilot/understanding/interpreter.py`](../shopping_copilot/understanding/interpreter.py):
  - **`MessageInterpreter`**: Coordinates the 10-step parsing cascade, handling structured prefixes (`color: black; budget: <= 50`), contextual elliptical replies using `DialogueContext.last_ask_attribute`, and residual search terms.

### C. Dialog State Tracking Subsystem (`shopping_copilot/dialog/`)
- [`shopping_copilot/dialog/models.py`](../shopping_copilot/dialog/models.py):
  - `CustomerProfile`: Customer metadata, historical rating, and preference tags.
  - `ActiveConstraint`: Active constraint container with attribute, relation, values, strength, source turn, and raw span.
  - `ActiveState`: Immutable frozen snapshot representing the dialog state across turns (`category`, `constraints`, `exclusions`, `any_attributes` suppression set, `profile_preferences`, `raw_phrases`, `residual_product_terms`).
  - `SessionState`, `TurnRecord`, `DialogueContext`: Multi-turn session containers.
- [`shopping_copilot/dialog/reducer.py`](../shopping_copilot/dialog/reducer.py):
  - **`StateReducer`**: Pure state transition function strictly enforcing all 9 state invariants.
- [`shopping_copilot/dialog/store.py`](../shopping_copilot/dialog/store.py):
  - **`SessionStore`**: Thread-safe (`RLock`), managing isolated session state across turns.

---

## 3. The 9 State Reduction Invariants

| # | Invariant Rule | Implementation Mechanism in `StateReducer` |
| :--- | :--- | :--- |
| **1** | Current session evidence outranks Customer Profile | Profile preference tags are only used if no explicit session constraints contradict them. |
| **2** | Later explicit replacements deactivate earlier values | Replacing an attribute slot removes earlier active constraints for that attribute. |
| **3** | Compatible additions remain active | Distinct attribute constraints accumulate across turns. |
| **4** | Exclusions are stored separately | `operation="exclude"` writes to `ActiveState.exclusions` and purges any matching positive constraints. |
| **5** | `set_any` clears active slot & suppresses profile | `operation="set_any"` clears active constraints for that attribute, adds it to `any_attributes` (suppression set), and filters out corresponding profile tags. |
| **6** | Category replacement resets dependent slots | When `category` changes, incompatible category-specific size/style constraints are cleared. |
| **7** | Overridden evidence remains in audit history | Overridden values stay in `SessionState.turn_history` (`TurnRecord`) but are purged from `ActiveState.constraints`. |
| **8** | Inferred evidence cannot overwrite explicit evidence | Slot updates with `explicitness="inferred"` will not overwrite existing slots with `confidence >= 0.90`. |
| **9** | Missing evidence does not clear existing values | When a turn omits an attribute, earlier active constraints for that attribute persist. |

---

## 4. Handling the 4 Simulator Scenarios

1. **Buying Scenario**:
   - Turn 1 User: `"I'm looking for running shoes. A key requirement is: 100% cotton; budget under $50."`
   - Parsed: `category="running shoes"`, `material="cotton"` (`strength="hard"`), `budget <= 50.0`.
   - Assessment: High `focus_score` (>0.60), `decision_stage="deciding"` or `"narrowing"`.
2. **Browsing Scenario**:
   - Turn 1 User: `"I'm looking for coats, but I'm still exploring."`
   - Parsed: `category="coats"`, `dialogue_acts=("explore",)`.
   - Assessment: `decision_stage="exploring"`, high `exploration` score, preserves broad retrieval terms.
   - Turn 2 User (clarification reply): `"For that, what matters is: wool."`
   - Parsed via contextual resolution to `material="wool"`.
3. **Intent Override Scenario**:
   - Turn 1 User: `"I'm looking for jackets. I prefer fleece fabric."`
   - Turn 2 User: `"Actually, ignore my earlier preference. What I need is: 100% genuine leather."`
   - State Reducer: Deactivates stale `fleece` constraint and activates `leather`. Outdated terms never leak into subsequent retrieval.
4. **Boundary Scenario**:
   - Turn 1 Agent: Clarifies attribute `color`.
   - Turn 2 User: `"I don't have a preference for color; please use your judgment."`
   - State Reducer: Marks `Attribute.COLOR` as `set_any`, adds to `any_attributes` suppression set, and suppresses profile tags matching `color`.

---

## 5. How to Test

### A. Run Full Test Suite
Run all unit and integration tests from project root:
```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

### B. Run Subsystem Test Suites Individually

- **Understanding & Rules Unit Tests**:
  ```bash
  python3 -m unittest tests/unit/test_understanding.py -v
  ```
- **Dialog Reducer & Invariants Unit Tests**:
  ```bash
  python3 -m unittest tests/unit/test_dialog.py -v
  ```
- **Competition Scenarios Integration Tests**:
  ```bash
  python3 -m unittest tests/integration/test_scenarios_nlu.py -v
  ```
- **eCommerce Utterance Corpus Tests**:
  ```bash
  python3 -m unittest tests/unit/test_interpreter_corpus.py -v
  ```

---

### C. Interactive Python Testing Code

#### 1. Single Utterance Understanding & Assessment
```python
from shopping_copilot.understanding.interpreter import MessageInterpreter
from shopping_copilot.understanding.assessment import NeedAssessor
from shopping_copilot.dialog.reducer import StateReducer
from shopping_copilot.dialog.models import ActiveState

interpreter = MessageInterpreter()
assessor = NeedAssessor()

# Sample input message
msg = "I need a navy blue running shirt under $40, but avoid polyester"
frame = interpreter.parse(msg)

print("=== PARSED INTENT FRAME ===")
print("Dialogue Acts:", frame.dialogue_acts)
print("Product Terms:", frame.product_terms)
for s in frame.slot_updates:
    print(f"  Attr: {s.attribute.value:<10} | Op: {s.operation:<8} | Rel: {s.relation.value:<5} | Vals: {s.normalized_values} | Modality: {s.strength}")

state = StateReducer.reduce(ActiveState(), frame, turn=1)
print("\n=== ACTIVE DIALOG STATE ===")
print("Category:   ", state.category)
print("Constraints:", [(c.attribute.value, c.relation.value, c.values) for c in state.constraints])
print("Exclusions: ", [(e.attribute.value, e.relation.value, e.values) for e in state.exclusions])

assessment = assessor.assess(state, frame)
print("\n=== NEED ASSESSMENT ===")
print(f"Decision Stage: {assessment.decision_stage}")
print(f"Focus Score:    {assessment.focus_score}")
print(f"Specificity:    {assessment.specificity}")
print(f"Exploration:    {assessment.exploration}")
```

#### 2. Multi-Turn Dialogue & Intent Override Simulation
```python
from shopping_copilot.understanding.interpreter import MessageInterpreter
from shopping_copilot.dialog.reducer import StateReducer
from shopping_copilot.dialog.store import SessionStore
from shopping_copilot.understanding.models import Attribute

store = SessionStore()
interpreter = MessageInterpreter()
store.reset("sess_demo", user_profile={"preference_tags": ["color: black"]})

# Turn 1: User prefers fleece
turn1_msg = "I want a warm fleece jacket."
ctx1 = store.get_dialogue_context("sess_demo", turn=1)
frame1 = interpreter.parse(turn1_msg, context=ctx1)
state1 = StateReducer.reduce(store.get_session("sess_demo").active_state, frame1, turn=1)
store.update_active_state("sess_demo", state1)
print("Turn 1 Constraints:", [(c.attribute.value, c.values) for c in state1.constraints])

# Turn 2: User overrides earlier preference
turn2_msg = "Actually, ignore my earlier preference. What I need is: 100% genuine leather."
ctx2 = store.get_dialogue_context("sess_demo", turn=2)
frame2 = interpreter.parse(turn2_msg, context=ctx2)
state2 = StateReducer.reduce(store.get_session("sess_demo").active_state, frame2, turn=2)
store.update_active_state("sess_demo", state2)
print("Turn 2 Constraints (Fleece deactivated, Leather active):", [(c.attribute.value, c.values) for c in state2.constraints])
```

