from __future__ import annotations

import logging
from typing import List

from scrapers.base import BaseScraper
from shared.models import Listing


class StadtUndLandScraper(BaseScraper):
    source = "stadt_und_land"
    url = "https://www.stadtundland.de/wohnungen-gewerbe/wohnungssuche/"

    def scrape(self) -> List[Listing]:
        logging.warning("Stadt und Land scraper is not implemented yet")
        return []
