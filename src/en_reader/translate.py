"""Gemini-backed English-to-Russian translation for en-reader.

Single public entry point: :func:`translate_one`. Callers pass the unit
(word or short phrase) and the full sentence it appears in; the function
returns a short Russian translation or raises :class:`TranslateError`.

Validation, retries (with exponential backoff), and logging are handled here.
No caching — that arrives in M6.1.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from google import genai

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a professional English-to-Russian literary translator.
You receive a single English word or short phrase and the sentence it appears in.
Return ONLY the best Russian translation of the word/phrase, in context.
Rules:
- One short translation, no variants, no explanations.
- Preserve capitalization (lowercase common words, Title Case for proper nouns).
- For a phrasal verb given as a whole (e.g. "look up"), return a single Russian verb or expression.
- If the phrase is the verb part of a split phrasal verb (particle is elsewhere in the sentence),
  still return the full Russian translation including what the particle contributes.
- No punctuation except what belongs to the translation. No quotes, no parentheses.
- Max 60 characters."""


_MAX_ATTEMPTS = 3
_BACKOFFS = (0.5, 1.0, 2.0)
_MAX_LEN = 60

# Lazy module-level Gemini client; initialized on first call.
_client: genai.Client | None = None


class TranslateError(Exception):
    """Raised when all attempts to obtain a valid translation fail."""


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


def _is_valid(text: str) -> bool:
    """Return True if ``text`` is a plausible single-line translation."""
    if not text or not text.strip():
        return False
    if "<" in text or ">" in text:
        return False
    if "\n" in text or "\r" in text:
        return False
    if len(text) > _MAX_LEN:
        return False
    return True


def _call_model(client: Any, model_name: str, user_prompt: str) -> str:
    resp = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config={"system_instruction": SYSTEM_PROMPT, "temperature": 0.2},
    )
    return (resp.text or "").strip()


def translate_one(unit_text: str, sentence: str) -> str:
    """Translate ``unit_text`` (in context of ``sentence``) to Russian.

    Attempts up to 3 calls with exponential backoff between failures.
    A failure is either an SDK exception or a reply that fails validation
    (empty, contains ``<``/``>``, multi-line, or longer than 60 characters).

    Raises :class:`TranslateError` if no attempt succeeds.

    .. note::
       When the environment variable ``E2E_MOCK_LLM`` is set to ``"1"`` this
       function short-circuits to ``f"RU:{unit_text}"`` without contacting
       Gemini or running the retry loop. The hook is used exclusively by
       Playwright E2E tests (see :mod:`tests.e2e.conftest`) so browser
       flows remain deterministic and offline.
    """
    # M15.6: E2E tests stub the Gemini call entirely via this env var.
    # Keep the check above the retry loop so the mock path doesn't pay
    # backoff/sleep costs, and the return is byte-stable for assertions.
    if os.environ.get("E2E_MOCK_LLM") == "1":
        return f"RU:{unit_text}"

    logger.info("translate request: unit=%r sentence=%r", unit_text, sentence[:100])

    user_prompt = f"Word: {unit_text}\nSentence: {sentence}"
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

    started = time.monotonic()
    last_reason = "no attempts made"

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            client = _get_client()
            text = _call_model(client, model_name, user_prompt)
        except TranslateError:
            # Missing API key etc. — no point retrying.
            raise
        except Exception as exc:  # noqa: BLE001 — any SDK failure is retryable
            last_reason = f"sdk error: {exc!r}"
        else:
            if _is_valid(text):
                latency = time.monotonic() - started
                logger.info(
                    "translate ok: unit=%r ru=%r latency=%.2fs attempts=%d",
                    unit_text,
                    text,
                    latency,
                    attempt,
                )
                return text
            last_reason = f"invalid reply (len={len(text)})"

        if attempt < _MAX_ATTEMPTS:
            _sleep(_BACKOFFS[attempt - 1])

    logger.warning("translate failed after %d attempts: unit=%r", _MAX_ATTEMPTS, unit_text)
    raise TranslateError(f"translate_one failed after {_MAX_ATTEMPTS} attempts ({last_reason})")
