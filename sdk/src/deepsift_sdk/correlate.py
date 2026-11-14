"""Correlation across tasks: what no single service can see (contract section 6)."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from typing import TypeVar

K = TypeVar("K", bound=Hashable)

#: Maximum Hamming distance between two 64-bit perceptual hashes of the same picture.
#: Resizing and recompression usually stay under 4; different photos are above 10.
PHASH_THRESHOLD = 6


def hamming(a: str, b: str) -> int:
    """Number of differing bits between two hex-encoded hashes of the same length."""
    return (int(a, 16) ^ int(b, 16)).bit_count()


def cluster(hashes: Mapping[K, str], threshold: int = PHASH_THRESHOLD) -> list[set[K]]:
    """Group keys whose hashes are within ``threshold`` bits, transitively (union-find)."""
    keys = list(hashes)
    parent = {key: key for key in keys}

    def root(key: K) -> K:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if hamming(hashes[a], hashes[b]) <= threshold:
                parent[root(a)] = root(b)

    groups: dict[K, set[K]] = {}
    for key in keys:
        groups.setdefault(root(key), set()).add(key)
    return list(groups.values())
