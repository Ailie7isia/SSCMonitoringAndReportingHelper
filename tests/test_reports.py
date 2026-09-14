import logging
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests.fakes import VALID_CSV, VALID_PDF, FakeClient
from models import Company
from Services import reports


class ValidateDownloadTest(unittest.TestCase):
    def test_accepts_real_files(self):
        reports._validate_download(VALID_PDF, ".pdf", "a.com")
        reports._validate_download(VALID_CSV, ".csv", "a.com")

    def test_rejects_small_non_pdf_and_error_pages(self):
        cases = [
            (b"%PDF-1.7", ".pdf"),
            (b"<html>" + b"x" * 8192, ".pdf"),
            (b"<!DOCTYPE html>" + b"x" * 512, ".csv"),
            (b"", ".csv"),
        ]
        for content, extension in cases:
            with self.subTest(content=content[:15], extension=extension):
                with self.assertRaises(ValueError):
                    reports._validate_download(content, extension, "a.com")


class DownloadReportsTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.output = Path(tmp.name)
        self.client = FakeClient(scores={
            "kalbe.co.id": (92, "A"),
            "kalventis.co.id": (90, "A"),
            "kalventis.com": (91, "A"),
        })
        sleep = mock.patch("Services.reports.time.sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        self.month = datetime.now(timezone.utc).strftime("%B %Y")

    def download(self, companies=None, report_types=("detailed_report",), **kwargs):
        companies = companies or [Company("kalbe.co.id", "Kalbe Farma")]
        return reports.download_reports(self.client, companies, self.output, report_types, **kwargs)

    def slept(self) -> list[float]:
        return [call.args[0] for call in self.sleep.call_args_list]

    def test_saves_pdf_and_csv_into_type_folders(self):
        saved = self.download(report_types=reports.REPORT_TYPES)
        self.assertEqual(
            sorted(path.relative_to(self.output).as_posix() for path in saved),
            [
                f"detailed/[A] - Kalbe Farma - Detailed Report - {self.month}.pdf",
                f"issues/[A] - Kalbe Farma - Issue Report - {self.month}.csv",
            ],
        )
        self.assertTrue(all(path.exists() for path in saved))
        self.assertEqual(list(self.output.rglob("*.part")), [])

    def test_skips_domain_whose_score_is_still_calculating(self):
        self.assertEqual(self.download([Company("pending.com", "Pending")]), [])
        self.assertEqual(self.client.receipts, {})

    def test_invalid_download_is_downloaded_again_before_regenerating(self):
        self.client.bad_downloads = {"kalbe.co.id": 1}
        saved = self.download()
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(self.client.receipts), 1, "a fresh download should not request a new report")
        self.assertTrue(saved[0].read_bytes().startswith(b"%PDF-"))

    def test_persistently_invalid_download_is_regenerated_once(self):
        self.client.bad_downloads = {"kalbe.co.id": 2}
        saved = self.download()
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(self.client.receipts), 2)

    def test_unknown_report_type_rejected(self):
        with self.assertRaises(ValueError):
            self.download(report_types=("summary",))

    def test_companies_sharing_a_display_name_do_not_overwrite_each_other(self):
        saved = self.download([Company("kalventis.co.id", "Kalventis"), Company("kalventis.com", "Kalventis")])
        self.assertEqual(
            sorted(path.name for path in (self.output / "detailed").glob("*.pdf")),
            [
                f"[A] - Kalventis (kalventis.co.id) - Detailed Report - {self.month}.pdf",
                f"[A] - Kalventis (kalventis.com) - Detailed Report - {self.month}.pdf",
            ],
        )
        self.assertEqual(len(saved), 2)

    def test_unique_display_names_keep_the_plain_filename(self):
        saved = self.download([Company("kalbe.co.id", "Kalbe Farma"), Company("kalventis.com", "Kalventis")])
        self.assertEqual(
            sorted(path.name for path in saved),
            [
                f"[A] - Kalbe Farma - Detailed Report - {self.month}.pdf",
                f"[A] - Kalventis - Detailed Report - {self.month}.pdf",
            ],
        )

    def test_transient_polling_error_does_not_discard_the_batch(self):
        self.client.recent_report_errors = 1
        self.assertEqual(len(self.download()), 1)

    def test_status_checks_back_off(self):
        self.client.pending_polls = 5
        self.assertEqual(len(self.download()), 1)
        self.assertEqual(self.slept(), [15, 20, 30, 45, 60, 60])
        self.assertEqual(self.client.list_recent_calls, 6)

    # Rate limits --------------------------------------------------------------------

    def test_rate_limited_request_waits_for_retry_after_then_continues(self):
        self.client.create_rate_limits = 1
        events = []
        saved = self.download(on_rate_limit=events.append)
        self.assertEqual(len(saved), 1)
        self.assertEqual(self.slept()[0], 42)
        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[0], datetime)
        self.assertIsNone(events[1])

    def test_rate_limit_without_retry_after_uses_fallback_wait(self):
        self.client.create_rate_limits = 2
        self.client.rate_limit_retry_after = None
        self.assertEqual(len(self.download()), 1)
        self.assertEqual(self.slept()[:2], list(reports.FALLBACK_RATE_LIMIT_WAITS[:2]))

    def test_excessive_wait_is_capped(self):
        self.client.create_rate_limits = 1
        self.client.rate_limit_retry_after = 10 * 3600
        self.download()
        self.assertEqual(self.slept()[0], reports.MAX_RATE_LIMIT_WAIT)

    def test_persistent_rate_limit_gives_up_after_retries(self):
        self.client.create_rate_limits = 100
        self.assertEqual(self.download(), [])
        self.assertEqual(self.client.receipts, {})
        self.assertEqual(self.slept(), [42] * reports.RATE_LIMIT_RETRIES)


if __name__ == "__main__":
    unittest.main()
