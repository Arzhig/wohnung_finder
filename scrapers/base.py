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
        response = self._get(self.url)
        response.raise_for_status()
        return response.text

    def _get(self, url: str, use_policy: bool = True, **kwargs) -> requests.Response:
        if use_policy:
            self.crawl_policy.wait_for_slot()
        return requests.get(url, timeout=self.timeout_seconds, **kwargs)

    def _post(self, url: str, use_policy: bool = True, **kwargs) -> requests.Response:
        if use_policy:
            self.crawl_policy.wait_for_slot()
        return requests.post(url, timeout=self.timeout_seconds, **kwargs)

    @abstractmethod
    def scrape(self) -> List[Listing]:
        raise NotImplementedError
