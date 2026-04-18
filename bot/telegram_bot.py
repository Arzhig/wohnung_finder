from __future__ import annotations

import logging
from typing import Any

import requests

from shared.models import Listing


class TelegramNotifier:
    def __init__(self, token: str) -> None:
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"

    def format_listing(self, listing: Listing) -> str:
        return (
            f"[{listing.source.upper()}] {listing.title}\n"
            f"Address: {listing.address}\n"
            f"Rent: {listing.rent}\n"
            f"Size: {listing.size}\n"
            f"Rooms: {listing.rooms}\n"
            f"Link: {listing.link}"
        )

    def send_listing(self, chat_id: int, listing: Listing) -> None:
        message = self.format_listing(listing)
        self.send_text(chat_id, message, disable_web_page_preview=False)
        logging.info("Sent listing %s to chat %s", listing.unique_key, chat_id)

    def send_text(self, chat_id: int, text: str, disable_web_page_preview: bool = True) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        response = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=20)
        response.raise_for_status()

    def verify_token(self) -> str:
        response = requests.get(f"{self.base_url}/getMe", timeout=20)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError("Telegram getMe returned not ok")
        result = payload.get("result") or {}
        username = result.get("username")
        if username:
            return str(username)
        return "<unknown>"
