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
        for patcher in (
            mock.patch("Services.reports.time.sleep"),
            mock.patch("Services.reports.SecurityScorecardClient", return_value=self.client),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.month = datetime.now(timezone.utc).strftime("%B %Y")

    def test_saves_pdf_and_csv_into_type_folders(self):
        saved = reports.download_reports(self.client, [Company("kalbe.co.id", "Kalbe Farma")], self.output)
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
        saved = reports.download_reports(self.client, [Company("pending.com", "Pending")], self.output)
        self.assertEqual(saved, [])
        self.assertEqual(self.client.receipts, {})

    def test_invalid_download_is_regenerated_once(self):
        self.client.bad_first_download = {"kalbe.co.id"}
        saved = reports.download_reports(
            self.client, [Company("kalbe.co.id", "Kalbe Farma")], self.output, ("detailed_report",)
        )
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(self.client.receipts), 2)
        self.assertTrue(saved[0].read_bytes().startswith(b"%PDF-"))

    def test_unknown_report_type_rejected(self):
        with self.assertRaises(ValueError):
            reports.download_reports(self.client, [Company("kalbe.co.id", "Kalbe")], self.output, ("summary",))

    def test_companies_sharing_a_display_name_do_not_overwrite_each_other(self):
        companies = [Company("kalventis.co.id", "Kalventis"), Company("kalventis.com", "Kalventis")]
        saved = reports.download_reports(self.client, companies, self.output, ("detailed_report",))
        self.assertEqual(
            sorted(path.name for path in (self.output / "detailed").glob("*.pdf")),
            [
                f"[A] - Kalventis (kalventis.co.id) - Detailed Report - {self.month}.pdf",
                f"[A] - Kalventis (kalventis.com) - Detailed Report - {self.month}.pdf",
            ],
        )
        self.assertEqual(len(saved), 2)

    def test_unique_display_names_keep_the_plain_filename(self):
        companies = [Company("kalbe.co.id", "Kalbe Farma"), Company("kalventis.com", "Kalventis")]
        saved = reports.download_reports(self.client, companies, self.output, ("detailed_report",))
        self.assertEqual(
            sorted(path.name for path in saved),
            [
                f"[A] - Kalbe Farma - Detailed Report - {self.month}.pdf",
                f"[A] - Kalventis - Detailed Report - {self.month}.pdf",
            ],
        )

    def test_transient_polling_error_does_not_discard_the_batch(self):
        self.client.recent_report_errors = 1
        saved = reports.download_reports(
            self.client, [Company("kalbe.co.id", "Kalbe Farma")], self.output, ("detailed_report",)
        )
        self.assertEqual(len(saved), 1)


if __name__ == "__main__":
    unittest.main()
