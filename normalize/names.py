"""Helpers for canonicalizing bookmaker-specific names.

The Odds API may return slightly different team or player names per bookmaker.
These helpers provide a central place for deterministic and fuzzy matching so
that arbitrage analysis can align outcomes across books.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict


class NameNormalizer:
    """Maps bookmaker-provided names to canonical forms."""

    def __init__(self, overrides: Dict[str, str] | None = None) -> None:
        self._overrides = {k.casefold(): v for k, v in (overrides or {}).items()}

    def canonicalize(self, value: str) -> str:
        key = value.casefold().strip()
        if key in self._overrides:
            return self._overrides[key]
        normalized = _squash_whitespace(_strip_suffixes(key))
        return normalized.title()

    def update(self, mapping: Dict[str, str]) -> None:
        for raw, canonical in mapping.items():
            self._overrides[raw.casefold()] = canonical


def _strip_suffixes(value: str) -> str:
    return re.sub(r"\b(f.c.|fc|club)\b", "", value, flags=re.IGNORECASE)


@lru_cache(maxsize=512)
def _squash_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())
