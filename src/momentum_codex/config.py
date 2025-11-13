"""Configuration helpers for Momentum Codex."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Settings:
    """Runtime configuration loaded from environment variables."""

    hubspot_access_token: str
    hubspot_base_url: str = "https://api.hubapi.com"
    slack_webhook_url: Optional[str] = None
    project_board_webhook_url: Optional[str] = None

    @classmethod
    def from_environment(cls) -> "Settings":
        """Create :class:`Settings` from environment variables."""

        access_token = os.environ.get("HUBSPOT_ACCESS_TOKEN")
        if not access_token:
            raise ValueError("HUBSPOT_ACCESS_TOKEN must be set in the environment")

        return cls(
            hubspot_access_token=access_token,
            hubspot_base_url=os.environ.get("HUBSPOT_BASE_URL", "https://api.hubapi.com"),
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL"),
            project_board_webhook_url=os.environ.get("PROJECT_BOARD_WEBHOOK_URL"),
        )


DEFAULT_SETTINGS = Settings(
    hubspot_access_token="YOUR_PRIVATE_APP_TOKEN",
    hubspot_base_url="https://api.hubapi.com",
)
"""Default settings placeholder that mirrors the system configuration."""
