"""Pace SecurityScorecard requests and wait out rate limits.

SecurityScorecard allows 5,000 requests per rolling hour and applies a
stricter, unpublished limit to POST /reports/detailed. A limited request gets
HTTP 429 with a Retry-After header; successful responses carry no quota
headers, so the remaining allowance cannot be read, only learned.

Retrying each request a fixed number of times at whatever Retry-After said
dropped reports whenever the header understated the real reset or was
missing while the window was long, and every request rediscovered the limit
by hitting it. This pacer shares what it learns across the batch instead:
after a 429 every request to that endpoint waits out the same cooldown, the
gap between requests widens, repeated 429s escalate the wait past
Retry-After, and a request is only abandoned once a time budget is spent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, TypeVar

from ssc_client import RateLimitError
from utils import format_duration

T = TypeVar("T")

# Waits for a 429 without Retry-After, and the floor once a repeated 429 shows
# Retry-After understated the reset.
BACKOFF_WAITS = (60, 120, 300, 600, 900)
# No single wait is longer than SecurityScorecard's rolling hour plus margin.
MAX_RATE_LIMIT_WAIT = 65 * 60
# A request is abandoned once its rate-limit waits would exceed this.
MAX_TOTAL_WAIT = 65 * 60
# Minimum gap between requests to one endpoint, in seconds. Detailed reports
# start spaced because SecurityScorecard documents a stricter limit there.
INITIAL_SPACING = {"reports/detailed": 3.0}
MAX_SPACING = 300.0
# After this many successes in a row the gap narrows again.
RELAX_AFTER = 10
RELAX_FACTOR = 0.8

StatusCallback = Callable[["RateLimitStatus"], None]


@dataclass(frozen=True, slots=True)
class RateLimitStatus:
    """A snapshot of the pacer for display."""

    # "running", "pacing" (waiting for the gap), "cooling" (waiting out a 429)
    # or "finished".
    state: str
    endpoint: str | None
    # Local time the next request may be sent, while pacing or cooling.
    resume_at: datetime | None
    # Current gap between requests to ``endpoint``, in seconds.
    spacing: float
    requests: int
    rate_limited: int
    waited_on_limits: float
    waited_on_pacing: float
    # True when a cooldown was guessed because SecurityScorecard gave no Retry-After.
    estimated: bool = False


class RequestPacer:
    """Send requests at a pace SecurityScorecard accepts, one batch at a time.

    ``sleep`` and ``clock`` are injected so tests can run an hour instantly.
    """

    def __init__(
        self,
        *,
        sleep: Callable[[float], None],
        clock: Callable[[], float],
        now: Callable[[], datetime] | None = None,
        on_status: StatusCallback | None = None,
    ) -> None:
        self._sleep = sleep
        self._clock = clock
        self._now = now or (lambda: datetime.now().astimezone())
        self._on_status = on_status
        self._base = dict(INITIAL_SPACING)
        self._spacing = dict(INITIAL_SPACING)
        self._next_slot: dict[str, float] = {}
        self._cooldown_until: dict[str, float] = {}
        self._estimated: dict[str, bool] = {}
        self._limited_in_a_row: dict[str, int] = {}
        self._successes_in_a_row: dict[str, int] = {}
        self.requests = 0
        self.rate_limited = 0
        self.waited_on_limits = 0.0
        self.waited_on_pacing = 0.0

    def spacing(self, endpoint: str) -> float:
        return self._spacing.get(endpoint, 0.0)

    def status(self, state: str, endpoint: str | None = None, wait: float = 0.0) -> RateLimitStatus:
        return RateLimitStatus(
            state=state,
            endpoint=endpoint,
            resume_at=self._now() + timedelta(seconds=wait) if wait > 0 else None,
            spacing=self.spacing(endpoint) if endpoint else 0.0,
            requests=self.requests,
            rate_limited=self.rate_limited,
            waited_on_limits=self.waited_on_limits,
            waited_on_pacing=self.waited_on_pacing,
            estimated=self._estimated.get(endpoint, False) if endpoint else False,
        )

    def _publish(self, state: str, endpoint: str | None = None, wait: float = 0.0) -> None:
        if self._on_status:
            self._on_status(self.status(state, endpoint, wait))

    def run(self, endpoint: str, action: Callable[[], T], activity: str) -> T:
        """Run ``action`` once the endpoint may be called, waiting out any 429."""
        waited_for_this_request = 0.0
        while True:
            now = self._clock()
            cooldown = max(0.0, self._cooldown_until.get(endpoint, 0.0) - now)
            gap = max(0.0, self._next_slot.get(endpoint, 0.0) - now)
            wait = max(cooldown, gap)
            if wait > 0:
                cooling = cooldown >= gap
                self._publish("cooling" if cooling else "pacing", endpoint, wait)
                self._sleep(wait)
                if cooling:
                    self.waited_on_limits += wait
                else:
                    self.waited_on_pacing += wait
            self.requests += 1
            try:
                result = action()
            except RateLimitError as exc:
                self.rate_limited += 1
                delay, estimated = self._learn_from_limit(endpoint, exc)
                if waited_for_this_request + delay > MAX_TOTAL_WAIT:
                    self._publish("running", endpoint)
                    raise
                waited_for_this_request += delay
                self._cooldown_until[endpoint] = self._clock() + delay
                self._estimated[endpoint] = estimated
                logging.warning(
                    "SecurityScorecard request limit reached while %s%s. Waiting %s until %s (%s).",
                    activity,
                    f" (limit: {exc.limit})" if exc.limit else "",
                    format_duration(delay),
                    f"{self._now() + timedelta(seconds=delay):%H:%M:%S}",
                    "estimated; SecurityScorecard did not say when the quota resets"
                    if estimated
                    else "reset time from SecurityScorecard",
                )
                continue
            self._learn_from_success(endpoint)
            self._publish("running", endpoint)
            return result

    def _learn_from_limit(self, endpoint: str, exc: RateLimitError) -> tuple[float, bool]:
        in_a_row = self._limited_in_a_row.get(endpoint, 0)
        self._limited_in_a_row[endpoint] = in_a_row + 1
        self._successes_in_a_row[endpoint] = 0
        self._spacing[endpoint] = min(max(self.spacing(endpoint) * 2, 1.0), MAX_SPACING)

        backoff = BACKOFF_WAITS[min(in_a_row, len(BACKOFF_WAITS) - 1)]
        if exc.retry_after is None:
            return min(backoff, MAX_RATE_LIMIT_WAIT), True
        # Trust Retry-After the first time. Still being limited right after
        # waiting it out means it understated the reset, so escalate.
        delay = exc.retry_after if in_a_row == 0 else max(exc.retry_after, backoff)
        return min(max(delay, 1.0), MAX_RATE_LIMIT_WAIT), False

    def _learn_from_success(self, endpoint: str) -> None:
        self._limited_in_a_row[endpoint] = 0
        successes = self._successes_in_a_row.get(endpoint, 0) + 1
        base = self._base.get(endpoint, 0.0)
        if successes >= RELAX_AFTER and self.spacing(endpoint) > base:
            relaxed = self.spacing(endpoint) * RELAX_FACTOR
            self._spacing[endpoint] = relaxed if relaxed >= max(base, 0.5) else base
            successes = 0
        self._successes_in_a_row[endpoint] = successes
        self._next_slot[endpoint] = self._clock() + self.spacing(endpoint)

    def finish(self) -> str:
        """Publish the final state and return a one-line summary for the log."""
        self._publish("finished")
        return (
            f"SecurityScorecard requests: {self.requests} sent, {self.rate_limited} rate-limited, "
            f"{format_duration(self.waited_on_limits)} waiting on limits, "
            f"{format_duration(self.waited_on_pacing)} pacing."
        )
