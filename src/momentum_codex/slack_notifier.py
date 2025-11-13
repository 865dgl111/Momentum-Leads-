"""Slack notification helper."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests


class SlackNotifier:
    """Send deal notifications to Slack using an incoming webhook."""

    def __init__(self, webhook_url: Optional[str]) -> None:
        self.webhook_url = webhook_url

    def send(self, text: str, *, blocks: Optional[Dict[str, Any]] = None) -> None:
        if not self.webhook_url:
            return
        payload: Dict[str, Any] = {"text": text}
        if blocks:
            payload["blocks"] = blocks
        response = requests.post(self.webhook_url, data=json.dumps(payload), timeout=10)
        response.raise_for_status()

    def format_new_deal_message(self, *, dealname: str, amount: Optional[float], owner: str, source: str) -> str:
        amount_text = f"${amount:,.2f}" if amount is not None else "N/A"
        return f"New deal booked: {dealname} ({amount_text}) by {owner} via {source}."

    def format_stage_change_message(self, *, dealname: str, stage: str) -> str:
        return f"Deal '{dealname}' moved to stage {stage}."
