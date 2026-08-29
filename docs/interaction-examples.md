# Expected Shopping Interactions

These examples describe intended behavior, not fixed response snapshots. Exact
products depend on the frozen catalog and current ranking configuration.

## Compound buying request

Customer:

> I'm looking for running shoes under $100, preferably blue, no leather.

Expected handling:

- category becomes `running shoes`;
- `under $100` becomes a budget bound;
- `blue` remains a positive session preference;
- `leather` becomes an exclusion;
- missing product price is neutral rather than treated as over budget;
- the same turn returns recommendations and one useful non-repeated question.

## Browsing and recovery

Customer:

> I need something for a humid outdoor wedding, but I'm not sure what style.

The deterministic path retains the raw need for lexical search. When the
optional semantic parser is explicitly enabled, it may propose short rewrites
and soft needs, but it cannot return product IDs. If a specific clarification
is declined, the agent asks once what other requirement matters most instead of
walking through every catalog field.

## Intent correction

Customer:

> Actually, make it waterproof instead.

`waterproof` replaces stale session preference evidence before retrieval.
Recommendation Exposure resets because products rejected under the old need may
be valid under the corrected need. Category evidence remains unless the customer
also changes the requested product category.

## No preference

Customer:

> I don't have a preference for color; use your judgment.

Color is removed and suppressed for later questions. The agent continues with
ten recommendations and may use one broad recovery question. It does not infer
a favorite color from the anonymized profile.

## Known limits

- Negation scope is conservative; complex clauses still need more corpus tests.
- `black or navy` is searchable but does not yet have a first-class OR group.
- Relative language such as `cheaper than the last one` is not grounded because
  the API provides no product-selection event.
- Semantic model quality, cost, and latency are unknown until a real key and
  explicit model are evaluated.
