from __future__ import annotations

# -----------------------------------------------------------------------------
# SecurityScorecard API client.

# This file handles all communication with the SecurityScorecard API,
# including retrieving portfolio data, managing companies, generating
# reports, and downloading report files.
# -----------------------------------------------------------------------------

import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

# Custom exception used for API request failures.
# Includes HTTP status code and response when available.
class ApiRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response: requests.Response | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


# Raised for HTTP 429 Too Many Requests.
# ``retry_after`` is how many seconds SecurityScorecard asked the client to
# wait, or None when the response did not say. ``limit`` is the quota size
# when the response reports one.
class RateLimitError(ApiRequestError):
    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None,
        limit: str | None = None,
        response: requests.Response | None = None,
    ) -> None:
        super().__init__(message, status_code=429, response=response)
        self.retry_after = retry_after
        self.limit = limit


# Read how many seconds remain until the quota resets.
# Retry-After may be delta-seconds or an HTTP date; RateLimit-Reset may be
# delta-seconds or an epoch timestamp (seconds or milliseconds).
def seconds_until_reset(headers) -> float | None:
    retry_after = str(headers.get("Retry-After") or "").strip()
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                reset_at = parsedate_to_datetime(retry_after)
            except (TypeError, ValueError):
                reset_at = None
            if reset_at is not None:
                if reset_at.tzinfo is None:
                    reset_at = reset_at.replace(tzinfo=timezone.utc)
                return max(0.0, (reset_at - datetime.now(timezone.utc)).total_seconds())

    for name in ("RateLimit-Reset", "X-RateLimit-Reset"):
        try:
            value = float(str(headers.get(name) or "").strip())
        except ValueError:
            continue
        if value > 1e12:
            value = value / 1000 - time.time()
        elif value > 1e9:
            value -= time.time()
        return max(0.0, value)
    return None


class SecurityScorecardClient:
    # Base URL for all SecurityScorecard API requests.
    BASE_URL = "https://api.securityscorecard.io"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: int = 60,
    ):
        self.api_key = api_key
        self.timeout = timeout

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {api_key}",
            "Accept": "application/json",
        })

    # Raise ApiRequestError (or RateLimitError for 429) for non-2xx responses.
    @staticmethod
    def _check_response(response: requests.Response) -> None:
        if response.status_code == 429:
            raise RateLimitError(
                response.text or "Too many requests",
                retry_after=seconds_until_reset(response.headers),
                limit=response.headers.get("RateLimit-Limit") or response.headers.get("X-RateLimit-Limit"),
                response=response,
            )
        if not response.ok:
            raise ApiRequestError(
                response.text,
                status_code=response.status_code,
                response=response,
            )

    # Internal helper for making authenticated API requests.
    # Raises ApiRequestError if the request fails or returns a non-2xx response.
    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> requests.Response:

        url = f"{self.BASE_URL}{endpoint}"

        try:
            response = self.session.request(
                method,
                url,
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise ApiRequestError(str(exc)) from exc

        self._check_response(response)
        return response

    # Retrieve all companies in the specified portfolio.
    def fetch_portfolio_companies(
        self,
        portfolio_id: str,
    ) -> list[dict]:

        r = self._request(
            "GET",
            f"/portfolios/{portfolio_id}/companies",
        )

        return r.json()["entries"]

    # Add a company to the specified portfolio.
    def add_company(
        self,
        portfolio_id: str,
        domain: str,
    ):

        self._request(
            "POST",
            f"/portfolios/{portfolio_id}/companies",
            json={"domain": domain},
        )

    # Remove a company from the specified portfolio.
    def remove_company(
        self,
        portfolio_id: str,
        domain: str,
    ):

        self._request(
            "DELETE",
            f"/portfolios/{portfolio_id}/companies/{domain}",
        )


    def create_detailed_report(self, domain: str) -> dict:
        """Request a new Company Detailed PDF report for ``domain``."""
        response = self._request(
            "POST",
            "/reports/detailed",
            json={"scorecard_identifier": domain},
        )
        return response.json()

    def create_issues_report(self, domain: str) -> dict:
        """Request a new Company Issues report in CSV format for ``domain``."""
        response = self._request(
            "POST",
            "/reports/issues",
            json={"scorecard_identifier": domain, "format": "csv"},
        )
        return response.json()

    # Get the list of recently generated reports.
    def list_recent_reports(self) -> list[dict]:

        r = self._request(
            "GET",
            "/reports/recent",
        )

        return r.json().get("entries", [])

    # Download the completed report file from its download URL.
    def download_report(
        self,
        download_url: str,
    ) -> bytes:

        try:
            r = self.session.get(
                download_url,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ApiRequestError(str(exc)) from exc

        self._check_response(r)

        return r.content

    # Retrieve company details for a given domain.
    def get_company(
        self,
        domain: str,
    ) -> dict:
        r = self._request(
            "GET",
            f"/companies/{domain}",
        )
        return r.json()

    # Retrieve the company's current score, grade and issue summary for each
    # of SecurityScorecard's ten risk factors.
    def get_company_factors(
        self,
        domain: str,
    ) -> list[dict]:
        r = self._request(
            "GET",
            f"/companies/{domain}/factors",
        )
        return r.json().get("entries", [])

    # Retrieve the company's factor scores over time. "monthly" returns one
    # averaged entry per month for about the last year.
    def get_factor_history(
        self,
        domain: str,
        *,
        timing: str = "monthly",
        date_from: str | None = None,
    ) -> list[dict]:
        params = {"timing": timing}
        if date_from:
            params["date_from"] = date_from
        r = self._request(
            "GET",
            f"/companies/{domain}/history/factors/score",
            params=params,
        )
        return r.json().get("entries", [])
