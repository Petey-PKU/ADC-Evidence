from __future__ import annotations
from tests.support import WorkspaceTemporaryDirectory

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from adc_evidence.config import environment_flag, load_local_environment


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

    def test_explicit_env_file_is_loaded_without_override(self) -> None:
        with WorkspaceTemporaryDirectory() as temporary:
            env_path = Path(temporary) / ".env"
            env_path.write_text("SECRET=value\n", encoding="utf-8")
            calls = []
            fake_dotenv = SimpleNamespace(
                load_dotenv=lambda path, override: calls.append((path, override))
            )
            with patch.dict(
                os.environ,
                {"ADC_ENV_FILE": str(env_path)},
                clear=True,
            ), patch.dict("sys.modules", {"dotenv": fake_dotenv}):
                load_local_environment()
            self.assertEqual(calls, [(env_path, False)])

    def test_missing_explicit_env_file_fails_without_echoing_path(self) -> None:
        secret_path = "C:/private/location/.env"
        with patch.dict(
            os.environ,
            {"ADC_ENV_FILE": secret_path},
            clear=True,
        ):
            with self.assertRaises(RuntimeError) as context:
                load_local_environment()
        self.assertNotIn(secret_path, str(context.exception))


if __name__ == "__main__":
    unittest.main()
