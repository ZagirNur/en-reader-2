"""Open-dictionary lookup (dictionaryapi.dev) with a prompt-hash cache.

Provides the IPA pronunciation + canonical English definitions and
example sentences that land on the training card (M20.1). The API is
free, has no key, and is backed by Wiktionary data — a "good enough"
source for the top ~60 k most common English headwords.

Cache layer reuses ``llm_cache`` from :mod:`en_reader.storage` so one
``/debug/health`` blob shows both LLM and dictionary cache growth; the
hash prefix (``"dict-v1"``) and the ``"dictionaryapi.dev"`` model tag
partition the namespace so a future dictionary swap can invalidate in
place by bumping the prefix.

A missing entry (phrasal verbs, typos, rare lemmas) is itself cached —
as an empty list JSON — so we don't burn a round-trip every time a
user reopens the same unrecognised word.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from . import storage

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/"
_TIMEOUT_SECONDS = 6.0
_MODEL_TAG = "dictionaryapi.dev"
_CACHE_PREFIX = "dict-v1"


@dataclass
class DictMeaning:
    """One POS-grouped block of definitions from the dictionary entry.

    Flattened to the fields the card actually renders: ``pos`` (noun,
    verb, ...), two to three ``definitions`` as plain English strings,
    and up to three ``examples`` in English. The raw API payload has
    more (antonyms, synonyms per-definition, nested structure) but the
    card UI gets cluttered fast — we cap at the useful minimum.
    """

    pos: str
    definitions: list[str]
    examples: list[str]


@dataclass
class DictEntry:
    """Parsed dictionaryapi.dev response, trimmed to what the card needs."""

    word: str
    ipa: str
    audio_url: str
    meanings: list[DictMeaning]
    synonyms: list[str]


def _cache_key(word: str) -> str:
    """Deterministic prompt-hash-style key for ``llm_cache`` lookup.

    Folds in the ``dict-v1`` version prefix so a schema change (say,
    keeping more examples per meaning) can invalidate the whole cache
    by bumping ``_CACHE_PREFIX`` without manual SQL.
    """
    h = hashlib.sha256()
    h.update(_CACHE_PREFIX.encode("utf-8"))
    h.update(b"\n")
    h.update(word.lower().encode("utf-8"))
    return h.hexdigest()


def _parse_response(payload: Any) -> list[DictMeaning]:
    """Extract up to three meanings (one per POS) from the raw JSON.

    Defensive: dictionaryapi.dev can return partial records (no
    phonetics array, meaning with no example, etc.). Everything below
    swallows missing fields and falls back to an empty string/list so
    the card layer never has to null-check.
    """
    meanings: list[DictMeaning] = []
    if not isinstance(payload, list):
        return meanings
    for entry in payload:
        for m in entry.get("meanings", []) or []:
            pos = (m.get("partOfSpeech") or "").strip()
            defs_src = m.get("definitions") or []
            definitions: list[str] = []
            examples: list[str] = []
            for d in defs_src[:3]:
                text = (d.get("definition") or "").strip()
                if text:
                    definitions.append(text)
                ex = (d.get("example") or "").strip()
                if ex:
                    examples.append(ex)
            if not definitions:
                continue
            meanings.append(
                DictMeaning(
                    pos=pos,
                    definitions=definitions[:3],
                    examples=examples[:3],
                )
            )
        if len(meanings) >= 3:
            break
    return meanings[:3]


def _pick_ipa_and_audio(payload: Any) -> tuple[str, str]:
    """Return ``(ipa, audio_url)`` picked from the first entry with data.

    dictionaryapi.dev emits a top-level ``phonetic`` and a
    ``phonetics[]`` array with per-recording variants. We walk both and
    return the first non-empty pair, because some entries have the IPA
    on the array and others on the top-level.
    """
    ipa = ""
    audio = ""
    if not isinstance(payload, list):
        return ipa, audio
    for entry in payload:
        if not ipa:
            ipa = (entry.get("phonetic") or "").strip()
        for ph in entry.get("phonetics", []) or []:
            if not ipa:
                ipa = (ph.get("text") or "").strip()
            if not audio:
                audio = (ph.get("audio") or "").strip()
            if ipa and audio:
                return ipa, audio
        if ipa and audio:
            break
    return ipa, audio


def _collect_synonyms(payload: Any) -> list[str]:
    """Flatten synonyms across all meanings; dedupe, cap at 5 entries."""
    seen: set[str] = set()
    out: list[str] = []
    if not isinstance(payload, list):
        return out
    for entry in payload:
        for m in entry.get("meanings", []) or []:
            for syn in m.get("synonyms", []) or []:
                s = (syn or "").strip().lower()
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
                    if len(out) >= 5:
                        return out
    return out


def fetch_entry(word: str) -> DictEntry | None:
    """Fetch ``word`` from dictionaryapi.dev, parse, cache. ``None`` on 404.

    The raw API payload (or the sentinel ``"[]"`` for a 404) lands in
    ``llm_cache`` keyed by :func:`_cache_key`. Subsequent lookups skip
    the HTTP round-trip entirely. Network / parse failures return
    ``None`` without caching, so a transient DNS glitch doesn't pin a
    bogus "not found" for the lemma.
    """
    lower = word.strip().lower()
    if not lower:
        return None

    key = _cache_key(lower)
    cached = storage.llm_cache_get(key)
    if cached is not None:
        logger.info("dict cache HIT key=%s word=%r", key[:12], lower)
        try:
            payload = json.loads(cached)
        except json.JSONDecodeError:
            payload = []
    else:
        logger.info("dict cache MISS key=%s word=%r", key[:12], lower)
        url = _BASE_URL + lower
        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                resp = client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("dict fetch failed word=%r err=%r", lower, exc)
            return None
        if resp.status_code == 404:
            # Cache the miss as an empty array so repeat lookups on
            # phrasal verbs etc. don't keep hammering the API.
            storage.llm_cache_put(key, _MODEL_TAG, "[]")
            return None
        if resp.status_code != 200:
            logger.warning("dict fetch non-200 word=%r status=%d", lower, resp.status_code)
            return None
        try:
            payload = resp.json()
        except ValueError:
            logger.warning("dict fetch non-JSON word=%r", lower)
            return None
        storage.llm_cache_put(key, _MODEL_TAG, json.dumps(payload, ensure_ascii=False))

    meanings = _parse_response(payload)
    if not meanings:
        return None
    ipa, audio = _pick_ipa_and_audio(payload)
    synonyms = _collect_synonyms(payload)
    return DictEntry(
        word=lower,
        ipa=ipa,
        audio_url=audio,
        meanings=meanings,
        synonyms=synonyms,
    )
