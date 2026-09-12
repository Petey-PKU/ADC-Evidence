from __future__ import annotations

import unittest

from adc_evidence.evaluation.public_hygiene import scan_public_text


class PublicHygieneTests(unittest.TestCase):
    def test_safe_text_has_no_findings(self) -> None:
        self.assertEqual(scan_public_text("README.md", "offline evaluation only"), [])

    def test_reports_categories_without_secret_values(self) -> None:
        secret = "sk-" + "abcdefghijklmnopqrstuvwxyz"
        findings = scan_public_text("example.txt", f"{secret} C:\\Users\\alice\\secret.txt")
        self.assertEqual({item["kind"] for item in findings}, {"api_key", "local_path"})
        self.assertNotIn(secret, str(findings))


if __name__ == "__main__":
    unittest.main()
