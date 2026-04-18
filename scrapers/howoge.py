from __future__ import annotations

import logging
from typing import List

from scrapers.base import BaseScraper
from shared.models import Listing


class HOWOGEScraper(BaseScraper):
    source = "howoge"
    url = "https://www.howoge.de/wohnungen-gewerbe/wohnungssuche.html"

    def scrape(self) -> List[Listing]:
        logging.warning("HOWOGE scraper is not implemented yet")
        return []
