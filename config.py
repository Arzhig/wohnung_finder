from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

from dotenv import load_dotenv


@dataclass(frozen=True)
class CrawlPolicyConfig:
    max_calls_per_minute: int
    delay_mean_seconds: float
    delay_std_seconds: float
    delay_min_seconds: float
    delay_max_seconds: float
    quiet_hours_start: int
    quiet_hours_end: int
    timezone: str


@dataclass(frozen=True)
class AppConfig:
    telegram_bot_token: str
    telegram_chat_ids: List[int]
    enabled_companies: List[str]
    request_timeout_seconds: int
    loop_sleep_seconds: int
    database_path: Path
    crawl_policy: CrawlPolicyConfig


def _parse_csv(raw_value: str) -> List[str]:
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _parse_chat_ids(raw_value: str) -> List[int]:
    chat_ids: List[int] = []
    for value in _parse_csv(raw_value):
        try:
            chat_ids.append(int(value))
        except ValueError as exc:
            raise ValueError(f"Invalid TELEGRAM_CHAT_IDS value: {value}") from exc
    return chat_ids


def load_config() -> AppConfig:
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    chat_ids_raw = os.getenv("TELEGRAM_CHAT_IDS", "").strip()
    if not chat_ids_raw:
        raise ValueError("TELEGRAM_CHAT_IDS is required")

    enabled_companies_raw = os.getenv(
        "ENABLED_COMPANIES",
        "wbm,howoge,gesobau,gewobag,stadt_und_land,degewo",
    )

    request_timeout_seconds = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "15"))
    loop_sleep_seconds = int(os.getenv("LOOP_SLEEP_SECONDS", "10"))
    database_path = Path(os.getenv("DATABASE_PATH", "data/listings.db"))

    crawl_policy = CrawlPolicyConfig(
        max_calls_per_minute=int(os.getenv("CRAWL_MAX_CALLS_PER_MINUTE", "2")),
        delay_mean_seconds=float(os.getenv("CRAWL_DELAY_MEAN_SECONDS", "35")),
        delay_std_seconds=float(os.getenv("CRAWL_DELAY_STD_SECONDS", "10")),
        delay_min_seconds=float(os.getenv("CRAWL_DELAY_MIN_SECONDS", "20")),
        delay_max_seconds=float(os.getenv("CRAWL_DELAY_MAX_SECONDS", "70")),
        quiet_hours_start=int(os.getenv("QUIET_HOURS_START", "0")),
        quiet_hours_end=int(os.getenv("QUIET_HOURS_END", "6")),
        timezone=os.getenv("TIMEZONE", "Europe/Berlin"),
    )

    if crawl_policy.max_calls_per_minute > 2:
        raise ValueError("CRAWL_MAX_CALLS_PER_MINUTE must be <= 2")

    if crawl_policy.delay_min_seconds > crawl_policy.delay_max_seconds:
        raise ValueError("CRAWL_DELAY_MIN_SECONDS must be <= CRAWL_DELAY_MAX_SECONDS")

    return AppConfig(
        telegram_bot_token=bot_token,
        telegram_chat_ids=_parse_chat_ids(chat_ids_raw),
        enabled_companies=_parse_csv(enabled_companies_raw),
        request_timeout_seconds=request_timeout_seconds,
        loop_sleep_seconds=loop_sleep_seconds,
        database_path=database_path,
        crawl_policy=crawl_policy,
    )
