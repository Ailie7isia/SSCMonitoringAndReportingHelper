"""Headless-ish smoke tests for the customtkinter dashboard (window stays withdrawn)."""

import logging
import queue
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from openpyxl import load_workbook

from tests.fakes import FakeClient
from tests.test_scores import write_history
from models import Company
from Services.portfolio import target_domains
from Services.scores import HistoricalScoreTrend

try:
    import customtkinter as ctk
    import gui
except Exception as exc:  # pragma: no cover - environment without Tk
    gui = None
    IMPORT_ERROR = exc


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def label_texts(widget) -> list[str]:
    return [w.cget("text") for w in descendants(widget) if isinstance(w, ctk.CTkLabel)]


def no_network():
    raise AssertionError("test attempted to contact SecurityScorecard")


class InlineThread:
    """Runs a worker synchronously: Tk's after() needs mainloop() when called from another thread."""

    def __init__(self, target, daemon=None, **_kwargs):
        self.target = target

    def start(self):
        self.target()


class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if gui is None:
            raise unittest.SkipTest(f"GUI unavailable: {IMPORT_ERROR}")
        with mock.patch.object(gui.Dashboard, "refresh_dashboard"):
            try:
                cls.app = gui.Dashboard()
            except Exception as exc:
                raise unittest.SkipTest(f"Tk unavailable: {exc}")
        cls.app.withdraw()
        # Guard rails: nothing in this class may reach the real API.
        cls.app.refresh_dashboard = lambda: None
        cls.app._client = no_network

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()

    def setUp(self):
        self.errors: list[BaseException] = []
        self.app.report_callback_exception = lambda exc, value, tb: self.errors.append(value)
        threads = mock.patch.object(gui.threading, "Thread", InlineThread)
        threads.start()
        self.addCleanup(threads.stop)
        if gui.SCORE_HISTORY_PATH.exists():
            gui.SCORE_HISTORY_PATH.unlink()
        self.app.active_cycle = None
        self.app.show_dashboard()

    def wait_until_idle(self, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.update()
            if not self.app.busy:
                return
            time.sleep(0.02)
        self.fail("background task did not finish")

    def clear_activity(self):
        self.app.activity.configure(state="normal")
        self.app.activity.delete("1.0", "end")
        self.app.activity.configure(state="disabled")

    # Activity log -----------------------------------------------------------------

    def test_genuine_failure_is_highlighted(self):
        self.clear_activity()
        self.app.log_queue.put("✗ Operation failed: boom")
        self.app._poll_log_queue()
        self.assertNotEqual(self.app.activity._textbox.tag_ranges("failure"), ())

    def test_service_error_logs_are_marked_as_failures(self):
        destination = queue.Queue()
        handler = gui.QueueLogHandler(destination)
        handler.emit(logging.LogRecord("ssc", logging.ERROR, __file__, 1, "Failed adding %s", ("a.com",), None))
        handler.emit(logging.LogRecord("ssc", logging.INFO, __file__, 1, "Added %s", ("b.com",), None))
        self.assertEqual([destination.get_nowait(), destination.get_nowait()], ["✗ Failed adding a.com", "Added b.com"])

    def test_successful_cycle_summary_is_not_highlighted_as_failure(self):
        self.clear_activity()
        self.app.log_queue.put("✓ Portfolio cycle complete: 2 added, 1 removed, 0 failed.")
        self.app._poll_log_queue()
        self.assertEqual(
            self.app.activity._textbox.tag_ranges("failure"),
            (),
            "a success message is rendered red because it contains ' failed'",
        )

    # Pages -------------------------------------------------------------------------

    def test_cycle_label_matches_configured_cycle(self):
        companies = [Company(domain, domain) for domain in target_domains(3)]
        self.assertTrue(self.app._current_cycle_label(companies).startswith("Cycle 3 — "))
        self.assertEqual(self.app.active_cycle, 3)

    def test_score_trend_search_filters_rows(self):
        self.app.current_companies = [Company("kalbe.co.id", "Kalbe", "A", 91), Company("zerpidio.com", "Zerpidio", "C", 72)]
        self.app._show_score_trends({
            "kalbe.co.id": HistoricalScoreTrend(91.0, 85.0, 6.0, None),
            "zerpidio.com": HistoricalScoreTrend(72.0, 70.0, 2.0, None),
        })
        page = self.app.trends_page
        self.assertIn("zerpidio.com", label_texts(page))

        search = next(w for w in descendants(page) if isinstance(w, ctk.CTkEntry))
        search.insert(0, "kalbe")
        self.app.update_idletasks()

        self.assertEqual(self.errors, [], "typing in the search box raised inside a Tk callback")
        texts = label_texts(page)
        self.assertIn("kalbe.co.id", texts)
        self.assertNotIn("zerpidio.com", texts)

    def test_report_page_renders_workbook_months(self):
        this_month = datetime.now(timezone.utc).replace(tzinfo=None, day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month = this_month - timedelta(days=3)
        write_history(gui.SCORE_HISTORY_PATH, [
            (last_month, "kalbe.co.id", "Kalbe", 85, "B", 1),
            (this_month, "kalbe.co.id", "Kalbe", 91, "A", 1),
            (this_month, "zerpidio.com", "Zerpidio", 65, None, 2),
        ])
        snapshots = self.app._history_by_month()
        self.assertEqual(list(snapshots), [this_month.strftime("%B %Y"), last_month.strftime("%B %Y")])
        self.app._show_report_page(snapshots)
        self.app.update_idletasks()
        self.assertEqual(self.errors, [])
        texts = label_texts(self.app.report_page)
        self.assertIn("kalbe.co.id", texts)
        self.assertIn("zerpidio.com", texts)

    def test_latest_issue_report_prefers_newest_dated_folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for day, grade in (("2026-09-03", "B"), ("2026-09-10", "A")):
            folder = root / day / "issues"
            folder.mkdir(parents=True)
            (folder / f"[{grade}] - Kalbe Farma - Issue Report - September 2026.csv").write_text("x")
        with mock.patch.object(gui, "REPORTS_DIR", root):
            found = self.app._latest_issue_report(Company("kalbe.co.id", "Kalbe Farma"))
        self.assertEqual(found.parent.parent.name, "2026-09-10")

    def test_latest_issue_report_finds_domain_suffixed_filename(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / "2026-09-14" / "issues"
        folder.mkdir(parents=True)
        for domain in ("kalventis.co.id", "kalventis.com"):
            (folder / f"[A] - Kalventis ({domain}) - Issue Report - September 2026.csv").write_text("x")
        with mock.patch.object(gui, "REPORTS_DIR", Path(tmp.name)):
            found = self.app._latest_issue_report(Company("kalventis.com", "Kalventis"))
        self.assertEqual(found.name, "[A] - Kalventis (kalventis.com) - Issue Report - September 2026.csv")

    # Background workflows -------------------------------------------------------------

    def test_declined_cycle_makes_no_changes(self):
        client = FakeClient([{"domain": "kalbe.co.id"}, {"domain": "old.example"}])
        with mock.patch.object(self.app, "_client", return_value=(client, "p")), mock.patch.object(
            self.app, "_ask_confirmation", return_value=False
        ):
            self.app._run_cycle(3)
            self.wait_until_idle()
        self.assertEqual((client.added, client.removed), ([], []))

    def test_confirmed_cycle_applies_plan(self):
        client = FakeClient([{"domain": d} for d in target_domains(3)] + [{"domain": "old.example"}])
        with mock.patch.object(self.app, "_client", return_value=(client, "p")), mock.patch.object(
            self.app, "_ask_confirmation", return_value=True
        ), mock.patch("Services.portfolio.time.sleep"):
            self.app._run_cycle(3)
            self.wait_until_idle()
        self.assertEqual((client.added, client.removed), ([], ["old.example"]))

    def test_score_export_for_later_cycle_skips_pinned_domains(self):
        client = FakeClient(
            [{"domain": "kalbe.co.id", "name": "Kalbe Farma"}, {"domain": "zerpidio.com", "name": "Zerpidio"}],
            {"kalbe.co.id": (92, "A"), "zerpidio.com": (81, "B")},
        )
        self.app.active_cycle = 2
        with mock.patch.object(self.app, "_client", return_value=(client, "p")):
            self.app._export_score_history()
            self.wait_until_idle()
        worksheet = load_workbook(gui.SCORE_HISTORY_PATH).active
        rows = [(r[1], r[3], r[4], r[5]) for r in worksheet.iter_rows(min_row=3, values_only=True)]
        self.assertEqual(rows, [("zerpidio.com", 81, "B", 2)])


if __name__ == "__main__":
    unittest.main()
