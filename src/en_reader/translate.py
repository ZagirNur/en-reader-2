"""Gemini-backed LLM calls for en-reader (translation + training cards).

Two public entry points:

* :func:`translate_one` — English word/phrase → short Russian translation,
  with ± 1 sentence of surrounding context (M19.1).
* :func:`generate_training_card` — AI-built SRS card for a lemma, using
  the original context the word was first met in.

Both funnel through :func:`_cached_llm_call`, a prompt-hash cache backed
by the ``llm_cache`` SQLite table (M19.1). The key includes the model
name + the full system + user prompt, so per-instance translation
requests that happen to share a sentence context de-dupe naturally
without the caller knowing.

Retries (up to 3 with exponential backoff), input validation, and
structured logging stay here so the API handlers remain boring.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import asdict
from typing import Any

from google import genai

from . import dictionary, storage
from .metrics import counters

logger = logging.getLogger(__name__)


TRANSLATE_SYSTEM_PROMPT = """You are a professional English-to-Russian literary translator.
You receive a single English word or short phrase and the sentence it appears in,
plus (optionally) the previous and next sentence for context.
Return ONLY the best Russian translation of the word/phrase, in context.
Rules:
- One short translation, no variants, no explanations.
- Preserve capitalization (lowercase common words, Title Case for proper nouns).
- For a phrasal verb given as a whole (e.g. "look up"), return a single Russian verb or expression.
- If the phrase is the verb part of a split phrasal verb (particle is elsewhere in the sentence),
  still return the full Russian translation including what the particle contributes.
- No punctuation except what belongs to the translation. No quotes, no parentheses.
- Max 60 characters."""


CARD_SYSTEM_PROMPT = """You are building a compact flash-card for a Russian-speaking
learner of English. You receive one English word or phrase, its short Russian
translation, and the example sentence the learner first met it in.

Return a Markdown card with EXACTLY these four sections, no preamble, no trailing text:

**Значение:** one short Russian sentence explaining the meaning and usage nuance (max 120 chars).
**Пример:** one clear English sentence using the word (NOT the one provided). Max 120 chars.
**Синонимы:** up to 3 common English synonyms, comma-separated. Skip the line if none fit.
**Запомни:** one short mnemonic or usage hint in Russian (max 100 chars).

Keep the whole card under 600 characters. No HTML, no links, no headings above level-2."""


# M20.1 — the structured card (``card_json``). Feeds the per-POS
# definitions + example translations to Gemini, and asks for one extra
# example "in a different situation" so the learner sees the word used
# in more than one register. The model is told to return bare JSON; we
# parse with a small rescue wrapper so a leading/trailing ``
RICH_CARD_SYSTEM_PROMPT = """You are building a structured flash-card for a
Russian-speaking learner of English.

You receive:
- the English headword (or phrase)
- its short Russian translation
- the sentence the learner first met it in
- optionally, a list of English definitions the user already has from a dictionary
- optionally, a list of English example sentences the user already has

Return ONLY a JSON object with this exact shape (no Markdown code fences, no prose):

{
  "definitions_ru": ["Russian translations of the provided definitions, same order, max 140 chars each"],
  "examples": [
    {"en": "English example sentence in a specific context", "ru": "russian translation of the example"},
    ...
  ],
  "usage_note_ru": "one short Russian sentence describing a nuance or common pitfall (max 180 chars)"
}

Rules:
- ``definitions_ru`` mirrors whatever list of definitions you got, in the same
  order. If you were given zero definitions, return an empty array.
- ``examples`` MUST contain at least three items that together show the word in
  DIFFERENT situations (formal / casual / literal / idiomatic as applicable).
  Reuse the provided user examples if any, translate them, and invent more.
- Keep every string short. No HTML, no Markdown, no quotes around the JSON.
- If you cannot produce a valid card, return ``{"definitions_ru":[],"examples":[],"usage_note_ru":""}``."""


SIMPLIFY_SYSTEM_PROMPT = """You are an English-language vocabulary simplifier
for an intermediate learner. You receive ONE English word or short phrase
and the sentence it appears in, plus optional surrounding sentences.

