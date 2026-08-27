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
