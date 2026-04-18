from __future__ import annotations

import argparse
import logging
import threading
import time

from bot.command_bot import TelegramCommandBot
from bot.telegram_bot import TelegramNotifier
from config import load_config
from crawl_policy import CrawlPolicy
from database import Database
from scrapers import (
    DegewoScraper,
    GESOBAUScraper,
    GEWOBAGScraper,
    HOWOGEScraper,
    StadtUndLandScraper,
    WBMScraper,
)


def _build_scrapers(crawl_policy: CrawlPolicy, timeout_seconds: int):
    return {
        "wbm": WBMScraper(crawl_policy=crawl_policy, timeout_seconds=timeout_seconds),
        "howoge": HOWOGEScraper(crawl_policy=crawl_policy, timeout_seconds=timeout_seconds),
        "gesobau": GESOBAUScraper(crawl_policy=crawl_policy, timeout_seconds=timeout_seconds),
        "gewobag": GEWOBAGScraper(crawl_policy=crawl_policy, timeout_seconds=timeout_seconds),
        "stadt_und_land": StadtUndLandScraper(crawl_policy=crawl_policy, timeout_seconds=timeout_seconds),
        "degewo": DegewoScraper(crawl_policy=crawl_policy, timeout_seconds=timeout_seconds),
    }


def _run_startup_checks(notifier: TelegramNotifier, db: Database, enabled: list[str]) -> None:
    logging.info("Running startup checks...")

    bot_username = notifier.verify_token()
    logging.info("Telegram token is valid for bot: @%s", bot_username)

    # Force a quick database read to validate file access and schema initialization.
    db.bootstrap_default_subscribers([], enabled)
    logging.info("Database is reachable and initialized")

    if "wbm" in enabled:
        logging.info("WBM scraper is enabled")
    else:
        logging.warning("WBM scraper is not enabled")

    placeholder_sources = [
        company
        for company in enabled
        if company in {"howoge", "gesobau", "gewobag", "stadt_und_land", "degewo"}
    ]
    if placeholder_sources:
        logging.warning(
            "These providers are enabled but still placeholders: %s",
            ", ".join(placeholder_sources),
        )

    logging.info("Startup checks passed")


def run(check_only: bool = False) -> None:
    config = load_config()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    crawl_policy = CrawlPolicy(config.crawl_policy)
    db = Database(config.database_path)
    notifier = TelegramNotifier(config.telegram_bot_token)
    scrapers = _build_scrapers(crawl_policy, config.request_timeout_seconds)

    enabled = [company for company in config.enabled_companies if company in scrapers]
    if not enabled:
        raise ValueError("No valid companies are enabled in ENABLED_COMPANIES")

    _run_startup_checks(notifier, db, enabled)
    if check_only:
        logging.info("Check mode complete. Exiting without starting monitoring loop.")
        return

    db.bootstrap_default_subscribers(config.telegram_chat_ids, enabled)

    stop_event = threading.Event()
    command_bot = TelegramCommandBot(config.telegram_bot_token, db, enabled)
    command_thread = threading.Thread(
        target=command_bot.run_forever,
        args=(stop_event,),
        daemon=True,
        name="telegram-command-worker",
    )
    command_thread.start()

    logging.info("Starting apartment monitor for companies: %s", ", ".join(enabled))

    try:
        while True:
            for company in enabled:
                scraper = scrapers[company]
                try:
                    listings = scraper.scrape()
                except Exception as exc:
                    logging.exception("Scraper '%s' failed: %s", company, exc)
                    continue

                new_count = 0
                for listing in listings:
                    is_new_listing = db.upsert_listing(listing)
                    if not is_new_listing:
                        continue

                    new_count += 1
                    target_chat_ids = db.get_target_chat_ids_for_listing(listing)
                    for chat_id in target_chat_ids:
                        if db.was_sent(chat_id, listing):
                            continue
                        try:
                            notifier.send_listing(chat_id, listing)
                            db.mark_sent(chat_id, listing)
                        except Exception as exc:
                            logging.exception(
                                "Failed to send listing '%s' to chat '%s': %s",
                                listing.unique_key,
                                chat_id,
                                exc,
                            )

                logging.info("Source '%s' produced %s new listings", company, new_count)

            time.sleep(config.loop_sleep_seconds)
    finally:
        stop_event.set()
        command_thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wohnung finder bot runner")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run startup checks and exit",
    )
    args = parser.parse_args()
    run(check_only=args.check)


