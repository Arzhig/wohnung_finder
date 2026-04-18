from __future__ import annotations

from typing import List

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from shared.models import Listing


class WBMScraper(BaseScraper):
    source = "wbm"
    url = "https://www.wbm.de/wohnungen-berlin/angebote/"

    def scrape(self) -> List[Listing]:
        html = self.fetch()
        soup = BeautifulSoup(html, "html.parser")

        listings_section = soup.find("div", class_="m-tabs__content")
        if listings_section is None:
            return []

        listing_nodes = listings_section.find_all("div", class_="openimmo-search-list-item")
        listings: List[Listing] = []
        for node in listing_nodes:
            listing_id = node.get("data-id", "")

            title_node = node.find("h2", class_="imageTitle")
            address_node = node.find("div", class_="address")
            rent_node = node.find("div", class_="main-property-rent")
            size_node = node.find("div", class_="main-property-size")
            rooms_node = node.find("div", class_="main-property-rooms")
            details_link = node.find("a", title="Details")

            if not all([title_node, address_node, rent_node, size_node, rooms_node, details_link]):
                continue

            relative_link = details_link.get("href", "")
            full_link = (
                f"https://www.wbm.de{relative_link}"
                if relative_link.startswith("/")
                else relative_link
            )

            listings.append(
                Listing(
                    source=self.source,
                    listing_id=listing_id,
                    title=title_node.get_text(strip=True),
                    address=address_node.get_text(separator=", ", strip=True),
                    rent=rent_node.get_text(strip=True),
                    size=size_node.get_text(strip=True),
                    rooms=rooms_node.get_text(strip=True),
                    link=full_link,
                )
            )

        return listings
