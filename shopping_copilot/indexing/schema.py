from __future__ import annotations

# In-memory SQLite FTS5 table definitions
CREATE_PRODUCTS_FTS_SQL = """
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
"""

CREATE_PRODUCTS_VOCAB_SQL = """
CREATE VIRTUAL TABLE products_vocab USING fts5vocab(products, row);
"""

# Default BM25 field weights ordered by column position in FTS5 table
# Columns: parent_asin (0), title (1), categories (2), features (3), details (4), store (5), description (6)
DEFAULT_BM25_FIELD_WEIGHTS: tuple[float, ...] = (
    0.0,  # parent_asin (UNINDEXED)
    6.0,  # title
    4.0,  # categories
    2.5,  # features
    2.5,  # details
    1.5,  # store
    1.0,  # description
)

# Max terms to include in FTS5 query to prevent unbounded expressions
MAX_FTS_QUERY_TERMS = 24