Return the SIMPLEST common English synonym that fits the sentence — same
part of speech, same number / tense / case, so the user can drop it into
the sentence and the grammar still works. Preserve capitalization.

Special case: if the input word is ALREADY among the most common simple
English words for its meaning (e.g. "drop", "run", "see"), and no
significantly simpler synonym exists, return EXACTLY the literal token
``@SAME@`` — the caller treats that as "no simpler form, just open the
card".

Rules:
- One word or short phrase only. No explanations, no quotes.
- Match the inflection of the input ("ran" → "sprinted", not "sprint").
- Plain ASCII apostrophes only ("don't"). No HTML, no Markdown.
- Max 40 characters.
- If you cannot decide, prefer ``@SAME@`` over a wrong answer."""


_MAX_ATTEMPTS = 3
_BACKOFFS = (0.5, 1.0, 2.0)
_MAX_TRANSLATE_LEN = 60
_MAX_CARD_LEN = 1000
_MAX_SIMPLIFY_LEN = 40

# Lazy module-level Gemini client; initialized on first call.
_client: genai.Client | None = None


class TranslateError(Exception):
    """Raised when all attempts to obtain a valid response fail."""


def _sleep(seconds: float) -> None:
    """Thin wrapper around :func:`time.sleep` so tests can stub retries out."""
    time.sleep(seconds)


def _get_client() -> genai.Client:
    """Return a cached :class:`genai.Client`, building it on first call.

    Raises :class:`TranslateError` if ``GEMINI_API_KEY`` is not set.
    """
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise TranslateError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=api_key)
    return _client


def _is_valid_translation(text: str) -> bool:
    """Return True if ``text`` is a plausible single-line translation."""
    if not text or not text.strip():
        return False
    if "<" in text or ">" in text:
        return False
    if "\n" in text or "\r" in text:
        return False
    if len(text) > _MAX_TRANSLATE_LEN:
        return False
    return True


def _is_valid_card(text: str) -> bool:
    """Return True if ``text`` looks like a card (non-empty, bounded length)."""
    if not text or not text.strip():
        return False
    if len(text) > _MAX_CARD_LEN:
        return False
    return True


def _prompt_hash(model: str, system: str, user: str) -> str:
    """Compute the content-addressed cache key for an LLM call.

    Folds in the model name so the same prompt against
    ``gemini-2.5-flash-lite`` and ``gemini-2.5-pro`` does not collide.
    Uses a version prefix so we can invalidate the whole cache by bumping
    the prefix if the prompt contract changes in a backwards-incompatible
    way.
    """
    h = hashlib.sha256()
    h.update(b"v1\n")
    h.update(model.encode("utf-8"))
    h.update(b"\n---SYSTEM---\n")
    h.update(system.encode("utf-8"))
    h.update(b"\n---USER---\n")
    h.update(user.encode("utf-8"))
    return h.hexdigest()


def _call_model(client: Any, model_name: str, system: str, user_prompt: str) -> str:
    """One Gemini round-trip. No retries, no cache — pure I/O."""
    resp = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config={"system_instruction": system, "temperature": 0.2},
    )
    return (resp.text or "").strip()


def _cached_llm_call(
    system: str, user: str, *, validator, model: str | None = None
) -> tuple[str, str]:
    """Call Gemini (with retries), passing through the SQLite prompt-hash cache.

    Returns ``(response_text, source)`` where ``source`` is one of:

    * ``"mock"`` — the ``E2E_MOCK_LLM=1`` short-circuit fired.
    * ``"cache"`` — found in ``llm_cache`` by prompt hash; no SDK call.
    * ``"llm"`` — actual Gemini round-trip (result then written to cache).

    Key is ``sha256(v1 || model || system || user)``. Cache HITs bypass
    the SDK entirely; MISSes go through the ``_MAX_ATTEMPTS`` retry loop
    with ``_BACKOFFS`` delays, and the first valid response is written
    back. ``validator`` is a callable returning ``True`` iff the text is
    usable — mis-shaped replies are treated like SDK errors.
    """
    model_name = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

    if os.environ.get("E2E_MOCK_LLM") == "1":
        return f"RU:{user[:40]}", "mock"

    key = _prompt_hash(model_name, system, user)
    cached = storage.llm_cache_get(key)
    if cached is not None:
        counters.llm_cache_hit += 1
        logger.info("llm cache HIT key=%s len=%d", key[:12], len(cached))
        return cached, "cache"

    counters.llm_cache_miss += 1
    logger.info("llm cache MISS key=%s", key[:12])
    last_reason = "no attempts made"
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            client = _get_client()
            text = _call_model(client, model_name, system, user)
        except TranslateError:
            raise
        except Exception as exc:  # noqa: BLE001 — any SDK failure is retryable
            last_reason = f"sdk error: {exc!r}"
        else:
            if validator(text):
                storage.llm_cache_put(key, model_name, text)
                return text, "llm"
            last_reason = f"invalid reply (len={len(text)})"
        if attempt < _MAX_ATTEMPTS:
            _sleep(_BACKOFFS[attempt - 1])
    logger.warning("llm call failed after %d attempts (%s)", _MAX_ATTEMPTS, last_reason)
    raise TranslateError(f"llm call failed after {_MAX_ATTEMPTS} attempts ({last_reason})")


def _build_translate_prompt(
    unit_text: str,
    sentence: str,
    prev_sentence: str = "",
    next_sentence: str = "",
) -> str:
    """Compose the user-side prompt text sent to Gemini for translation.

    Always emits the same four-line layout — empty strings for missing
    neighbours — so the cache key is stable for identical contexts
    regardless of how the caller chose to represent "no neighbour". The
    model has been instructed to treat blank neighbour lines as unknown.
    """
    prev = (prev_sentence or "").strip()
    nxt = (next_sentence or "").strip()
    return f"Word: {unit_text}\n" f"Previous: {prev}\n" f"Sentence: {sentence}\n" f"Next: {nxt}"


def translate_one(
    unit_text: str,
    sentence: str,
    prev_sentence: str = "",
    next_sentence: str = "",
) -> tuple[str, str]:
    """Translate ``unit_text`` (in context) to Russian, with ± 1 sentence context.

    Returns ``(ru, source)`` where ``source`` is one of ``"cache"``,
    ``"llm"``, or ``"mock"`` — see :func:`_cached_llm_call`. The caller
    can forward this to the client so the UI can show whether a click
    bounced off the prompt-hash cache or hit Gemini.

    M19.1: the prompt includes the preceding and following sentence
    when available, so per-instance translation carries enough context
    for word-sense disambiguation. The result is cached by prompt hash
    in ``llm_cache``, so the same (word, 3-sentence window) is a free
    lookup on replay.

    Raises :class:`TranslateError` if Gemini fails three times with
    backoff, or the reply fails validation (empty, contains ``<``/``>``,
    multi-line, or longer than 60 characters).
    """
    logger.info(
        "translate request: unit=%r sentence=%r prev=%r next=%r",
        unit_text,
        sentence[:80],
        prev_sentence[:80] if prev_sentence else "",
        next_sentence[:80] if next_sentence else "",
    )
    user_prompt = _build_translate_prompt(unit_text, sentence, prev_sentence, next_sentence)
    started = time.monotonic()
    ru, source = _cached_llm_call(
        TRANSLATE_SYSTEM_PROMPT,
        user_prompt,
        validator=_is_valid_translation,
    )
    latency = time.monotonic() - started
    logger.info(
        "translate ok: unit=%r ru=%r source=%s latency=%.2fs",
        unit_text,
        ru,
        source,
        latency,
    )
    return ru, source


def _is_valid_json_card(text: str) -> bool:
    """Return True if ``text`` parses as a JSON object with the expected keys."""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(obj, dict):
        return False
    if "examples" not in obj:
        return False
    return True


def _strip_json_fences(text: str) -> str:
    """Tolerate a model that wraps its JSON in a ``` fence.

    We ask Gemini for bare JSON and the prompt is clear about it, but
    the model occasionally adds a ``` fence anyway. Peeling the fences
    here is cheaper than re-prompting.
    """
    t = text.strip()
    if t.startswith("```"):
        # Drop the opening fence + optional language tag line.
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def build_rich_card(
    unit_text: str,
    ru_translation: str,
    context_sentence: str,
) -> dict:
    """Build the M20.1 structured card: dictionary + Gemini translation layer.

    Flow:

    1. Look up ``unit_text`` in :func:`dictionary.fetch_entry` (open
       dictionaryapi.dev, cached in ``llm_cache``). When we get a hit we
       know the IPA, POS, canonical English definitions and a handful of
       example sentences.
    2. Ask Gemini for the Russian-language layer: translations of the
       definitions (in order), additional / translated example sentences
       (at least three, covering different situations), and a short
       usage note.  The prompt includes the dictionary data as context
       so the model's examples match the register.
    3. Merge both layers into a single JSON-serialisable dict.

    If the word isn't in the open dictionary (phrasal verb etc.) we
    still call Gemini with empty definition/example lists — it produces
    a card from scratch. The shape returned is identical to the
    dictionary-backed path, so the frontend has one render code-path.
    """
    lemma_entry = dictionary.fetch_entry(unit_text)
    if lemma_entry is None:
        # Try the stem without trailing -ed / -ing / -s so "drops" still
        # lands on "drop"'s dictionary entry.
        stem = re.sub(r"(s|es|ed|ing)$", "", unit_text.strip().lower())
        if stem and stem != unit_text.strip().lower():
            lemma_entry = dictionary.fetch_entry(stem)

    dict_payload = (
        {
            "word": lemma_entry.word,
            "ipa": lemma_entry.ipa,
            "audio_url": lemma_entry.audio_url,
            "meanings": [asdict(m) for m in lemma_entry.meanings],
            "synonyms": lemma_entry.synonyms,
        }
        if lemma_entry is not None
        else {
            "word": unit_text.strip().lower(),
            "ipa": "",
            "audio_url": "",
            "meanings": [],
            "synonyms": [],
        }
    )

    # Flatten the dict definitions + examples into the LLM prompt so the
    # model's output can align ``definitions_ru`` with the same order.
    flat_definitions = [d for m in dict_payload["meanings"] for d in m["definitions"]]
    flat_examples = [e for m in dict_payload["meanings"] for e in m["examples"]]

    user_prompt = (
        f"Word: {unit_text}\n"
        f"Russian translation: {ru_translation}\n"
        f"Context sentence: {context_sentence}\n"
        f"English definitions: {json.dumps(flat_definitions, ensure_ascii=False)}\n"
        f"Dictionary examples: {json.dumps(flat_examples, ensure_ascii=False)}"
    )
    logger.info("rich-card request: unit=%r has_dict=%s", unit_text, lemma_entry is not None)
    started = time.monotonic()
    try:
        raw, _source = _cached_llm_call(
            RICH_CARD_SYSTEM_PROMPT,
            user_prompt,
            validator=lambda t: _is_valid_json_card(_strip_json_fences(t)),
        )
    except TranslateError:
        # A total failure still produces a renderable card — just with
        # no Russian translations. Better than an empty ``card_json``.
        logger.warning("rich-card LLM failed for %r — returning dict-only payload", unit_text)
        return {
            "word": dict_payload["word"],
            "ipa": dict_payload["ipa"],
            "audio_url": dict_payload["audio_url"],
            "meanings": dict_payload["meanings"],
            "synonyms": dict_payload["synonyms"],
            "translation": ru_translation,
            "examples_ru": [],
            "usage_note_ru": "",
            "source": "dictionary-only" if lemma_entry else "none",
        }
    llm_card = json.loads(_strip_json_fences(raw))
    latency = time.monotonic() - started
    logger.info(
        "rich-card ok: unit=%r defs=%d examples=%d latency=%.2fs",
        unit_text,
        len(llm_card.get("definitions_ru", []) or []),
        len(llm_card.get("examples", []) or []),
        latency,
    )

    # Splice the LLM's Russian definitions back into the per-POS
    # meaning blocks, matching by position.
    defs_ru = list(llm_card.get("definitions_ru") or [])
    idx = 0
    for m in dict_payload["meanings"]:
        m["definitions_ru"] = []
        for _ in m["definitions"]:
            m["definitions_ru"].append(defs_ru[idx] if idx < len(defs_ru) else "")
            idx += 1

    return {
        "word": dict_payload["word"],
        "ipa": dict_payload["ipa"],
        "audio_url": dict_payload["audio_url"],
        "meanings": dict_payload["meanings"],
        "synonyms": dict_payload["synonyms"],
        "translation": ru_translation,
        "examples_ru": [
            {"en": ex.get("en", ""), "ru": ex.get("ru", "")}
            for ex in (llm_card.get("examples") or [])
            if isinstance(ex, dict) and ex.get("en")
        ],
        "usage_note_ru": (llm_card.get("usage_note_ru") or "").strip(),
        "source": "dictionary+llm" if lemma_entry is not None else "llm",
    }


_SIMPLIFY_SAME = "@SAME@"


def _is_valid_simplification(text: str) -> bool:
    """Return True iff ``text`` is a usable single-token simplification.

    ``@SAME@`` is the in-band sentinel meaning "input is already the
    simplest"; we accept it as valid so the cache can store a canonical
    "no-op" answer too.
    """
    if not text or not text.strip():
        return False
    if text.strip() == _SIMPLIFY_SAME:
        return True
    if "<" in text or ">" in text:
        return False
    if "\n" in text or "\r" in text:
        return False
    if len(text) > _MAX_SIMPLIFY_LEN:
        return False
    return True


def simplify_one(
    unit_text: str,
    sentence: str,
    prev_sentence: str = "",
    next_sentence: str = "",
) -> tuple[str | None, bool, str]:
    """Find the simplest English synonym for ``unit_text`` in context.

    Returns ``(simplified_text_or_None, is_simplest, source)``:

    * ``is_simplest=True`` ⇒ the input is already among the simplest
      common English words for its meaning; ``simplified_text_or_None``
      is ``None`` and the caller should NOT replace the span — just
      open the card. The sentinel is also persisted in ``llm_cache``
      so a repeat lookup is free.
    * ``is_simplest=False`` ⇒ ``simplified_text_or_None`` is the
      single-token simpler synonym, in the same grammatical form as
      the input. Caller drops it into the DOM in place of the original.

    ``source`` is one of ``"cache" | "llm" | "mock"`` — same semantics
    as :func:`translate_one`.
    """
    logger.info(
        "simplify request: unit=%r sentence=%r prev=%r next=%r",
        unit_text,
        sentence[:80],
        prev_sentence[:80] if prev_sentence else "",
        next_sentence[:80] if next_sentence else "",
    )
    user_prompt = _build_translate_prompt(unit_text, sentence, prev_sentence, next_sentence)
    started = time.monotonic()
    text, source = _cached_llm_call(
        SIMPLIFY_SYSTEM_PROMPT,
        user_prompt,
        validator=_is_valid_simplification,
    )
    latency = time.monotonic() - started
    text = text.strip()
    is_simplest = text == _SIMPLIFY_SAME
    logger.info(
        "simplify ok: unit=%r out=%r is_simplest=%s source=%s latency=%.2fs",
        unit_text,
        text,
        is_simplest,
        source,
        latency,
    )
    return (None if is_simplest else text), is_simplest, source


def generate_training_card(
    unit_text: str,
    ru_translation: str,
    context_sentence: str,
) -> str:
    """Build a Markdown SRS card for ``unit_text`` using ``context_sentence``.

    Runs against the same Gemini model as translation but with a distinct
    system prompt (see :data:`CARD_SYSTEM_PROMPT`). Goes through the
    prompt-hash cache, so a lemma seen in the same sentence context as
    an earlier user will reuse that card for free.

    Raises :class:`TranslateError` on total failure. The caller is
    expected to run this in the background and swallow the exception —
    a missing card is a graceful degradation.
    """
    user_prompt = (
        f"Word: {unit_text}\n"
        f"Russian translation: {ru_translation}\n"
        f"Context sentence: {context_sentence}"
    )
    logger.info("card request: unit=%r", unit_text)
    started = time.monotonic()
    card, _source = _cached_llm_call(
        CARD_SYSTEM_PROMPT,
        user_prompt,
        validator=_is_valid_card,
    )
    latency = time.monotonic() - started
    logger.info("card ok: unit=%r len=%d latency=%.2fs", unit_text, len(card), latency)
    return card
