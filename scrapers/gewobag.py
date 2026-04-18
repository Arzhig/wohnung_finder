from __future__ import annotations

import logging
from typing import List

from scrapers.base import BaseScraper
from shared.models import Listing


class GEWOBAGScraper(BaseScraper):
    source = "gewobag"
    url = "https://www.gewobag.de/fuer-mieter-und-mietinteressenten/mietangebote/"

    def scrape(self) -> List[Listing]:
        logging.warning("GEWOBAG scraper is not implemented yet")
        return []
