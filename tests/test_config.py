from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from adc_evidence.config import environment_flag


class EnvironmentFlagTests(unittest.TestCase):
    def test_true_and_false_values(self) -> None:
        for value in ("1", "true", "YES", "on"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"TEST_FLAG": value}
            ):
                self.assertTrue(environment_flag("TEST_FLAG"))
        for value in ("0", "false", "NO", "off"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"TEST_FLAG": value}
            ):
                self.assertFalse(environment_flag("TEST_FLAG", default=True))

    def test_missing_value_uses_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(environment_flag("TEST_FLAG", default=True))

    def test_invalid_value_fails_fast(self) -> None:
        with patch.dict(os.environ, {"TEST_FLAG": "tru"}):
            with self.assertRaises(ValueError):
                environment_flag("TEST_FLAG")


if __name__ == "__main__":
    unittest.main()
