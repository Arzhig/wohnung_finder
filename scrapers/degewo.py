from __future__ import annotations

import logging
import random
import re
import time
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from requests import Response
from requests import exceptions as requests_exceptions

from scrapers.base import BaseScraper
from shared.models import Listing


class DegewoScraper(BaseScraper):
    source = "degewo"
    url = "https://www.degewo.de/immosuche"

    def __init__(
        self,
        crawl_policy,
        timeout_seconds: int,
        inter_page_delay_min_seconds: float = 1.5,
        inter_page_delay_max_seconds: float = 4.5,
        cooldown_seconds: int = 900,
        cooldown_status_codes: List[int] | None = None,
    ) -> None:
        super().__init__(crawl_policy=crawl_policy, timeout_seconds=timeout_seconds)
        self.inter_page_delay_min_seconds = inter_page_delay_min_seconds
        self.inter_page_delay_max_seconds = inter_page_delay_max_seconds
        self.cooldown_seconds = cooldown_seconds
        self.cooldown_status_codes = set(cooldown_status_codes or [403, 429])
        self.max_page_retries = 3
        self.retry_backoff_base_seconds = 2.0

    def scrape(self) -> List[Listing]:
        first_response = self._request_with_retries(
            lambda: self._get(self.url),
            label="page 1",
        )
        if first_response is None:
            logging.warning("degewo: failed to fetch first page after retries")
            return []

        if self._handle_cooldown_status(first_response):
            return []
        first_response.raise_for_status()

        first_soup = BeautifulSoup(first_response.text, "html.parser")

        all_listings = self._extract_listings(first_soup)
        if not all_listings:
            return []

        total_hits = self._extract_total_hits(first_soup)
        per_page = len(all_listings)
        if total_hits <= per_page:
            return all_listings

        form_action, form_payload = self._extract_pagination_form(first_soup)
        if not form_action or not form_payload:
            return all_listings

        total_pages = (total_hits + per_page - 1) // per_page
        logging.info("degewo: detected %s total listings across %s pages", total_hits, total_pages)
        seen_keys = {listing.unique_key for listing in all_listings}

        for page in range(2, total_pages + 1):
            payload = [item for item in form_payload if item[0] != "tx_openimmo_immobilie[search]"]
            payload.append(("tx_openimmo_immobilie[search]", "paginate"))
            payload.append(("tx_openimmo_immobilie[page]", str(page)))

            delay_seconds = random.uniform(
                self.inter_page_delay_min_seconds,
                self.inter_page_delay_max_seconds,
            )
            if delay_seconds > 0:
                time.sleep(delay_seconds)

            # Pagination requests are treated as part of one logical scrape cycle.
            response = self._request_with_retries(
                lambda: self._post(form_action, data=payload, use_policy=False),
                label=f"page {page}",
            )
            if response is None:
                logging.warning(
                    "degewo: giving up on page %s after retries; returning partial result set (%s listings)",
                    page,
                    len(all_listings),
                )
                break

            if self._handle_cooldown_status(response):
                break
            response.raise_for_status()
            page_soup = BeautifulSoup(response.text, "html.parser")
            page_listings = self._extract_listings(page_soup)

            logging.info("degewo: page %s/%s returned %s listings", page, total_pages, len(page_listings))

            if not page_listings:
                break

            for listing in page_listings:
                if listing.unique_key in seen_keys:
                    continue
                seen_keys.add(listing.unique_key)
                all_listings.append(listing)

        logging.info("degewo: collected %s unique listings", len(all_listings))
        return all_listings

    def _request_with_retries(self, requester, label: str) -> Response | None:
        for attempt in range(1, self.max_page_retries + 1):
            try:
                response: Response = requester()
                if response.status_code >= 500:
                    raise requests_exceptions.HTTPError(
                        f"HTTP {response.status_code} on {label}",
                        response=response,
                    )
                return response
            except requests_exceptions.RequestException as exc:
                if attempt >= self.max_page_retries:
                    logging.warning(
                        "degewo: request failed for %s after %s attempts: %s",
                        label,
                        attempt,
                        exc,
                    )
                    return None

                backoff = self.retry_backoff_base_seconds * (2 ** (attempt - 1))
                jitter = random.uniform(0, 1)
                wait_seconds = backoff + jitter
                logging.warning(
                    "degewo: transient request error on %s (attempt %s/%s): %s; retrying in %.1fs",
                    label,
                    attempt,
                    self.max_page_retries,
                    exc,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

        return None

    def _handle_cooldown_status(self, response: Response) -> bool:
        if response.status_code in self.cooldown_status_codes:
            logging.warning(
                "degewo: received HTTP %s, entering cooldown for %s seconds",
                response.status_code,
                self.cooldown_seconds,
            )
            time.sleep(self.cooldown_seconds)
            return True
        return False

    def _extract_listing_id(self, link: str) -> str:
        match = re.search(r"/immosuche/details/([^/?#]+)", link)
        if match:
            return match.group(1)
        return link

    def _extract_total_hits(self, soup: BeautifulSoup) -> int:
        text = soup.get_text(" ", strip=True)
        match = re.search(r"(\d+)\s+Treffer\s+gefunden", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 0

    def _extract_pagination_form(self, soup: BeautifulSoup) -> tuple[str, List[tuple[str, str]]]:
        form = soup.select_one("form#openimmo-search-form")
        if form is None:
            return ("", [])

        action = form.get("action", "").strip()
        if not action:
            return ("", [])
        action_url = urljoin(self.url, action)

        payload: List[tuple[str, str]] = []
        for input_el in form.select("input[name]"):
            name = input_el.get("name", "").strip()
            if not name:
                continue
            if name == "tx_openimmo_immobilie[page]":
                continue

            input_type = (input_el.get("type", "text") or "text").lower()
            if input_type in {"checkbox", "radio"} and not input_el.has_attr("checked"):
                continue

            value = input_el.get("value", "")
            payload.append((name, value))

        payload.append(("tx_openimmo_immobilie[search]", "search"))
        return (action_url, payload)

    def _extract_listings(self, soup: BeautifulSoup) -> List[Listing]:
        listing_nodes = soup.select("article.article-list__item--immosearch")
        listings: List[Listing] = []

        for node in listing_nodes:
            details_link = node.select_one('a[href*="/immosuche/details/"]')
            if details_link is None:
                continue

            href = details_link.get("href", "").strip()
            if not href:
                continue
            full_link = urljoin(self.url, href)

            listing_id = self._extract_listing_id(full_link)

            title_node = node.select_one("h2.article__title")
            address_node = node.select_one("span.article__meta")
            price_node = node.select_one("div.article__price-tag")

            rooms = ""
            size = ""
            for property_item in node.select("ul.article__properties li.article__properties-item"):
                text = property_item.get_text(" ", strip=True)
                if not rooms and "Zimmer" in text:
                    rooms = text
                if not size and "m²" in text:
                    size = text

            title = title_node.get_text(" ", strip=True) if title_node else ""
            address = address_node.get_text(" ", strip=True) if address_node else ""
            rent = price_node.get_text(" ", strip=True) if price_node else ""

            if not title:
                continue

            listings.append(
                Listing(
                    source=self.source,
                    listing_id=listing_id,
                    title=title,
                    address=address,
                    rent=rent,
                    size=size,
                    rooms=rooms,
                    link=full_link,
                )
            )

        return listings
