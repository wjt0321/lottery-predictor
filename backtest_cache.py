#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Request-scoped bounded cache for runtime-invariant backtest contexts."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Callable, Dict, Hashable, Iterable, Optional, TypeVar

CACHE_SCHEMA_VERSION = "backtest-context/v1"
T = TypeVar("T")


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def make_backtest_context_key(
    records: Iterable[Dict[str, object]],
    cycles: int,
    seed: Optional[int],
    initial_weights: Optional[Dict[str, float]],
    ticket_count: int,
) -> tuple:
    """Build a deterministic key from inputs that affect prepared contexts."""
    return (
        CACHE_SCHEMA_VERSION,
        _canonical_hash(list(records)),
        int(cycles),
        int(seed or 0),
        _canonical_hash(initial_weights or {}),
        int(ticket_count),
    )


class BacktestContextCache:
    """A small LRU cache with additive telemetry.

    Values are intentionally opaque. The caller owns immutability guarantees
    for cached contexts and the cache never persists data across processes.
    """

    def __init__(self, max_entries: int = 8):
        max_entries = int(max_entries)
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self.max_entries = max_entries
        self._values: "OrderedDict[Hashable, object]" = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.prepared_samples = 0

    def get_or_prepare(self, key: Hashable, factory: Callable[[], T]) -> T:
        if key in self._values:
            self.hits += 1
            value = self._values.pop(key)
            self._values[key] = value
            return value  # type: ignore[return-value]
        self.misses += 1
        value = factory()
        try:
            sample_count = len(value)  # type: ignore[arg-type]
        except TypeError:
            sample_count = 1
        self.prepared_samples += int(sample_count)
        self._values[key] = value
        while len(self._values) > self.max_entries:
            self._values.popitem(last=False)
            self.evictions += 1
        return value

    def snapshot(self) -> Dict[str, int]:
        return {
            "max_entries": self.max_entries,
            "entries": len(self._values),
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "prepared_samples": self.prepared_samples,
        }
