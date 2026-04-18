from __future__ import annotations

import logging
from typing import List

from scrapers.base import BaseScraper
from shared.models import Listing


class DegewoScraper(BaseScraper):
    source = "degewo"
    url = "https://www.degewo.de/wohnungen"

    def scrape(self) -> List[Listing]:
        logging.warning("degewo scraper is not implemented yet")
        return []
