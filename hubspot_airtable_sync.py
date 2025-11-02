"""Utilities for synchronising HubSpot contacts with Airtable tables.

This module orchestrates a two way sync between Airtable and HubSpot with a
focus on contact level data.  It intentionally keeps the public API small and
well typed so it can be dropped into automation scripts or scheduled jobs.

The implementation does not perform any destructive writes by default.  When a
record already exists in HubSpot the synchroniser updates only the fields that
are provided by Airtable.  It emits granular logging so that the calling worker
can observe the progress of each batch of records.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, MutableMapping, Optional

import requests


logger = logging.getLogger(__name__)


@dataclass
class HubSpotContact:
    """Representation of the properties HubSpot expects for a contact."""

    email: str
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    lifecycle_stage: Optional[str] = None
    custom_properties: MutableMapping[str, Optional[str]] = field(default_factory=dict)

    def to_hubspot_payload(self) -> Dict[str, Optional[str]]:
        """Convert the dataclass to the dictionary used by the HubSpot API."""

        payload: Dict[str, Optional[str]] = {
            "email": self.email,
        }
        optional_fields = {
            "firstname": self.firstname,
            "lastname": self.lastname,
            "phone": self.phone,
            "company": self.company,
            "lifecyclestage": self.lifecycle_stage,
        }
        payload.update({k: v for k, v in optional_fields.items() if v})
        payload.update({k: v for k, v in self.custom_properties.items() if v})
        return payload


class HubSpotClient:
    """Minimal HubSpot client for contact level operations."""

    def __init__(self, access_token: str, base_url: str = "https://api.hubapi.com") -> None:
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def find_contact_by_email(self, email: str) -> Optional[str]:
        """Return the contact id for the provided email if it exists."""

        response = requests.get(
            f"{self._base_url}/crm/v3/objects/contacts",
            headers=self._headers,
            params={"email": email, "properties": "email"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        if not results:
            return None
        return results[0]["id"]

    def create_contact(self, contact: HubSpotContact) -> str:
        response = requests.post(
            f"{self._base_url}/crm/v3/objects/contacts",
            headers=self._headers,
            json={"properties": contact.to_hubspot_payload()},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()["id"]

    def update_contact(self, contact_id: str, properties: Dict[str, Optional[str]]) -> None:
        response = requests.patch(
            f"{self._base_url}/crm/v3/objects/contacts/{contact_id}",
            headers=self._headers,
            json={"properties": properties},
            timeout=20,
        )
        response.raise_for_status()


class AirtableClient:
    """Lightweight Airtable client focussed on list/update operations."""

    def __init__(self, base_id: str, api_key: str, base_url: str = "https://api.airtable.com/v0") -> None:
        self._base_url = base_url.rstrip("/")
        self._base_id = base_id
        self._headers = {
            "Authorization": f"Bearer {api_key}",
        }

    def list_records(self, table: str, modified_since: Optional[str] = None) -> Iterable[Dict]:
        """Yield all records for the table optionally filtered by modified time."""

        params: Dict[str, str] = {}
        if modified_since:
            params["filterByFormula"] = f"DATETIME_COMPARE(LAST_MODIFIED_TIME(), '{modified_since}') >= 0"
        offset: Optional[str] = None
        while True:
            if offset:
                params["offset"] = offset
            response = requests.get(
                f"{self._base_url}/{self._base_id}/{table}",
                headers=self._headers,
                params=params,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            for record in data.get("records", []):
                yield record
            offset = data.get("offset")
            if not offset:
                break

    def update_record(self, table: str, record_id: str, fields: Dict[str, Optional[str]]) -> None:
        response = requests.patch(
            f"{self._base_url}/{self._base_id}/{table}/{record_id}",
            headers={**self._headers, "Content-Type": "application/json"},
            json={"fields": fields},
            timeout=20,
        )
        response.raise_for_status()


@dataclass
class SyncConfig:
    airtable_base_id: str
    airtable_table: str
    airtable_api_key: str
    hubspot_access_token: str
    field_mapping: Dict[str, str]
    modified_since: Optional[str] = None
    dry_run: bool = False


class HubSpotAirtableSync:
    """Coordinate reading Airtable records and updating HubSpot contacts."""

    def __init__(self, config: SyncConfig) -> None:
        self._config = config
        self._hubspot = HubSpotClient(access_token=config.hubspot_access_token)
        self._airtable = AirtableClient(
            base_id=config.airtable_base_id,
            api_key=config.airtable_api_key,
        )

    def _convert_record(self, record: Dict) -> HubSpotContact:
        fields = record.get("fields", {})
        email = fields.get(self._config.field_mapping.get("email", "email"))
        if not email:
            raise ValueError("Airtable record missing required email field")
        custom: Dict[str, Optional[str]] = {}
        for airtable_field, hubspot_field in self._config.field_mapping.items():
            if hubspot_field in {"email", "firstname", "lastname", "phone", "company", "lifecyclestage"}:
                continue
            custom[hubspot_field] = fields.get(airtable_field)
        return HubSpotContact(
            email=email,
            firstname=fields.get(self._config.field_mapping.get("firstname", "firstname")),
            lastname=fields.get(self._config.field_mapping.get("lastname", "lastname")),
            phone=fields.get(self._config.field_mapping.get("phone", "phone")),
            company=fields.get(self._config.field_mapping.get("company", "company")),
            lifecycle_stage=fields.get(self._config.field_mapping.get("lifecyclestage", "lifecyclestage")),
            custom_properties=custom,
        )

    def sync(self) -> List[str]:
        """Synchronise Airtable records into HubSpot returning processed ids."""

        processed: List[str] = []
        for record in self._airtable.list_records(self._config.airtable_table, self._config.modified_since):
            record_id = record.get("id")
            try:
                contact = self._convert_record(record)
            except ValueError as error:
                logger.warning("Skipping record %s: %s", record_id, error)
                continue
            logger.info("Processing Airtable record %s for %s", record_id, contact.email)
            if self._config.dry_run:
                processed.append(record_id)
                continue
            hubspot_id = self._hubspot.find_contact_by_email(contact.email)
            payload = contact.to_hubspot_payload()
            if hubspot_id:
                self._hubspot.update_contact(hubspot_id, payload)
                logger.debug("Updated HubSpot contact %s", hubspot_id)
            else:
                hubspot_id = self._hubspot.create_contact(contact)
                logger.debug("Created HubSpot contact %s", hubspot_id)
            processed.append(record_id)
            time.sleep(0.2)  # avoid throttling
        return processed


def load_config_from_env(field_mapping: Dict[str, str]) -> SyncConfig:
    """Helper for quickly constructing :class:`SyncConfig` from env vars."""

    base_id = os.environ["AIRTABLE_BASE_ID"]
    table = os.environ.get("AIRTABLE_TABLE", "Contacts")
    api_key = os.environ["AIRTABLE_API_KEY"]
    access_token = os.environ["HUBSPOT_ACCESS_TOKEN"]
    modified_since = os.environ.get("AIRTABLE_MODIFIED_SINCE")
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    return SyncConfig(
        airtable_base_id=base_id,
        airtable_table=table,
        airtable_api_key=api_key,
        hubspot_access_token=access_token,
        field_mapping=field_mapping,
        modified_since=modified_since,
        dry_run=dry_run,
    )


def default_field_mapping() -> Dict[str, str]:
    """Return a conservative default mapping for Airtable -> HubSpot fields."""

    return {
        "Email": "email",
        "First Name": "firstname",
        "Last Name": "lastname",
        "Phone": "phone",
        "Company": "company",
        "Lifecycle Stage": "lifecyclestage",
        "Lead Source": "source",
    }


def run() -> None:
    """Entry point used by scripts or cron jobs."""

    logging.basicConfig(level=logging.INFO)
    config = load_config_from_env(default_field_mapping())
    synchroniser = HubSpotAirtableSync(config)
    processed = synchroniser.sync()
    logger.info("Sync complete: %s records processed", len(processed))


if __name__ == "__main__":
    run()
