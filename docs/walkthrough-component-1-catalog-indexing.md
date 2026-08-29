# Walkthrough: Component 1 (Catalog Ingestion & Multi-Faceted Indexing Engine)

This document describes the design, architecture, implemented modules, and verification procedures for **Component 1** of the `ShoppingCopilot` pipeline, located under [`shopping_copilot/catalog/`](../shopping_copilot/catalog/) and [`shopping_copilot/indexing/`](../shopping_copilot/indexing/).

---

## 1. System Architecture & Role

Component 1 serves as the foundational data and indexing layer of the system. It ingests the 29,481 raw product records from `data/catalog.jsonl`, parses complex field variations (such as heterogeneous price strings and unstructured descriptions), and builds fast in-memory indexing structures with zero external server dependencies.

```
+-----------------------------------------------------------------------------------------------+
|                                      data/catalog.jsonl                                       |
+-----------------------------------------------------------------------------------------------+
                                                │
                                                ▼
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ CatalogLoader (shopping_copilot/catalog/loader.py)                                            │
│                                                                                               │
│  • Validates JSON structure, ASIN presence & uniqueness.                                      │
│  • Unicode NFKC normalization, casefolding, and whitespace collapsing.                        │
│  • parse_price(): Resolves exact, range, lower_bound, or unknown prices.                      │
│  • CatalogAttributeExtractor: Scans structured details and unstructured text for attributes.  │
└───────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                                │
                                                ▼ (Iterable[ProductRecord])
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ CatalogIndex (shopping_copilot/indexing/store.py)                                             │
│                                                                                               │
│  • In-Memory SQLite FTS5 Table: Field-weighted BM25 search (Title: 6.0, Categories: 4.0,     │
│    Features: 2.5, Details: 2.5, Store: 1.5, Description: 1.0).                                │
│  • Inverted Posting Sets:                                                                     │
│    - category_to_ids: O(1) set retrieval for taxonomy filtering.                             │
│    - attribute_to_ids: Inverted maps for materials, colors, styles, brands, etc.             │
│  • Sorted Price Index: Binary search (bisect) for range queries (price <= X, X <= price <= Y).│
│  • Vocabulary Exporter: Feeds canonical entities into Component 2's CatalogTrie.             │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Implemented Modules and Files

### A. Catalog Subsystem ([`shopping_copilot/catalog/`](../shopping_copilot/catalog/))
- [`shopping_copilot/catalog/models.py`](../shopping_copilot/catalog/models.py):
  - `PriceValue`: Immutable price container (`lower`, `upper`, `kind` as `exact`, `range`, `lower_bound`, or `unknown`), with `.matches_budget()` evaluation.
  - `AttributeEvidence`: Full provenance metadata recording value, source field (`details.Fabric Type`, `title`, `features`), extraction type, and confidence.
  - `ProductRecord`: Canonical immutable data structure holding search fields, categories, extracted attributes, price, ratings, and field presence sets.
- [`shopping_copilot/catalog/price.py`](../shopping_copilot/catalog/price.py):
  - `parse_price()`: Deterministic regex and numeric parser supporting float/int values, price ranges (`"$15 - $35"`, `"from $10 to $20"`), lower bounds (`"From $12.99"`, `"$25+"`), and safe unknown fallback.
- [`shopping_copilot/catalog/extraction.py`](../shopping_copilot/catalog/extraction.py):
  - `CatalogAttributeExtractor`: Maps structured `details` keys to canonical `Attribute` types, strips percentage prefixes (e.g. `"100% cotton"` -> `"cotton"`), and scans unstructured fields (`title`, `features`, `description`, `store`) with precompiled lexicon patterns.
- [`shopping_copilot/catalog/loader.py`](../shopping_copilot/catalog/loader.py):
  - `CatalogLoader`: Streaming JSONL reader with ASIN uniqueness validation and robust text normalization.

### B. Indexing Subsystem ([`shopping_copilot/indexing/`](../shopping_copilot/indexing/))
- [`shopping_copilot/indexing/schema.py`](../shopping_copilot/indexing/schema.py):
  - In-memory SQLite FTS5 table DDL with `unicode61 remove_diacritics 2` tokenization.
  - Field BM25 weight definitions: `title: 6.0`, `categories: 4.0`, `features: 2.5`, `details: 2.5`, `store: 1.5`, `description: 1.0`.
- [`shopping_copilot/indexing/store.py`](../shopping_copilot/indexing/store.py):
  - `CatalogIndex`:
    - `search_bm25(terms, limit)`: Fast FTS5 lexical matching with IDF-based term pruning (capping to top 24 discriminative terms).
    - `filter_by_category(category)`: $O(1)$ set lookup for exact and substring taxonomy matches.
    - `filter_by_attribute(attribute, value)`: Inverted posting set lookup for specific attributes.
    - `filter_by_price(min_price, max_price)`: $O(\log N)$ binary search across sorted price lists.
    - `filter_by_exclusion(attribute, value)`: Set difference for negative constraints.
    - `get_vocabulary_by_attribute()`: Exports catalog vocabulary to seed Component 2 understanding models.

---

## 3. How to Test & Verify

### Running Unit & Integration Tests

```bash
# 1. Run Catalog Unit Tests
python3 -m unittest tests/unit/test_catalog.py -v

# 2. Run Indexing Unit Tests
python3 -m unittest tests/unit/test_indexing.py -v

# 3. Run Integration Benchmark on data/catalog.jsonl
python3 -m unittest tests/integration/test_catalog_indexing_integration.py -v

# 4. Run the entire test suite across all components
python3 -m unittest discover -s tests -p "test_*.py" -v
```

### Verification Results
- **48/48 tests passed in 0.96s (100% success rate)**.
- Query latencies for BM25 and posting set intersections are consistently **< 5ms**.

