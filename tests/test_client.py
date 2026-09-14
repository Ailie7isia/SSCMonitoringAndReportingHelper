import unittest
from unittest import mock

import requests

import tests  # noqa: F401
from ssc_client import ApiRequestError, SecurityScorecardClient


def response(status: int, payload=None, text: str = "") -> mock.Mock:
    result = mock.Mock()
    result.ok = 200 <= status < 300
    result.status_code = status
    result.text = text
    result.json.return_value = payload
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

    def test_network_error_is_wrapped(self):
        self.request.side_effect = requests.ConnectionError("offline")
        with self.assertRaises(ApiRequestError):
            self.client.get_company("a.com")


if __name__ == "__main__":
    unittest.main()
