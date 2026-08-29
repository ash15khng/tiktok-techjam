from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shopping_copilot.environment import load_runtime_environment


class EnvironmentLoaderTest(unittest.TestCase):
    def test_loads_only_approved_values_and_preserves_os_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "secrets.env"
            env_file.write_text(
                "\n".join(
                    (
                        "SHOPPING_COPILOT_LLM_ENABLED=1",
                        "SHOPPING_COPILOT_LLM_MODEL='llama3.1:8b'",
                        "SOCLAAS_BASE_URL=https://gateway.example/v1",
                        "SOCLAAS_API_KEY=file-secret",
                        "UNAPPROVED_VARIABLE=must-not-load",
                    )
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"SOCLAAS_API_KEY": "os-secret"}, clear=True):
                loaded = load_runtime_environment(env_file)

                self.assertEqual(loaded, env_file)
                self.assertEqual(os.environ["SOCLAAS_API_KEY"], "os-secret")
                self.assertEqual(os.environ["SHOPPING_COPILOT_LLM_MODEL"], "llama3.1:8b")
                self.assertNotIn("UNAPPROVED_VARIABLE", os.environ)

    def test_missing_explicit_file_does_not_fall_back_to_repository_env(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.env"
            with patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(load_runtime_environment(missing))
                self.assertNotIn("SOCLAAS_API_KEY", os.environ)


if __name__ == "__main__":
    unittest.main()
