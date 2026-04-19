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


class GEWOBAGScraper(BaseScraper):
    source = "gewobag"
    url = "https://www.gewobag.de/fuer-mietinteressentinnen/mietangebote/wohnung/?objekttyp%5B%5D=wohnung&bezirke_all=1"

    def __init__(self, crawl_policy, timeout_seconds: int) -> None:
        super().__init__(crawl_policy=crawl_policy, timeout_seconds=timeout_seconds)
        self.inter_page_delay_min_seconds = 1.0
        self.inter_page_delay_max_seconds = 3.0
        self.max_page_retries = 3
        self.retry_backoff_base_seconds = 2.0

    def scrape(self) -> List[Listing]:
        first_response = self._request_with_retries(
            lambda: self._get(self.url),
            label="page 1",
        )
        if first_response is None:
            logging.warning("gewobag: failed to fetch first page after retries")
            return []
        first_response.raise_for_status()

        first_soup = BeautifulSoup(first_response.text, "html.parser")
        all_listings = self._extract_listings(first_soup)
        if not all_listings:
            return []

        pagination_links = self._extract_pagination_links(first_soup)
        total_pages = 1 + len(pagination_links)
        logging.info("gewobag: detected %s pages", total_pages)

        seen_keys = {listing.unique_key for listing in all_listings}
        for page_index, page_url in enumerate(pagination_links, start=2):
            delay_seconds = random.uniform(
                self.inter_page_delay_min_seconds,
                self.inter_page_delay_max_seconds,
            )
            if delay_seconds > 0:
                time.sleep(delay_seconds)

            response = self._request_with_retries(
                lambda: self._get(page_url, use_policy=False),
                label=f"page {page_index}",
            )
            if response is None:
                logging.warning(
                    "gewobag: giving up on page %s after retries; returning partial result set (%s listings)",
                    page_index,
                    len(all_listings),
                )
                break

            response.raise_for_status()
            page_soup = BeautifulSoup(response.text, "html.parser")
            page_listings = self._extract_listings(page_soup)
            logging.info(
                "gewobag: page %s/%s returned %s listings",
                page_index,
                total_pages,
                len(page_listings),
            )

            if not page_listings:
                break

            for listing in page_listings:
                if listing.unique_key in seen_keys:
                    continue
                seen_keys.add(listing.unique_key)
                all_listings.append(listing)

        logging.info("gewobag: collected %s unique listings", len(all_listings))
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
                        "gewobag: request failed for %s after %s attempts: %s",
                        label,
                        attempt,
                        exc,
                    )
                    return None

                backoff = self.retry_backoff_base_seconds * (2 ** (attempt - 1))
                jitter = random.uniform(0, 1)
                wait_seconds = backoff + jitter
                logging.warning(
                    "gewobag: transient request error on %s (attempt %s/%s): %s; retrying in %.1fs",
                    label,
                    attempt,
                    self.max_page_retries,
                    exc,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

        return None

    def _extract_pagination_links(self, soup: BeautifulSoup) -> List[str]:
        links: List[tuple[int, str]] = []
        for anchor in soup.select("a.page-numbers[href]"):
            href = anchor.get("href", "").strip()
            if not href:
                continue
            match = re.search(r"/page/(\d+)/", href)
            if not match:
                continue
            page_number = int(match.group(1))
            links.append((page_number, urljoin(self.url, href)))

        links = sorted(set(links), key=lambda item: item[0])
        return [href for _, href in links]

    def _extract_listings(self, soup: BeautifulSoup) -> List[Listing]:
        listings: List[Listing] = []
        for node in soup.select("article.angebot-big-box.gw-offer"):
            title_node = node.select_one("h3.angebot-title")
            address_node = node.select_one("tr.angebot-address address")
            area_node = node.select_one("tr.angebot-area td")
            rent_node = node.select_one("tr.angebot-kosten td")
            link_node = node.select_one("div.angebot-footer a.read-more-link[href]")

            if title_node is None or link_node is None:
                continue

            full_link = urljoin(self.url, link_node.get("href", "").strip())
            listing_id = self._extract_listing_id(full_link)

            area_text = area_node.get_text(" ", strip=True) if area_node else ""
            rooms, size = self._split_area(area_text)

            listings.append(
                Listing(
                    source=self.source,
                    listing_id=listing_id,
                    title=title_node.get_text(" ", strip=True),
                    address=address_node.get_text(" ", strip=True) if address_node else "",
                    rent=rent_node.get_text(" ", strip=True) if rent_node else "",
                    size=size,
                    rooms=rooms,
                    link=full_link,
                )
            )

        return listings

    def _split_area(self, area_text: str) -> tuple[str, str]:
        parts = [part.strip() for part in area_text.split("|")]
        rooms = ""
        size = ""
        for part in parts:
            if "Zimmer" in part and not rooms:
                rooms = part
            if "m²" in part and not size:
                size = part
        return rooms, size

    def _extract_listing_id(self, link: str) -> str:
        match = re.search(r"/mietangebote/([^/?#]+)/?", link)
        if match:
            return match.group(1)
        return link
