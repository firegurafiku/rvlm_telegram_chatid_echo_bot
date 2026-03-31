#!/usr/bin/env python3
"""Simple Telegram bot for chat_id discovery.

The bot polls Telegram's getUpdates endpoint and replies with the chat_id
for every command message (messages whose text starts with '/').
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from typing import Any
from urllib import error, parse, request

POLL_TIMEOUT_SECONDS = 30
RETRY_DELAY_SECONDS = 3

_MARKDOWN_V2_SPECIAL = frozenset(r"_*[]()~`>#+-=|{}.!")


def _escape_markdown_v2(text: str) -> str:
    return "".join(f"\\{c}" if c in _MARKDOWN_V2_SPECIAL else c for c in text)


def _build_api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _telegram_get(token: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    query = parse.urlencode(params)
    url = f"{_build_api_url(token, method)}?{query}"
    req = request.Request(url, method="GET")

    with request.urlopen(req, timeout=POLL_TIMEOUT_SECONDS + 5) as resp:
        payload = resp.read().decode("utf-8")

    data = json.loads(payload)
    if not isinstance(data, dict) or not data.get("ok"):
        raise RuntimeError(f"Telegram API call failed for {method}: {data}")
    return data


def _telegram_post(token: str, method: str, body: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(body).encode("utf-8")
    req = request.Request(
        _build_api_url(token, method),
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    with request.urlopen(req, timeout=15) as resp:
        payload = resp.read().decode("utf-8")

    data = json.loads(payload)
    if not isinstance(data, dict) or not data.get("ok"):
        raise RuntimeError(f"Telegram API call failed for {method}: {data}")
    return data


def _is_command_message(update: dict[str, Any]) -> bool:
    message = update.get("message")
    if not isinstance(message, dict):
        return False

    text = message.get("text")
    return isinstance(text, str) and text.startswith("/")


def _extract_chat_id(update: dict[str, Any]) -> int | str | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None

    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None

    return chat.get("id")


def _poll_updates(token: str, offset: int | None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "timeout": POLL_TIMEOUT_SECONDS,
        "allowed_updates": json.dumps(["message"]),
    }
    if offset is not None:
        params["offset"] = offset

    data = _telegram_get(token, "getUpdates", params)
    results = data.get("result", [])
    if not isinstance(results, list):
        raise RuntimeError(f"Unexpected getUpdates payload: {data}")

    return [item for item in results if isinstance(item, dict)]


def _reply_with_chat_id(token: str, chat_id: int | str) -> None:
    escaped_id = _escape_markdown_v2(str(chat_id))
    msg = f"This chat's `chat_id` is: {escaped_id}"
    _telegram_post(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "parse_mode": "MarkdownV2",
            "text": msg,
        },
    )


def run() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")

    signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(0))

    print("Bot is running: polling Telegram getUpdates", flush=True)
    next_offset: int | None = None

    while True:
        try:
            updates = _poll_updates(token, next_offset)

            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    next_offset = update_id + 1

                if not _is_command_message(update):
                    continue

                chat_id = _extract_chat_id(update)
                if chat_id is None:
                    continue

                _reply_with_chat_id(token, chat_id)

        except KeyboardInterrupt:
            print("Stopping bot...", flush=True)
            return
        except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            print(f"Recoverable error: {exc}", file=sys.stderr, flush=True)
            time.sleep(RETRY_DELAY_SECONDS)


def main() -> int:
    try:
        run()
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
