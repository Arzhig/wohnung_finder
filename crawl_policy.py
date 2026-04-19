from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import CrawlPolicyConfig


class CrawlPolicy:
    def __init__(self, config: CrawlPolicyConfig) -> None:
        self.config = config
        self.request_timestamps: deque[float] = deque()
        self.last_request_ts: float | None = None
        self._lock = threading.Lock()
        try:
            self.tz = ZoneInfo(config.timezone)
        except ZoneInfoNotFoundError:
            logging.warning(
                "Timezone '%s' not found. Falling back to UTC. Install tzdata to use named timezones.",
                config.timezone,
            )
            self.tz = timezone.utc

    def wait_for_slot(self) -> None:
        with self._lock:
            self._wait_if_quiet_hours()
            self._wait_for_rate_limit()
            self._wait_for_randomized_delay()
            self._record_request()

    def _wait_if_quiet_hours(self) -> None:
        now = datetime.now(self.tz)
        if self._is_in_quiet_window(now):
            resume_time = now.replace(
                hour=self.config.quiet_hours_end,
                minute=0,
                second=0,
                microsecond=0,
            )
            if now.hour >= self.config.quiet_hours_end:
                resume_time = resume_time + timedelta(days=1)
            sleep_seconds = max(0.0, (resume_time - now).total_seconds())
            if sleep_seconds > 0:
                logging.info(
                    "Crawl quiet window active (%02d:00-%02d:00 %s). Sleeping %.0f seconds.",
                    self.config.quiet_hours_start,
                    self.config.quiet_hours_end,
                    self.config.timezone,
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)

    def _is_in_quiet_window(self, dt: datetime) -> bool:
        # Quiet window is expected to be [start, end) and currently configured as 00:00-06:00.
        return self.config.quiet_hours_start <= dt.hour < self.config.quiet_hours_end

    def _wait_for_rate_limit(self) -> None:
        now_ts = time.time()
        while self.request_timestamps and now_ts - self.request_timestamps[0] >= 60:
            self.request_timestamps.popleft()

        if len(self.request_timestamps) >= self.config.max_calls_per_minute:
            oldest = self.request_timestamps[0]
            sleep_seconds = max(0.0, 60 - (now_ts - oldest))
            if sleep_seconds > 0:
                logging.info(
                    "Crawl rate limit reached (%s/min). Sleeping %.1f seconds.",
                    self.config.max_calls_per_minute,
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)

    def _wait_for_randomized_delay(self) -> None:
        if self.last_request_ts is None:
            return

        sampled = random.gauss(
            mu=self.config.delay_mean_seconds,
            sigma=self.config.delay_std_seconds,
        )
        bounded = min(
            max(sampled, self.config.delay_min_seconds),
            self.config.delay_max_seconds,
        )

        elapsed = time.time() - self.last_request_ts
        sleep_seconds = max(0.0, bounded - elapsed)
        if sleep_seconds > 0:
            logging.info(
                "Applying randomized crawl delay. Sleeping %.1f seconds.",
                sleep_seconds,
            )
            time.sleep(sleep_seconds)

    def _record_request(self) -> None:
        now_ts = time.time()
        self.request_timestamps.append(now_ts)
        self.last_request_ts = now_ts
