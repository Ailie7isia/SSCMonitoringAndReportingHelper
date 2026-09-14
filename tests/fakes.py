"""In-memory stand-in for SecurityScorecardClient."""

from __future__ import annotations

import itertools
import threading

from ssc_client import ApiRequestError, RateLimitError

VALID_PDF = b"%PDF-1.7\n" + b"0" * 8192
VALID_CSV = (
    "ISSUE ID,FACTOR NAME,ISSUE TYPE TITLE,ISSUE TYPE SEVERITY,ISSUE RECOMMENDATION,STATUS,TARGET\n"
    + "1,Network Security,Open port,HIGH,Close the port,active,host.example\n" * 5
).encode()
ERROR_PAGE = b"<html><body>502 Bad Gateway</body></html>"

CONFIG = {"securityscorecard": {"api_key": "test-key", "portfolio_id": "portfolio-1"}}


class FakeClient:
    def __init__(self, portfolio=(), scores=None) -> None:
        self.api_key = "test-key"
        self.timeout = 1
        self.portfolio = [dict(entry) for entry in portfolio]
        # domain -> (score, grade)
        self.scores = {domain.lower(): value for domain, value in (scores or {}).items()}
        self.added: list[str] = []
        self.removed: list[str] = []
        self.fail_add: set[str] = set()
        self.fail_remove: set[str] = set()
        self.receipts: dict[str, tuple[str, str]] = {}
        # domain -> number of invalid downloads to serve before a valid one
        self.bad_downloads: dict[str, int] = {}
        self.recent_report_errors = 0
        # Status checks that report nothing finished yet.
        self.pending_polls = 0
        # 429 responses to raise from report creation, and the Retry-After they carry.
        self.create_rate_limits = 0
        self.rate_limit_retry_after: float | None = 42
        self.list_recent_calls = 0
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def fetch_portfolio_companies(self, portfolio_id: str) -> list[dict]:
        return [dict(entry) for entry in self.portfolio]

    def get_company(self, domain: str) -> dict:
        score, grade = self.scores.get(domain.lower(), (None, ""))
        return {"domain": domain, "score": score, "grade": grade}

    def add_company(self, portfolio_id: str, domain: str) -> None:
        if domain in self.fail_add:
            raise ApiRequestError("cannot add", status_code=400)
        self.added.append(domain)

    def remove_company(self, portfolio_id: str, domain: str) -> None:
        if domain in self.fail_remove:
            raise ApiRequestError("cannot remove", status_code=400)
        self.removed.append(domain)

    def _receipt(self, domain: str, kind: str) -> dict:
        with self._lock:
            if self.create_rate_limits:
                self.create_rate_limits -= 1
                raise RateLimitError("Too many requests", retry_after=self.rate_limit_retry_after)
            receipt_id = f"r{next(self._ids)}"
            self.receipts[receipt_id] = (domain, kind)
        return {"id": receipt_id}

    def create_detailed_report(self, domain: str) -> dict:
        return self._receipt(domain, "pdf")

    def create_issues_report(self, domain: str) -> dict:
        return self._receipt(domain, "csv")

    def list_recent_reports(self) -> list[dict]:
        with self._lock:
            self.list_recent_calls += 1
            if self.recent_report_errors:
                self.recent_report_errors -= 1
                raise ApiRequestError("Service Unavailable", status_code=503)
            if self.pending_polls:
                self.pending_polls -= 1
                return []
            return [
                {"id": receipt_id, "download_url": f"https://files.test/{receipt_id}"}
                for receipt_id in self.receipts
            ]

    def download_report(self, download_url: str) -> bytes:
        receipt_id = download_url.rsplit("/", 1)[-1]
        domain, kind = self.receipts[receipt_id]
        with self._lock:
            if self.bad_downloads.get(domain, 0) > 0:
                self.bad_downloads[domain] -= 1
                return ERROR_PAGE
        return VALID_PDF if kind == "pdf" else VALID_CSV
