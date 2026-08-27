import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nju_agent.config import ConfigurationError, Settings


class SettingsTests(unittest.TestCase):
    def test_settings_load_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                "NJU_AGENT_API_KEY": "test-key",
                "NJU_AGENT_BASE_URL": "https://example.test/v1",
                "NJU_AGENT_MODEL": "test-model",
                "NJU_AGENT_WORKSPACE": directory,
            }
            with patch.dict(os.environ, environment, clear=True):
                settings = Settings.from_env()

            self.assertEqual(settings.api_key, "test-key")
            self.assertEqual(settings.base_url, "https://example.test/v1")
            self.assertEqual(settings.model, "test-model")
            self.assertEqual(settings.workspace, Path(directory).resolve())

    def test_settings_reject_missing_workspace(self) -> None:
        environment = {"NJU_AGENT_WORKSPACE": os.path.join("missing", "workspace")}
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "does not exist"):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()

