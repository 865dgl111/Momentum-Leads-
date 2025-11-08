"""Fetch Outlook email threads and log them to HubSpot as timeline events."""
from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import requests


logger = logging.getLogger(__name__)


@dataclass
class OutlookConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    hubspot_access_token: str
    user_email: str
    hubspot_base_url: str = "https://api.hubapi.com"
    graph_base_url: str = "https://graph.microsoft.com/v1.0"


class OutlookGraphClient:
    """Small helper around the Microsoft Graph API for reading mail."""

    def __init__(self, config: OutlookConfig) -> None:
        self._config = config
        self._token: Optional[str] = None

    def _authenticate(self) -> str:
        if self._token:
            return self._token
        response = requests.post(
            f"https://login.microsoftonline.com/{self._config.tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            timeout=20,
        )
        response.raise_for_status()
        self._token = response.json()["access_token"]
        return self._token

    @property
    def _headers(self) -> Dict[str, str]:
        token = self._authenticate()
        return {"Authorization": f"Bearer {token}"}

    def list_messages(self, since: dt.datetime) -> Iterable[Dict]:
        response = requests.get(
            f"{self._config.graph_base_url}/users/{self._config.user_email}/messages",
            headers=self._headers,
            params={
                "$filter": f"receivedDateTime ge {since.isoformat()}Z",
                "$orderby": "receivedDateTime desc",
                "$top": 50,
            },
            timeout=20,
        )
        response.raise_for_status()
        for message in response.json().get("value", []):
            yield message


class HubSpotTimelineClient:
    def __init__(self, access_token: str, base_url: str) -> None:
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def find_contact_id(self, email: str) -> Optional[str]:
        response = requests.get(
            f"{self._base_url}/crm/v3/objects/contacts/search",
            headers=self._headers,
            json={
                "filterGroups": [
                    {"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}
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

    def create_email_engagement(self, contact_id: str, subject: str, body: str, received_at: dt.datetime) -> str:
        response = requests.post(
            f"{self._base_url}/engagements/v1/engagements",
            headers=self._headers,
            json={
                "engagement": {
                    "active": True,
                    "type": "EMAIL",
                    "timestamp": int(received_at.timestamp() * 1000),
                },
                "associations": {"contactIds": [contact_id]},
                "metadata": {
                    "subject": subject,
                    "text": body,
                },
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()["engagement"].get("id")


class OutlookEmailLogger:
    def __init__(self, config: OutlookConfig) -> None:
        self._config = config
        self._outlook = OutlookGraphClient(config)
        self._hubspot = HubSpotTimelineClient(
            access_token=config.hubspot_access_token,
            base_url=config.hubspot_base_url,
        )

    def _extract_recipients(self, message: Dict) -> List[str]:
        addresses: List[str] = []
        for field in ("toRecipients", "ccRecipients", "bccRecipients"):
            for recipient in message.get(field, []):
                email = recipient.get("emailAddress", {}).get("address")
                if email:
                    addresses.append(email)
        return addresses

    def log_recent_messages(self, since: dt.datetime) -> List[str]:
        created: List[str] = []
        for message in self._outlook.list_messages(since):
            recipients = self._extract_recipients(message)
            subject = message.get("subject", "(no subject)")
            body_preview = message.get("bodyPreview", "")
            received_at = dt.datetime.fromisoformat(message["receivedDateTime"].replace("Z", "+00:00"))
            for address in recipients:
                contact_id = self._hubspot.find_contact_id(address)
                if not contact_id:
                    logger.debug("No HubSpot contact for %s", address)
                    continue
                engagement_id = self._hubspot.create_email_engagement(contact_id, subject, body_preview, received_at)
                created.append(engagement_id)
        return created


def load_config_from_env() -> OutlookConfig:
    return OutlookConfig(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
        hubspot_access_token=os.environ["HUBSPOT_ACCESS_TOKEN"],
        user_email=os.environ.get("OUTLOOK_USER_EMAIL", "momentumleadsllc@outlook.com"),
        hubspot_base_url=os.environ.get("HUBSPOT_BASE_URL", "https://api.hubapi.com"),
    )


def run(hours: int = 24) -> List[str]:
    logging.basicConfig(level=logging.INFO)
    config = load_config_from_env()
    logger.info("Fetching emails from the last %s hours", hours)
    since = dt.datetime.utcnow() - dt.timedelta(hours=hours)
    email_logger = OutlookEmailLogger(config)
    created = email_logger.log_recent_messages(since)
    logger.info("Logged %s HubSpot email engagements", len(created))
    return created


if __name__ == "__main__":
    run()
