from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Listing:
    source: str
    listing_id: str
    title: str
    address: str
    rent: str
    size: str
    rooms: str
    link: str

    @property
    def unique_key(self) -> str:
        return f"{self.source}:{self.listing_id}" if self.listing_id else f"{self.source}:{self.link}"
