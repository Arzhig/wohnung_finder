from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Iterable

import requests

from bot.telegram_bot import TelegramNotifier
from database import Database


@dataclass(frozen=True)
class CommandContext:
    enabled_companies: set[str]


class TelegramCommandBot:
    def __init__(
        self,
        token: str,
        database: Database,
        enabled_companies: Iterable[str],
    ) -> None:
        self.database = database
        self.notifier = TelegramNotifier(token)
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.offset = 0
        self.context = CommandContext(enabled_companies=set(enabled_companies))

    def run_forever(self, stop_event: threading.Event) -> None:
        logging.info("Telegram command worker started")
        while not stop_event.is_set():
            try:
                updates = self._poll_updates(timeout_seconds=20)
                for update in updates:
                    self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
                    self._handle_update(update)
            except Exception as exc:
                logging.exception("Command worker polling failed: %s", exc)

    def _poll_updates(self, timeout_seconds: int) -> list[dict]:
        payload = {
            "offset": self.offset,
            "timeout": timeout_seconds,
        }
        response = requests.get(f"{self.base_url}/getUpdates", params=payload, timeout=timeout_seconds + 10)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            return []
        result = data.get("result", [])
        if isinstance(result, list):
            return result
        return []

    def _handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        user = message.get("from") or {}

        if not text.startswith("/"):
            return

        chat_id_raw = chat.get("id")
        if chat_id_raw is None:
            return

        chat_id = int(chat_id_raw)
        username = user.get("username")
        self.database.register_user(chat_id, username)

        command, _, argument_line = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        argument_line = argument_line.strip()

        if command == "/start":
            self._cmd_start(chat_id)
            return
        if command == "/status":
            self._cmd_status(chat_id)
            return
        if command == "/subscribe":
            self._cmd_subscribe(chat_id, argument_line)
            return
        if command == "/unsubscribe":
            self._cmd_unsubscribe(chat_id, argument_line)
            return
        if command == "/filters":
            self._cmd_filters(chat_id, argument_line)
            return

        self.notifier.send_text(chat_id, self._help_text())

    def _cmd_start(self, chat_id: int) -> None:
        for company in self.context.enabled_companies:
            self.database.subscribe(chat_id, company)
        self.notifier.send_text(chat_id, self._welcome_text())

    def _cmd_status(self, chat_id: int) -> None:
        subscriptions = self.database.list_subscriptions(chat_id)
        max_rent, min_size, min_rooms = self.database.get_filters(chat_id)

        filter_lines = [
            f"max_rent={max_rent if max_rent is not None else '-'}",
            f"min_size={min_size if min_size is not None else '-'}",
            f"min_rooms={min_rooms if min_rooms is not None else '-'}",
        ]

        message = (
            "Your current settings:\n"
            f"Subscriptions: {', '.join(subscriptions) if subscriptions else 'none'}\n"
            f"Filters: {', '.join(filter_lines)}"
        )
        self.notifier.send_text(chat_id, message)

    def _cmd_subscribe(self, chat_id: int, argument_line: str) -> None:
        value = argument_line.lower().strip()
        if not value:
            self.notifier.send_text(chat_id, "Usage: /subscribe <company|all>")
            return

        if value == "all":
            for company in self.context.enabled_companies:
                self.database.subscribe(chat_id, company)
            self.notifier.send_text(chat_id, "Subscribed to all companies.")
            return

        if value not in self.context.enabled_companies:
            self.notifier.send_text(chat_id, f"Unknown company '{value}'.")
            return

        self.database.subscribe(chat_id, value)
        self.notifier.send_text(chat_id, f"Subscribed to {value}.")

    def _cmd_unsubscribe(self, chat_id: int, argument_line: str) -> None:
        value = argument_line.lower().strip()
        if not value:
            self.notifier.send_text(chat_id, "Usage: /unsubscribe <company|all>")
            return

        if value == "all":
            self.database.clear_subscriptions(chat_id)
            self.notifier.send_text(chat_id, "Unsubscribed from all companies.")
            return

        if value not in self.context.enabled_companies:
            self.notifier.send_text(chat_id, f"Unknown company '{value}'.")
            return

        self.database.unsubscribe(chat_id, value)
        self.notifier.send_text(chat_id, f"Unsubscribed from {value}.")

    def _cmd_filters(self, chat_id: int, argument_line: str) -> None:
        line = argument_line.strip()
        if not line:
            self.notifier.send_text(
                chat_id,
                "Usage: /filters max_rent=<number> min_size=<number> min_rooms=<number> or /filters clear",
            )
            return

        if line.lower() == "clear":
            self.database.clear_filters(chat_id)
            self.notifier.send_text(chat_id, "Filters cleared.")
            return

        parsed = self._parse_filters(line)
        if parsed is None:
            self.notifier.send_text(
                chat_id,
                "Invalid filter syntax. Example: /filters max_rent=900 min_size=45 min_rooms=2",
            )
            return

        max_rent, min_size, min_rooms = parsed
        self.database.set_filters(chat_id, max_rent, min_size, min_rooms)
        self.notifier.send_text(chat_id, "Filters updated.")

    def _parse_filters(self, line: str) -> tuple[float | None, float | None, float | None] | None:
        max_rent = None
        min_size = None
        min_rooms = None

        pairs = [piece.strip() for piece in line.split(" ") if piece.strip()]
        for pair in pairs:
            if "=" not in pair:
                return None
            key, value = pair.split("=", 1)
            key = key.strip().lower()
            value = value.strip().replace(",", ".")
            try:
                numeric = float(value)
            except ValueError:
                return None

            if key == "max_rent":
                max_rent = numeric
            elif key == "min_size":
                min_size = numeric
            elif key == "min_rooms":
                min_rooms = numeric
            else:
                return None

        return (max_rent, min_size, min_rooms)

    def _welcome_text(self) -> str:
        return (
            "Welcome to wohnung_finder.\n"
            "You are subscribed to all currently enabled companies.\n\n"
            "Commands:\n"
            "/status\n"
            "/subscribe <company|all>\n"
            "/unsubscribe <company|all>\n"
            "/filters max_rent=<n> min_size=<n> min_rooms=<n>\n"
            "/filters clear"
        )

    def _help_text(self) -> str:
        return (
            "Unknown command. Available commands:\n"
            "/start\n"
            "/status\n"
            "/subscribe <company|all>\n"
            "/unsubscribe <company|all>\n"
            "/filters max_rent=<n> min_size=<n> min_rooms=<n>\n"
            "/filters clear"
        )
