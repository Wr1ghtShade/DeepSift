"""Correlation across tasks: what no single service can see (contract section 6)."""

from __future__ import annotations

import string
from collections import defaultdict
from collections.abc import Hashable, Iterable, Mapping
from typing import Any, TypeVar

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


def group_name(index: int) -> str:
    """A, B, … Z, A1, B1, …"""
    return string.ascii_uppercase[index % 26] + ("" if index < 26 else str(index // 26))


def group_avatars(
    links: Iterable[tuple[K, str, K]],
    hash_attributes: Mapping[K, Mapping[str, Any]],
    threshold: int = PHASH_THRESHOLD,
) -> list[tuple[str, list[K], list[str]]]:
    """Profiles on different sites that use the same picture.

    ``links`` are (source, rel, target) triples: ``avatar`` goes from a profile to an
    image, ``hash`` from an image to an image_hash. ``hash_attributes`` holds each
    image_hash's attributes (``phash``, ``trivial``). Returns (name, profiles, phashes)
    for every cluster of close hashes covering two profiles or more.
    """
    profiles_of_image: dict[K, set[K]] = defaultdict(set)
    images_of_hash: dict[K, set[K]] = defaultdict(set)
    for source, rel, target in links:
        if rel == "avatar":
            profiles_of_image[target].add(source)
        elif rel == "hash":
            images_of_hash[target].add(source)

    phashes: dict[K, str] = {}
    for hash_key in images_of_hash:
        attributes = hash_attributes.get(hash_key) or {}
        if attributes.get("phash") and not attributes.get("trivial"):
            phashes[hash_key] = str(attributes["phash"])

    groups = []
    for hash_keys in cluster(phashes, threshold):
        profiles = {
            profile
            for hash_key in hash_keys
            for image in images_of_hash[hash_key]
            for profile in profiles_of_image[image]
        }
        if len(profiles) >= 2:
            groups.append((sorted(profiles), sorted(phashes[k] for k in hash_keys)))
    return [
        (group_name(i), profiles, hashes) for i, (profiles, hashes) in enumerate(sorted(groups))
    ]
