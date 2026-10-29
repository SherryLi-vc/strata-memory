"""Query-conditioned lexical scores for recall.

SQLite FTS5 already implements BM25, and that score is what ``fts_search``
orders by. FTS5 only assigns ``bm25()`` to rows that satisfy ``MATCH``.
The previous recall query AND-ed every token, so a natural-language question
often matched nothing and L0 rows never entered the ranked list.

``rank-bm25`` (https://github.com/dorianbrown/rank_bm25) is the usual
pure-Python Okapi implementation. It depends on numpy, which this process
does not otherwise need for ranking. The function below is the same Okapi
formula (k1=1.2, b=0.75) over the candidate set already loaded for the
request, so unmatched rows score 0 instead of disappearing.
"""

from __future__ import annotations

import math
import re

_WORD = re.compile(r"[a-z0-9]+")

# Function words that would make an OR query match almost every card.
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "to",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "this",
        "that",
        "it",
        "its",
        "user",
        "what",
        "which",
        "how",
        "does",
        "do",
        "did",
        "then",
        "into",
        "onto",
        "about",
        "your",
        "their",
    }
)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens with function words removed."""
    return [tok for tok in _WORD.findall((text or "").lower()) if len(tok) >= 2 and tok not in _STOP]


def fts_or_query(text: str, limit: int = 12) -> str:
    """FTS5 ``OR`` query. Empty when the question has no content words."""
    terms = list(dict.fromkeys(tokenize(text)))[: max(1, limit)]
    if not terms:
        return ""
    return " OR ".join(f'"{term}"' for term in terms)


def lexical_scores(query: str, documents: list[tuple[str, str]]) -> dict[str, float]:
    """Okapi BM25 of ``query`` against ``(doc_id, text)`` pairs.

    Scores are >= 0. A document that shares no query term scores 0.
    """
    query_terms = list(dict.fromkeys(tokenize(query)))
    if not query_terms or not documents:
        return {doc_id: 0.0 for doc_id, _text in documents}

    tokenized = [(doc_id, tokenize(text)) for doc_id, text in documents]
    doc_count = len(tokenized)
    doc_freq: dict[str, int] = {}
    for _doc_id, tokens in tokenized:
        for term in set(tokens):
            doc_freq[term] = doc_freq.get(term, 0) + 1
    avgdl = sum(len(tokens) for _doc_id, tokens in tokenized) / doc_count
    avgdl = max(avgdl, 1.0)

    scores: dict[str, float] = {}
    for doc_id, tokens in tokenized:
        if not tokens:
            scores[doc_id] = 0.0
            continue
        tf: dict[str, int] = {}
        for term in tokens:
            tf[term] = tf.get(term, 0) + 1
        dl = len(tokens)
        score = 0.0
        for term in query_terms:
            freq = tf.get(term, 0)
            if freq <= 0:
                continue
            df = doc_freq.get(term, 0)
            idf = math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))
            denom = freq + 1.2 * (0.25 + 0.75 * dl / avgdl)
            score += idf * (freq * 2.2) / denom
        scores[doc_id] = score
    return scores


def squash_lexical(score: float) -> float:
    """Map a non-negative BM25 score into (0, 1) without flattening ties."""
    if score <= 0:
        return 0.0
    return score / (score + 1.2)
