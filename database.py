from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterable, List

from shared.models import Listing


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS listings (
                    unique_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    listing_id TEXT,
                    title TEXT NOT NULL,
                    address TEXT NOT NULL,
                    rent TEXT NOT NULL,
                    size TEXT NOT NULL,
                    rooms TEXT NOT NULL,
                    link TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    username TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    chat_id INTEGER NOT NULL,
                    company TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, company),
                    FOREIGN KEY (chat_id) REFERENCES users(chat_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_filters (
                    chat_id INTEGER PRIMARY KEY,
                    max_rent REAL,
                    min_size REAL,
                    min_rooms REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (chat_id) REFERENCES users(chat_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_notifications (
                    chat_id INTEGER NOT NULL,
                    listing_unique_key TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, listing_unique_key)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_subscriptions_company
                ON subscriptions(company)
                """
            )
            conn.commit()

    def bootstrap_default_subscribers(self, chat_ids: Iterable[int], companies: Iterable[str]) -> None:
        company_list = [company for company in companies]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for chat_id in chat_ids:
                conn.execute(
                    """
                    INSERT INTO users (chat_id, is_active)
                    VALUES (?, 1)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        is_active = 1,
                        last_seen_at = CURRENT_TIMESTAMP
                    """,
                    (chat_id,),
                )
                for company in company_list:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO subscriptions (chat_id, company)
                        VALUES (?, ?)
                        """,
                        (chat_id, company),
                    )
            conn.commit()

    def register_user(self, chat_id: int, username: str | None = None) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO users (chat_id, username, is_active)
                VALUES (?, ?, 1)
                ON CONFLICT(chat_id) DO UPDATE SET
                    username = COALESCE(excluded.username, users.username),
                    is_active = 1,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (chat_id, username),
            )
            conn.commit()

    def subscribe(self, chat_id: int, company: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO subscriptions (chat_id, company)
                VALUES (?, ?)
                """,
                (chat_id, company),
            )
            conn.commit()

    def unsubscribe(self, chat_id: int, company: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                DELETE FROM subscriptions
                WHERE chat_id = ? AND company = ?
                """,
                (chat_id, company),
            )
            conn.commit()

    def clear_subscriptions(self, chat_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                DELETE FROM subscriptions
                WHERE chat_id = ?
                """,
                (chat_id,),
            )
            conn.commit()

    def set_filters(
        self,
        chat_id: int,
        max_rent: float | None,
        min_size: float | None,
        min_rooms: float | None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO user_filters (chat_id, max_rent, min_size, min_rooms, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id) DO UPDATE SET
                    max_rent = excluded.max_rent,
                    min_size = excluded.min_size,
                    min_rooms = excluded.min_rooms,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (chat_id, max_rent, min_size, min_rooms),
            )
            conn.commit()

    def clear_filters(self, chat_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                DELETE FROM user_filters
                WHERE chat_id = ?
                """,
                (chat_id,),
            )
            conn.commit()

    def list_subscriptions(self, chat_id: int) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT company
                FROM subscriptions
                WHERE chat_id = ?
                ORDER BY company
                """,
                (chat_id,),
            )
            return [str(row[0]) for row in cursor.fetchall()]

    def get_filters(self, chat_id: int) -> tuple[float | None, float | None, float | None]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT max_rent, min_size, min_rooms
                FROM user_filters
                WHERE chat_id = ?
                LIMIT 1
                """,
                (chat_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return (None, None, None)
            return (row[0], row[1], row[2])

    def upsert_listing(self, listing: Listing) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO listings (
                    unique_key, source, listing_id, title, address, rent, size, rooms, link
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    listing.unique_key,
                    listing.source,
                    listing.listing_id,
                    listing.title,
                    listing.address,
                    listing.rent,
                    listing.size,
                    listing.rooms,
                    listing.link,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_target_chat_ids_for_listing(self, listing: Listing) -> List[int]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT u.chat_id, f.max_rent, f.min_size, f.min_rooms
                FROM users u
                INNER JOIN subscriptions s
                    ON s.chat_id = u.chat_id
                LEFT JOIN user_filters f
                    ON f.chat_id = u.chat_id
                WHERE u.is_active = 1
                  AND s.company = ?
                """,
                (listing.source,),
            )
            rows = cursor.fetchall()

        targets: List[int] = []
        for row in rows:
            chat_id, max_rent, min_size, min_rooms = row
            if self._matches_filters(listing, max_rent, min_size, min_rooms):
                targets.append(int(chat_id))

        return targets

    def was_sent(self, chat_id: int, listing: Listing) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT 1
                FROM sent_notifications
                WHERE chat_id = ? AND listing_unique_key = ?
                LIMIT 1
                """,
                (chat_id, listing.unique_key),
            )
            return cursor.fetchone() is not None

    def mark_sent(self, chat_id: int, listing: Listing) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sent_notifications (chat_id, listing_unique_key)
                VALUES (?, ?)
                """,
                (chat_id, listing.unique_key),
            )
            conn.commit()

    def _matches_filters(
        self,
        listing: Listing,
        max_rent: float | None,
        min_size: float | None,
        min_rooms: float | None,
    ) -> bool:
        rent_value = self._extract_numeric_value(listing.rent)
        size_value = self._extract_numeric_value(listing.size)
        rooms_value = self._extract_numeric_value(listing.rooms)

        if max_rent is not None and rent_value is not None and rent_value > max_rent:
            return False
        if min_size is not None and size_value is not None and size_value < min_size:
            return False
        if min_rooms is not None and rooms_value is not None and rooms_value < min_rooms:
            return False
        return True

    def _extract_numeric_value(self, text: str) -> float | None:
        numeric = re.sub(r"[^0-9,\.]+", "", text or "")
        if not numeric:
            return None

        if "," in numeric and "." in numeric:
            if numeric.rfind(",") > numeric.rfind("."):
                normalized = numeric.replace(".", "").replace(",", ".")
            else:
                normalized = numeric.replace(",", "")
        elif "," in numeric:
            normalized = numeric.replace(".", "").replace(",", ".")
        else:
            normalized = numeric

        try:
            return float(normalized)
        except ValueError:
            return None
