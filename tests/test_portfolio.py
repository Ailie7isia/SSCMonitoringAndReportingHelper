import io
import logging
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tests.fakes import FakeClient
import constants
from models import Company, PortfolioPlan
from Services import portfolio
from Services.cycle import run_cycle

PINNED = {"Kalbe.co.id"}
VENDORS = {1: ["a.com", "B.com"], 2: ["c.com"]}
LABELS = {1: "One", 2: "Two"}


class PatchedConstantsTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.multiple(
            "Services.portfolio", ALWAYS_PINNED=PINNED, OPTION_VENDORS=VENDORS, OPTION_LABELS=LABELS
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)


class PortfolioLogicTest(PatchedConstantsTest):
    def test_companies_from_payload_normalizes_and_falls_back(self):
        companies = portfolio.companies_from_payload([
            {"domain": " Kalbe.CO.ID ", "name": "Kalbe Farma", "grade": "a"},
            {"website": "b.com", "current_grade": "c"},
            {"name": "no domain"},
        ])
        self.assertEqual(
            companies,
            [Company("kalbe.co.id", "Kalbe Farma", "A"), Company("b.com", "b.com", "C")],
        )

    def test_target_domains_includes_pinned(self):
        self.assertEqual(portfolio.target_domains(2), {"kalbe.co.id", "c.com"})

    def test_target_domains_rejects_unknown_cycle(self):
        with self.assertRaises(ValueError):
            portfolio.target_domains(99)

    def test_compute_plan_never_removes_pinned(self):
        current = [Company("kalbe.co.id", "Kalbe"), Company("a.com", "A"), Company("old.com", "Old")]
        plan = portfolio.compute_plan(current, portfolio.target_domains(2))
        self.assertEqual(plan, PortfolioPlan(to_add=["c.com"], to_remove=["a.com", "old.com"]))

    def test_cycle_action_excludes_pinned_after_cycle_one(self):
        companies = [Company("kalbe.co.id", "Kalbe"), Company("c.com", "C")]
        self.assertEqual(portfolio.companies_for_cycle_action(companies, None), companies)
        self.assertEqual(portfolio.companies_for_cycle_action(companies, 1), companies)
        self.assertEqual(portfolio.companies_for_cycle_action(companies, 2), [Company("c.com", "C")])

    def test_apply_plan_continues_after_failures(self):
        client = FakeClient()
        client.fail_remove = {"a.com"}
        client.fail_add = {"c.com"}
        report = portfolio.apply_plan(
            client, "p", PortfolioPlan(to_add=["c.com", "d.com"], to_remove=["a.com", "b.com"]), pause_seconds=0
        )
        self.assertEqual(report.removed_ok, ["b.com"])
        self.assertEqual(report.added_ok, ["d.com"])
        self.assertEqual([domain for domain, _ in report.removed_failed], ["a.com"])
        self.assertEqual([domain for domain, _ in report.added_failed], ["c.com"])
        self.assertTrue(report.has_failures)


class RunCycleTest(PatchedConstantsTest):
    def client(self):
        return FakeClient([{"domain": "kalbe.co.id"}, {"domain": "a.com"}, {"domain": "old.com"}])

    def test_dry_run_changes_nothing(self):
        client = self.client()
        with redirect_stdout(io.StringIO()):
            run_cycle(client, "p", option=2, dry_run=True, pause_seconds=0)
        self.assertEqual((client.added, client.removed), ([], []))

    def test_confirmation_requires_exact_uppercase_yes(self):
        client = self.client()
        with redirect_stdout(io.StringIO()), mock.patch("builtins.input", return_value="yes"):
            run_cycle(client, "p", option=2, pause_seconds=0)
        self.assertEqual((client.added, client.removed), ([], []))

    def test_assume_yes_applies_plan(self):
        client = self.client()
        with redirect_stdout(io.StringIO()):
            run_cycle(client, "p", option=2, assume_yes=True, pause_seconds=0)
        self.assertEqual(client.added, ["c.com"])
        self.assertEqual(client.removed, ["a.com", "old.com"])


class ConfiguredDomainsTest(unittest.TestCase):
    """Checks the operator's real constants.py."""

    def test_domains_contain_no_hidden_characters(self):
        groups = [("pinned", constants.ALWAYS_PINNED)] + [
            (f"cycle {option}", domains) for option, domains in constants.OPTION_VENDORS.items()
        ]
        for label, domains in groups:
            for domain in domains:
                with self.subTest(group=label, domain=domain):
                    self.assertTrue(
                        domain.isascii() and domain.isprintable() and domain == domain.strip(),
                        f"{domain!r} contains hidden or non-ASCII characters",
                    )

    def test_every_cycle_has_a_label(self):
        self.assertEqual(set(constants.OPTION_VENDORS), set(constants.OPTION_LABELS))


if __name__ == "__main__":
    unittest.main()
