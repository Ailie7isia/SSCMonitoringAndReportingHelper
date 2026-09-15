import logging
import unittest
from datetime import datetime, timedelta, timezone

import tests  # noqa: F401
from Services import rate_limit
from Services.rate_limit import RequestPacer
from ssc_client import RateLimitError

NOW = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


class Endpoint:
    """Raises a 429 for the first ``limited`` calls, then succeeds."""

    def __init__(self, limited: int = 0, retry_after: float | None = 30) -> None:
        self.limited = limited
        self.retry_after = retry_after
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.limited:
            self.limited -= 1
            raise RateLimitError("Too many requests", retry_after=self.retry_after)
        return "ok"


class RequestPacerTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        self.clock = Clock()
        self.statuses: list[rate_limit.RateLimitStatus] = []
        self.pacer = RequestPacer(
            sleep=self.clock.sleep,
            clock=self.clock.monotonic,
            now=lambda: NOW + timedelta(seconds=self.clock.now),
            on_status=self.statuses.append,
        )

    def run_on(self, endpoint: str, action) -> str:
        return self.pacer.run(endpoint, action, "testing")

    def test_first_limit_trusts_retry_after(self):
        self.assertEqual(self.run_on("x", Endpoint(limited=1, retry_after=42)), "ok")
        self.assertEqual(self.clock.sleeps, [42])

    def test_repeated_limit_escalates_past_an_understated_retry_after(self):
        self.run_on("x", Endpoint(limited=4, retry_after=30))
        self.assertEqual(self.clock.sleeps, [30, 120, 300, 600])

    def test_missing_retry_after_uses_backoff_and_is_marked_estimated(self):
        self.run_on("x", Endpoint(limited=2, retry_after=None))
        self.assertEqual(self.clock.sleeps, list(rate_limit.BACKOFF_WAITS[:2]))
        cooling = [s for s in self.statuses if s.state == "cooling"]
        self.assertTrue(all(s.estimated for s in cooling))

    def test_single_wait_is_capped(self):
        self.run_on("x", Endpoint(limited=1, retry_after=10 * 3600))
        self.assertEqual(self.clock.sleeps, [rate_limit.MAX_RATE_LIMIT_WAIT])

    def test_gives_up_once_the_time_budget_is_spent(self):
        with self.assertRaises(RateLimitError):
            self.run_on("x", Endpoint(limited=1000, retry_after=30))
        self.assertLessEqual(sum(self.clock.sleeps), rate_limit.MAX_TOTAL_WAIT)
        self.assertGreater(len(self.clock.sleeps), 5, "a count of five retries was the old, too-short budget")

    def test_cooldown_is_shared_by_the_next_request(self):
        self.run_on("x", Endpoint(limited=1, retry_after=100))
        self.clock.sleeps.clear()
        second = Endpoint()
        self.run_on("x", second)
        # Only the gap learned from the limit (1 second on an unpaced endpoint)
        # is waited; the next request does not hit the limit again.
        self.assertEqual(second.calls, 1)
        self.assertEqual(self.clock.sleeps, [1.0])

    def test_detailed_reports_start_spaced_and_other_endpoints_do_not(self):
        self.run_on("reports/detailed", Endpoint())
        self.run_on("reports/detailed", Endpoint())
        self.assertEqual(self.clock.sleeps, [rate_limit.INITIAL_SPACING["reports/detailed"]])
        self.clock.sleeps.clear()
        self.run_on("companies", Endpoint())
        self.run_on("companies", Endpoint())
        self.assertEqual(self.clock.sleeps, [])

    def test_limit_on_one_endpoint_does_not_delay_another(self):
        self.run_on("reports/detailed", Endpoint(limited=1, retry_after=600))
        self.clock.sleeps.clear()
        self.run_on("companies", Endpoint())
        self.assertEqual(self.clock.sleeps, [])

    def test_gap_widens_on_limit_and_narrows_after_a_run_of_successes(self):
        start = self.pacer.spacing("reports/detailed")
        self.run_on("reports/detailed", Endpoint(limited=1, retry_after=5))
        widened = self.pacer.spacing("reports/detailed")
        self.assertEqual(widened, start * 2)
        for _ in range(rate_limit.RELAX_AFTER):
            self.run_on("reports/detailed", Endpoint())
        self.assertLess(self.pacer.spacing("reports/detailed"), widened)
        self.assertGreaterEqual(self.pacer.spacing("reports/detailed"), start)

    def test_status_reports_cooling_with_resume_time_then_pacing(self):
        self.run_on("reports/detailed", Endpoint(limited=1, retry_after=90))
        self.run_on("reports/detailed", Endpoint())
        states = [s.state for s in self.statuses]
        self.assertIn("cooling", states)
        self.assertIn("pacing", states)
        cooling = next(s for s in self.statuses if s.state == "cooling")
        self.assertEqual(cooling.resume_at, NOW + timedelta(seconds=90))
        self.assertEqual(cooling.rate_limited, 1)

    def test_finish_summarises_and_publishes_final_state(self):
        self.run_on("x", Endpoint(limited=1, retry_after=65))
        summary = self.pacer.finish()
        self.assertEqual(self.statuses[-1].state, "finished")
        self.assertIn("2 sent, 1 rate-limited, 1:05 waiting on limits", summary)


if __name__ == "__main__":
    unittest.main()
