from __future__ import annotations

import logging
from typing import List

from scrapers.base import BaseScraper
from shared.models import Listing


class GESOBAUScraper(BaseScraper):
    source = "gesobau"
    url = "https://www.gesobau.de/mieten/wohnungen"

    def scrape(self) -> List[Listing]:
        logging.warning("GESOBAU scraper is not implemented yet")
        return []
