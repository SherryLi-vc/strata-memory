"""Deterministic hashing embedder.

Used when the local provider is selected and neither fastembed nor
sentence-transformers is installed. Vectors stay on the machine, need no
download, and need no API key. They match shared tokens, not paraphrases.

The same idea ships in other local-first memory projects (a blake2 feature
hash in memoryos, character n-gram hashing in litesearch). Those packages
are not dependencies here: this is the stdlib version, fixed to the
configured dimension, so ``uvx strata-memory-mcp`` stays offline by default.
Install the ``local`` extra for a semantic model, then rebuild the index.
"""

from __future__ import annotations

import hashlib
import math
import re

_WORD = re.compile(r"[a-z0-9]+")


def hash_embed(text: str, dimension: int) -> list[float]:
    """L2-normalized signed feature hash of alphanumeric tokens."""
    dim = max(1, int(dimension))
    vec = [0.0] * dim
    for token in _WORD.findall((text or "").lower()):
        if len(token) < 2:
            continue
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[index] += sign
    norm = math.sqrt(sum(value * value for value in vec)) or 1.0
    return [value / norm for value in vec]
