from __future__ import annotations

import argparse
import logging
import random
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


def _build_scrapers(timeout_seconds: int, config):
    # Keep one crawl policy instance per crawler so rate limits apply per source.
    wbm_policy = CrawlPolicy(config.crawl_policy)
    howoge_policy = CrawlPolicy(config.crawl_policy)
    gesobau_policy = CrawlPolicy(config.crawl_policy)
    gewobag_policy = CrawlPolicy(config.crawl_policy)
    stadt_und_land_policy = CrawlPolicy(config.crawl_policy)
    degewo_policy = CrawlPolicy(config.crawl_policy)

    return {
        "wbm": WBMScraper(crawl_policy=wbm_policy, timeout_seconds=timeout_seconds),
        "howoge": HOWOGEScraper(crawl_policy=howoge_policy, timeout_seconds=timeout_seconds),
        "gesobau": GESOBAUScraper(crawl_policy=gesobau_policy, timeout_seconds=timeout_seconds),
        "gewobag": GEWOBAGScraper(crawl_policy=gewobag_policy, timeout_seconds=timeout_seconds),
        "stadt_und_land": StadtUndLandScraper(crawl_policy=stadt_und_land_policy, timeout_seconds=timeout_seconds),
        "degewo": DegewoScraper(
            crawl_policy=degewo_policy,
            timeout_seconds=timeout_seconds,
            inter_page_delay_min_seconds=config.degewo_inter_page_delay_min_seconds,
            inter_page_delay_max_seconds=config.degewo_inter_page_delay_max_seconds,
            cooldown_seconds=config.degewo_cooldown_seconds,
            cooldown_status_codes=config.degewo_cooldown_status_codes,
        ),
    }


def _next_delay_for_company(config, company: str) -> float:
    if company == "wbm":
        return random.uniform(
            config.wbm_cycle_delay_min_seconds,
            config.wbm_cycle_delay_max_seconds,
        )
    if company == "degewo":
        return random.uniform(
            config.degewo_cycle_delay_min_seconds,
            config.degewo_cycle_delay_max_seconds,
        )
    return random.uniform(
        config.default_cycle_delay_min_seconds,
        config.default_cycle_delay_max_seconds,
    )


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
        if company in {"howoge", "gesobau", "stadt_und_land"}
    ]
    if placeholder_sources:
        logging.warning(
            "These providers are enabled but still placeholders: %s",
            ", ".join(placeholder_sources),
        )

    logging.info("Startup checks passed")


def _run_company_worker(
    company: str,
    scraper,
    db: Database,
    notifier: TelegramNotifier,
    config,
    stop_event: threading.Event,
) -> None:
    logging.info("Worker for '%s' started", company)
    while not stop_event.is_set():
        try:
            listings = scraper.scrape()
        except Exception as exc:
            logging.exception("Scraper '%s' failed: %s", company, exc)
            delay = _next_delay_for_company(config, company)
            if stop_event.wait(timeout=delay):
                break
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
        delay = _next_delay_for_company(config, company)
        logging.info("Next run for '%s' in %.1f seconds.", company, delay)
        if stop_event.wait(timeout=delay):
            break

    logging.info("Worker for '%s' stopped", company)


def run(check_only: bool = False) -> None:
    config = load_config()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    db = Database(config.database_path)
    notifier = TelegramNotifier(config.telegram_bot_token)
    scrapers = _build_scrapers(config.request_timeout_seconds, config)

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

    worker_threads: list[threading.Thread] = []
    for company in enabled:
        worker = threading.Thread(
            target=_run_company_worker,
            args=(company, scrapers[company], db, notifier, config, stop_event),
            daemon=True,
            name=f"crawler-{company}",
        )
        worker.start()
        worker_threads.append(worker)

    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutdown requested by user. Stopping workers...")
    finally:
        stop_event.set()
        for worker in worker_threads:
            worker.join(timeout=5)
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


