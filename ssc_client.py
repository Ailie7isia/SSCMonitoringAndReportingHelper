from __future__ import annotations
from typing import Any

# -----------------------------------------------------------------------------
# SecurityScorecard API client.

# This file handles all communication with the SecurityScorecard API,
# including retrieving portfolio data, managing companies, generating
# reports, and downloading report files.
# -----------------------------------------------------------------------------

import requests
import logging

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

        # Treat any non-success response as an API error.
        if not response.ok:
            raise ApiRequestError(
                response.text,
                status_code=response.status_code,
                response=response,
            )

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

        r = self.session.get(
            download_url,
            timeout=self.timeout,
        )

        r.raise_for_status()

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
