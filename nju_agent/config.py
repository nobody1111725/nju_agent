"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when the runtime configuration is invalid."""


@dataclass(frozen=True)
class Settings:
    """Settings shared by the CLI and future agent runtime."""

    api_key: str | None
    base_url: str
    model: str | None
    workspace: Path

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(Path.cwd() / ".env")
        workspace = Path(os.getenv("NJU_AGENT_WORKSPACE", ".")).expanduser().resolve()
        if not workspace.exists():
            raise ConfigurationError(f"Workspace does not exist: {workspace}")
        if not workspace.is_dir():
            raise ConfigurationError(f"Workspace is not a directory: {workspace}")

        base_url = os.getenv("NJU_AGENT_BASE_URL", "https://api.deepseek.com/v1").strip()
        if not base_url:
            raise ConfigurationError("NJU_AGENT_BASE_URL cannot be empty")

        return cls(
            api_key=os.getenv("NJU_AGENT_API_KEY") or None,
            base_url=base_url,
            model=os.getenv("NJU_AGENT_MODEL") or None,
            workspace=workspace,
        )


def _load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries without overwriting process variables."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key.isidentifier() and key not in os.environ:
            os.environ[key] = value
