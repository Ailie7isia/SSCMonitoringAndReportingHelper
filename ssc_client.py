from __future__ import annotations
from typing import Any

import requests
import logging

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

        if not response.ok:
            raise ApiRequestError(
                response.text,
                status_code=response.status_code,
                response=response,
            )

        return response

    def fetch_portfolio_companies(
        self,
        portfolio_id: str,
    ) -> list[dict]:

        r = self._request(
            "GET",
            f"/portfolios/{portfolio_id}/companies",
        )

        return r.json()["entries"]

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

    def remove_company(
        self,
        portfolio_id: str,
        domain: str,
    ):

        self._request(
            "DELETE",
            f"/portfolios/{portfolio_id}/companies/{domain}",
        )

    def create_report(
        self,
        *,
        domain: str,
        report_type: str,
        fmt: str = "pdf",
    ) -> dict:

        r = self._request(
            "POST",
            "/reports",
            json={
                "domain": domain,
                "type": report_type,
                "format": fmt,
            },
        )

        return r.json()

    def get_report(
        self,
        report_id: str,
    ) -> dict:

        r = self._request(
            "GET",
            f"/reports/{report_id}",
        )

        return r.json()

    def list_recent_reports(self) -> list[dict]:

        r = self._request(
            "GET",
            "/reports/recent",
        )

        return r.json().get("entries", [])

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

    def get_company(
        self,
        domain: str,
    ) -> dict:
        r = self._request(
        "GET",
        f"/companies/{domain}",
    )

        return r.json()    