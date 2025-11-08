"""Stripe webhook processing that logs successful payments into HubSpot."""
from __future__ import annotations

import hmac
import json
import logging
import os
from dataclasses import dataclass
from hashlib import sha256
from typing import Dict, Optional

import requests


logger = logging.getLogger(__name__)


@dataclass
class StripeWebhookConfig:
    signing_secret: str
    hubspot_access_token: str
    hubspot_base_url: str = "https://api.hubapi.com"


class StripeWebhookHandler:
    """Validate Stripe webhook requests and create HubSpot timeline events."""

    def __init__(self, config: StripeWebhookConfig) -> None:
        self._config = config

    def verify_signature(self, payload: bytes, signature: str, tolerance: int = 300) -> bool:
        """Validate that the provided signature matches the payload."""

        try:
            timestamp, received_signature = signature.split(",", 1)[1].split("=", 1)
        except ValueError as exc:  # pragma: no cover - defensive parsing
            raise ValueError("Invalid Stripe signature header") from exc
        message = f"{timestamp}.{payload.decode()}".encode()
        computed = hmac.new(self._config.signing_secret.encode(), msg=message, digestmod=sha256).hexdigest()
        is_valid = hmac.compare_digest(computed, received_signature)
        if not is_valid:
            logger.warning("Signature verification failed")
        return is_valid

    def handle_event(self, event: Dict) -> Optional[str]:
        """Process a Stripe event. Returns HubSpot id when a note is created."""

        event_type = event.get("type")
        if event_type not in {"checkout.session.completed", "invoice.payment_succeeded"}:
            logger.info("Ignoring irrelevant event type %s", event_type)
            return None
        data_object = event.get("data", {}).get("object", {})
        customer_email = data_object.get("customer_details", {}).get("email") or data_object.get("customer_email")
        if not customer_email:
            logger.info("Skipping event with no customer email")
            return None
        amount = data_object.get("amount_total") or data_object.get("amount_paid")
        note = self._build_note_body(event_type, amount, data_object)
        contact_id = self._find_contact_id(customer_email)
        if not contact_id:
            logger.info("HubSpot contact not found for %s", customer_email)
            return None
        return self._create_timeline_note(contact_id, note)

    def _build_note_body(self, event_type: str, amount: Optional[int], data_object: Dict) -> str:
        amount_display = f"$ {amount / 100:.2f}" if amount else "unknown amount"
        deal_name = data_object.get("metadata", {}).get("dealname", "Payment")
        return f"Stripe event `{event_type}` logged for {deal_name} totalling {amount_display}."

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.hubspot_access_token}",
            "Content-Type": "application/json",
        }

    def _find_contact_id(self, email: str) -> Optional[str]:
        response = requests.get(
            f"{self._config.hubspot_base_url}/crm/v3/objects/contacts/search",
            headers=self._headers,
            json={
                "filterGroups": [
                    {
                        "filters": [
                            {"propertyName": "email", "operator": "EQ", "value": email}
                        ]
                    }
                ],
                "limit": 1,
            },
            timeout=20,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        if not results:
            return None
        return results[0]["id"]

    def _create_timeline_note(self, contact_id: str, note: str) -> str:
        response = requests.post(
            f"{self._config.hubspot_base_url}/crm/v3/objects/notes",
            headers=self._headers,
            json={"properties": {"hs_note_body": note}},
            timeout=20,
        )
        response.raise_for_status()
        note_id = response.json()["id"]
        requests.put(
            f"{self._config.hubspot_base_url}/crm/v3/objects/notes/{note_id}/associations/contact/{contact_id}/notes_to_contacts",
            headers=self._headers,
            timeout=20,
        ).raise_for_status()
        return note_id


def load_config_from_env() -> StripeWebhookConfig:
    return StripeWebhookConfig(
        signing_secret=os.environ["STRIPE_SIGNING_SECRET"],
        hubspot_access_token=os.environ["HUBSPOT_ACCESS_TOKEN"],
        hubspot_base_url=os.environ.get("HUBSPOT_BASE_URL", "https://api.hubapi.com"),
    )


def main(payload: str, signature_header: str) -> Optional[str]:
    logging.basicConfig(level=logging.INFO)
    config = load_config_from_env()
    handler = StripeWebhookHandler(config)
    if not handler.verify_signature(payload.encode(), signature_header):
        raise ValueError("Invalid Stripe signature")
    event = json.loads(payload)
    return handler.handle_event(event)


if __name__ == "__main__":
    raise SystemExit("This module is intended to be imported and used by a webhook server.")
