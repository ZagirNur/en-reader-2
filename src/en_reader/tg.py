"""Telegram Mini-App integration (M18.1).

Two responsibilities:

1. **Verify ``initData`` strings** sent from the Telegram WebView. Telegram
   signs each init string with an HMAC-SHA256 derived from the bot token,
   so the origin (us) can cryptographically trust the contained ``user``
   object without any round-trip back to Telegram.

2. **Talk to the Bot API** for outbound calls we need on our side:
   ``setWebhook`` (registered once at app startup so updates flow to us
   instead of us long-polling), ``setChatMenuButton`` (plants the
   "Open App" button in every chat with the bot), and ``sendMessage``
   (the /start reply).

The bot token lives in ``.env`` only — never logged, never committed, never
echoed. Callers pass it explicitly; nothing in this module reads the
process environment on import so an accidental `import tg` in test code
doesn't panic when the variable is absent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TG_API = "https://api.telegram.org"


class InvalidInitDataError(Exception):
    """Raised when ``init_data`` fails HMAC verification or parses wrong."""


@dataclass
class TelegramUser:
    """Subset of Telegram's ``User`` object we actually care about."""

    id: int
    username: str | None
    first_name: str | None
    last_name: str | None


def verify_init_data(init_data: str, bot_token: str) -> TelegramUser:
    """Verify a ``Telegram.WebApp.initData`` string and return the user.

    Telegram's algorithm (docs: `telegram.org/js/telegram-web-app.js`):

    1. Parse the querystring. Pull ``hash`` out, join the rest as
       ``key=value`` lines sorted alphabetically — this is the
       "data-check-string".
    2. Derive ``secret_key = HMAC_SHA256("WebAppData", bot_token)``.
    3. Expected hash = ``HMAC_SHA256(secret_key, data_check_string)`` hex.
    4. Constant-time-compare the expected hash to the one the client sent.
    5. If the hash matches, the ``user`` key decodes to a JSON user
       object we can trust.

    Any deviation from the happy path — wrong hash, missing field, wrong
    types — raises :class:`InvalidInitDataError`. Callers should treat it
    as a 401.
    """
    if not init_data or not bot_token:
        raise InvalidInitDataError("empty init_data or bot_token")
    parsed = urllib.parse.parse_qs(init_data, keep_blank_values=True, strict_parsing=False)
    # parse_qs returns lists — flatten to single values (Telegram never
    # sends duplicate keys).
    flat: dict[str, str] = {k: v[0] for k, v in parsed.items()}
    client_hash = flat.pop("hash", None)
    if not client_hash:
        raise InvalidInitDataError("missing hash")
    pairs = [f"{k}={flat[k]}" for k in sorted(flat.keys())]
    data_check_string = "\n".join(pairs)
    secret_key = hmac.new(
        key=b"WebAppData", msg=bot_token.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        key=secret_key, msg=data_check_string.encode("utf-8"), digestmod=hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, client_hash):
        raise InvalidInitDataError("hash mismatch")

    user_blob = flat.get("user")
    if not user_blob:
        raise InvalidInitDataError("missing user")
    try:
        user_obj = json.loads(user_blob)
    except json.JSONDecodeError as e:
        raise InvalidInitDataError(f"user not JSON: {e}") from e
    tg_id = user_obj.get("id")
    if not isinstance(tg_id, int):
        raise InvalidInitDataError("user.id not int")
    return TelegramUser(
        id=int(tg_id),
        username=user_obj.get("username"),
        first_name=user_obj.get("first_name"),
        last_name=user_obj.get("last_name"),
    )


# ---------- bot API client ----------


def _call(bot_token: str, method: str, payload: dict) -> dict:
    """POST ``payload`` to the Telegram Bot API and return the parsed body.

    Timeouts short because the webhook handler runs inline with request
    processing — we must not block the HTTP reply for more than a few
    hundred ms. Errors bubble up as ``RuntimeError`` so the caller can
    choose to swallow or escalate.
    """
    url = f"{TG_API}/bot{bot_token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        body = json.loads(resp.read())
    if not body.get("ok"):
        raise RuntimeError(f"tg API {method} failed: {body}")
    return body.get("result", {})


