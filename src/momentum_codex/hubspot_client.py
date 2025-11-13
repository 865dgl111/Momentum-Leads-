"""HubSpot API client abstractions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

import requests


class HubSpotError(RuntimeError):
    """Raised when the HubSpot API returns an error."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, payload: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


@dataclass
class TimelineEvent:
    """Representation of a timeline event to log to HubSpot."""

    object_id: str
    event_template_id: str
    event_type: str
    occurred_at: datetime
    tokens: Dict[str, Any]

    def to_payload(self) -> Dict[str, Any]:
        return {
            "eventTemplateId": self.event_template_id,
            "eventType": self.event_type,
            "objectId": self.object_id,
            "occurredAt": self.occurred_at.isoformat(),
            "tokens": self.tokens,
        }


class HubSpotClient:
    """Lightweight HubSpot REST client."""

    def __init__(self, access_token: str, *, base_url: str = "https://api.hubapi.com", timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Low-level helpers
    def _request(self, method: str, path: str, *, expected: Iterable[int] = (200, 201, 204), **kwargs: Any) -> Any:
        url = urljoin(self.base_url, path.lstrip("/"))
        response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        if response.status_code not in expected:
            detail: Dict[str, Any]
            try:
                detail = response.json()
            except ValueError:
                detail = {"body": response.text}
            raise HubSpotError(
                f"HubSpot API error ({response.status_code}) for {method} {url}",
                status_code=response.status_code,
                payload=detail,
            )
        if response.content:
            try:
                return response.json()
            except ValueError:
                return response.text
        return None

    # ------------------------------------------------------------------
    # CRM objects
    def find_contact_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "email",
                            "operator": "EQ",
                            "value": email,
                        }
                    ]
                }
            ],
            "properties": ["firstname", "lastname", "email", "phone", "company", "lifecyclestage"],
            "limit": 1,
        }
        result = self._request("POST", "crm/v3/objects/contacts/search", json=payload)
        hits: List[Dict[str, Any]] = result.get("results", []) if isinstance(result, dict) else []
        return hits[0] if hits else None

    def create_contact(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "crm/v3/objects/contacts", json={"properties": properties})

    def update_contact(self, contact_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("PATCH", f"crm/v3/objects/contacts/{contact_id}", json={"properties": properties})

    def create_company(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "crm/v3/objects/companies", json={"properties": properties})

    def create_deal(self, properties: Dict[str, Any], *, associations: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
        data: Dict[str, Any] = {"properties": properties}
        if associations:
            data["associations"] = [
                {"to": {"id": assoc_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": int(type_id)}]}
                for type_id, ids in associations.items()
                for assoc_id in ids
            ]
        return self._request("POST", "crm/v3/objects/deals", json=data)

    def update_deal_stage(self, deal_id: str, stage: str) -> Dict[str, Any]:
        return self._request("PATCH", f"crm/v3/objects/deals/{deal_id}", json={"properties": {"dealstage": stage}})

    def associate_objects(self, from_object: str, from_id: str, to_object: str, to_id: str, association_type: int) -> None:
        self._request(
            "PUT",
            f"crm/v4/associations/{from_object}/{to_object}/batch/associate",
            json={
                "inputs": [
                    {
                        "from": {"id": from_id},
                        "to": {"id": to_id},
                        "types": [
                            {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": association_type,
                            }
                        ],
                    }
                ]
            },
            expected=(200, 204),
        )

    # ------------------------------------------------------------------
    # Timeline + reporting
    def log_timeline_event(self, event: TimelineEvent) -> None:
        path = f"crm/v3/timeline/events/{event.object_id}"
        self._request("POST", path, json=event.to_payload(), expected=(200, 201))

    def fetch_deals_updated_since(self, since: datetime) -> List[Dict[str, Any]]:
        query = json.dumps({"filters": [{"propertyName": "hs_lastmodifieddate", "operator": "GTE", "value": since.isoformat()}]})
        result = self._request(
            "GET",
            f"crm/v3/objects/deals?limit=100&properties=dealstage,amount,closedate,dealname&filterGroups={query}",
        )
        return result.get("results", []) if isinstance(result, dict) else []

    def fetch_deals_in_period(self, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "closedate",
                            "operator": "BETWEEN",
                            "value": start.isoformat(),
                            "highValue": end.isoformat(),
                        }
                    ]
                }
            ],
            "properties": ["dealstage", "amount", "dealname"],
            "limit": 100,
        }
        result = self._request("POST", "crm/v3/objects/deals/search", json=payload)
        return result.get("results", []) if isinstance(result, dict) else []

    def fetch_weekly_summary(self, anchor: Optional[datetime] = None) -> List[Dict[str, Any]]:
        anchor = anchor or datetime.now(UTC)
        start_of_week = anchor - timedelta(days=anchor.weekday())
        end_of_week = start_of_week + timedelta(days=7)
        return self.fetch_deals_in_period(start_of_week, end_of_week)
