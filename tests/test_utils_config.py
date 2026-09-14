import tempfile
import unittest
from pathlib import Path

import yaml

from tests import PROJECT_DIR
import utils
from config import load_config, validate_ssc_config


class FilenameTest(unittest.TestCase):
    def test_sanitize_replaces_windows_invalid_characters(self):
        self.assertEqual(utils.sanitize_filename('a<b>:c"/d\\e|f?g*h'), "a_b_c_d_e_f_g_h")

    def test_sanitize_trims_trailing_dots_and_spaces(self):
        self.assertEqual(utils.sanitize_filename("  Kalbe   Farma... "), "Kalbe Farma")

    def test_sanitize_falls_back_to_unknown(self):
        self.assertEqual(utils.sanitize_filename(""), "Unknown")
        self.assertEqual(utils.sanitize_filename("..."), "Unknown")

    def test_make_filename(self):
        self.assertEqual(
            utils.make_filename("A", "Kalbe/Farma", "September 2026", "issue_report", extension=".csv"),
            "[A] - Kalbe_Farma - Issue Report - September 2026.csv",
        )


class NormalizeDomainTest(unittest.TestCase):
    def test_strips_whitespace_case_and_zero_width_characters(self):
        self.assertEqual(utils.normalize_domain(" Kalgendna.CO.id​﻿ "), "kalgendna.co.id")


class ConfigTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_load_config_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_config(self.dir / "missing.yaml")

    def test_load_config_empty_file(self):
        path = self.dir / "config.yaml"
        path.write_text("", encoding="utf-8")
        self.assertEqual(load_config(path), {})

    def test_validate_returns_trimmed_credentials(self):
        config = {"securityscorecard": {"api_key": " key ", "portfolio_id": " pid "}}
        self.assertEqual(validate_ssc_config(config), ("key", "pid"))

    def test_validate_rejects_missing_key(self):
        with self.assertRaises(ValueError):
            validate_ssc_config({"securityscorecard": {"portfolio_id": "pid"}})

    def test_validate_rejects_unfilled_config_template(self):
        """Copying config_template.yaml without filling it in must be rejected."""
        template = yaml.safe_load((PROJECT_DIR / "config_template.yaml").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            validate_ssc_config(template)

    def test_validate_rejects_empty_securityscorecard_section(self):
        with self.assertRaises(ValueError):
            validate_ssc_config(yaml.safe_load("securityscorecard:\n"))

    def test_validate_rejects_readme_placeholder(self):
        config = {"securityscorecard": {"api_key": "YOUR_API_KEY", "portfolio_id": "YOUR_PORTFOLIO_ID"}}
        with self.assertRaises(ValueError):
            validate_ssc_config(config)


if __name__ == "__main__":
    unittest.main()