def set_webhook(bot_token: str, webhook_url: str, secret_token: str | None = None) -> None:
    """Register the webhook URL. Idempotent — Telegram overwrites the prior one."""
    payload: dict = {
        "url": webhook_url,
        # M18.4: callback_query updates are how the link-conflict
        # inline-keyboard choice reaches us.
        "allowed_updates": ["message", "callback_query"],
    }
    if secret_token:
        payload["secret_token"] = secret_token
    _call(bot_token, "setWebhook", payload)
    logger.info("telegram webhook registered at %s", webhook_url)


def set_chat_menu_button(bot_token: str, webapp_url: str, label: str = "Открыть") -> None:
    """Plant an "Open App" button in every chat with the bot.

    This is the button users tap in the Telegram client next to the
    message input — cleaner than requiring /start → inline button every
    time. Idempotent.
    """
    _call(
        bot_token,
        "setChatMenuButton",
        {"menu_button": {"type": "web_app", "text": label, "web_app": {"url": webapp_url}}},
    )


def send_start_reply(bot_token: str, chat_id: int, webapp_url: str) -> None:
    """Reply to /start with a button that opens the Mini App in-app.

    The ``web_app`` button type makes Telegram open the URL inside the
    chat (not the mobile browser), so ``Telegram.WebApp.initData``
    populates on first paint and /auth/telegram fires automatically.
    """
    _call(
        bot_token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": "Привет! Открой приложение — читай английские книги с переводом по тапу.",
            "reply_markup": {
                "inline_keyboard": [[{"text": "Открыть en-reader", "web_app": {"url": webapp_url}}]]
            },
        },
    )


# ---------- M18.4: link flow helpers ----------


def send_plain(bot_token: str, chat_id: int, text: str) -> dict:
    """Send a plain text message — the link flow uses this for success /
    already-linked / expired confirmations that don't need buttons."""
    return _call(bot_token, "sendMessage", {"chat_id": chat_id, "text": text})


def send_link_choice(
    bot_token: str,
    chat_id: int,
    token: str,
    dest_summary: str,
    src_summary: str,
) -> dict:
    """Ask the user which account to keep when both sides have data.

    Two buttons carrying ``callback_data`` encoding the token and the
    direction. The webhook callback_query handler routes on that string.
    We include short per-account summaries in the body so the user sees
    *why* the merge has to discard one side. Telegram limits
    ``callback_data`` to 64 bytes, hence the short prefix + base-urlsafe
    token (safe well under the cap).
    """
    text = (
        "У тебя уже есть en-reader аккаунт на этом Telegram. "
        "Какой оставить?\n\n"
        f"Текущий (email): {dest_summary}\n"
        f"Telegram: {src_summary}\n\n"
        "Данные второго аккаунта перенесутся в выбранный."
    )
    return _call(
        bot_token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {"text": "Оставить текущий", "callback_data": f"lk:{token}:dest"},
                        {"text": "Оставить Telegram", "callback_data": f"lk:{token}:src"},
                    ]
                ]
            },
        },
    )


def answer_callback(bot_token: str, callback_query_id: str, text: str = "") -> None:
    """Dismiss the spinner on the inline button Telegram shows mid-click.

    Always fire this on the server side even if the work takes longer —
    Telegram times out the client-side spinner at ~10 s and shows an
    ugly "error". We keep ``text`` short because it pops as a toast.
    """
    _call(
        bot_token,
        "answerCallbackQuery",
        {"callback_query_id": callback_query_id, "text": text[:200]},
    )


def edit_message(bot_token: str, chat_id: int, message_id: int, text: str) -> None:
    """Replace an earlier keyboard message with a final resolution line.

    Removing the keyboard (by sending a new text without ``reply_markup``)
    keeps a user from clicking a stale choice twice.
    """
    _call(
        bot_token,
        "editMessageText",
        {"chat_id": chat_id, "message_id": message_id, "text": text},
    )
