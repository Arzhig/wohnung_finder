from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

import requests

from crawl_policy import CrawlPolicy
from shared.models import Listing


class BaseScraper(ABC):
    source: str
    url: str

    def __init__(self, crawl_policy: CrawlPolicy, timeout_seconds: int) -> None:
        self.crawl_policy = crawl_policy
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> str:
        self.crawl_policy.wait_for_slot()
        response = requests.get(self.url, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.text

    @abstractmethod
    def scrape(self) -> List[Listing]:
        raise NotImplementedError
