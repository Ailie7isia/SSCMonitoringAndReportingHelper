import time
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest import mock

import requests
from requests.structures import CaseInsensitiveDict

import tests  # noqa: F401
from ssc_client import ApiRequestError, RateLimitError, SecurityScorecardClient, seconds_until_reset


def response(status: int, payload=None, text: str = "", headers=None) -> mock.Mock:
    result = mock.Mock()
    result.ok = 200 <= status < 300
    result.status_code = status
    result.text = text
    result.headers = CaseInsensitiveDict(headers or {})
    result.json.return_value = payload
    result.content = text.encode()
    return result


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.client = SecurityScorecardClient("secret", timeout=7)
        self.request = mock.Mock()
        self.client.session.request = self.request

    def test_sends_token_header(self):
        self.assertEqual(self.client.session.headers["Authorization"], "Token secret")

    def test_fetch_portfolio_companies(self):
        self.request.return_value = response(200, {"entries": [{"domain": "a.com"}]})
        self.assertEqual(self.client.fetch_portfolio_companies("p1"), [{"domain": "a.com"}])
        self.request.assert_called_once_with(
            "GET", "https://api.securityscorecard.io/portfolios/p1/companies", timeout=7
        )

    def test_issues_report_requests_csv(self):
        self.request.return_value = response(200, {"id": "r1"})
        self.assertEqual(self.client.create_issues_report("a.com"), {"id": "r1"})
        self.assertEqual(
            self.request.call_args.kwargs["json"], {"scorecard_identifier": "a.com", "format": "csv"}
        )

    def test_non_success_status_raises(self):
        self.request.return_value = response(404, text="not found")
        with self.assertRaises(ApiRequestError) as caught:
            self.client.remove_company("p1", "a.com")
        self.assertEqual(caught.exception.status_code, 404)
        self.assertNotIsInstance(caught.exception, RateLimitError)

    def test_network_error_is_wrapped(self):
        self.request.side_effect = requests.ConnectionError("offline")
        with self.assertRaises(ApiRequestError):
            self.client.get_company("a.com")

    def test_too_many_requests_raises_rate_limit_error_with_wait(self):
        self.request.return_value = response(
            429, text="Too many requests", headers={"Retry-After": "120", "RateLimit-Limit": "5"}
        )
        with self.assertRaises(RateLimitError) as caught:
            self.client.create_detailed_report("a.com")
        self.assertEqual(caught.exception.retry_after, 120)
        self.assertEqual(caught.exception.limit, "5")
        self.assertEqual(caught.exception.status_code, 429)

    def test_download_rate_limit_is_detected(self):
        self.client.session.get = mock.Mock(return_value=response(429, headers={"Retry-After": "30"}))
        with self.assertRaises(RateLimitError) as caught:
            self.client.download_report("https://files.test/r1")
        self.assertEqual(caught.exception.retry_after, 30)


class SecondsUntilResetTest(unittest.TestCase):
    def check(self, headers, expected):
        actual = seconds_until_reset(CaseInsensitiveDict(headers))
        if expected is None:
            self.assertIsNone(actual)
        else:
            self.assertAlmostEqual(actual, expected, delta=2)

    def test_retry_after_seconds(self):
        self.check({"Retry-After": "90"}, 90)

    def test_retry_after_http_date(self):
        self.check({"Retry-After": format_datetime(datetime.now(timezone.utc) + timedelta(seconds=90), usegmt=True)}, 90)

    def test_ratelimit_reset_delta_seconds(self):
        self.check({"RateLimit-Reset": "30"}, 30)

    def test_ratelimit_reset_epoch_seconds_and_milliseconds(self):
        self.check({"X-RateLimit-Reset": str(int(time.time() + 45))}, 45)
        self.check({"RateLimit-Reset": str(int((time.time() + 45) * 1000))}, 45)

    def test_past_reset_is_zero_and_missing_is_none(self):
        self.check({"RateLimit-Reset": str(int(time.time() - 60))}, 0)
        self.check({}, None)
        self.check({"Retry-After": "soon"}, None)


if __name__ == "__main__":
    unittest.main()
