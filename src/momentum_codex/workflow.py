"""High-level workflow orchestration for Momentum Codex."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

import requests

from .hubspot_client import HubSpotClient, TimelineEvent
from .reporting import WeeklyDealSummary, summarize_deals
from .slack_notifier import SlackNotifier


@dataclass
class LeadPayload:
    """Normalized lead data payload."""

    firstname: str
    lastname: str
    email: str
    company: Optional[str] = None
    phone: Optional[str] = None
    dealname: Optional[str] = None
    amount: Optional[float] = None
    lifecyclestage: str = "lead"
    dealstage: str = "appointmentscheduled"
    source: str = "unknown"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LeadPayload":
        return cls(
            firstname=data.get("firstname", ""),
            lastname=data.get("lastname", ""),
            email=data["email"],
            company=data.get("company"),
            phone=data.get("phone"),
            dealname=data.get("dealname"),
            amount=float(data["amount"]) if data.get("amount") not in (None, "") else None,
            lifecyclestage=data.get("lifecyclestage", "lead"),
            dealstage=data.get("dealstage", "appointmentscheduled"),
            source=data.get("source", "unknown"),
        )


class MomentumCodex:
    """Encapsulates CRM automation flows for Momentum Leads."""

    def __init__(
        self,
        hubspot: HubSpotClient,
        *,
        slack: Optional[SlackNotifier] = None,
        project_board_hook: Optional[str] = None,
    ) -> None:
        self.hubspot = hubspot
        self.slack = slack or SlackNotifier(None)
        self.project_board_hook = project_board_hook

    # ------------------------------------------------------------------
    # Lead capture / CRM sync
    def process_lead(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        lead = LeadPayload.from_dict(payload)

        contact = self.hubspot.find_contact_by_email(lead.email)
        contact_properties = {
            "firstname": lead.firstname,
            "lastname": lead.lastname,
            "email": lead.email,
            "phone": lead.phone,
            "company": lead.company,
            "lifecyclestage": lead.lifecyclestage,
        }
        if contact:
            contact_id = contact.get("id")
            self.hubspot.update_contact(contact_id, contact_properties)
        else:
            contact = self.hubspot.create_contact(contact_properties)
            contact_id = contact.get("id")

        company_id: Optional[str] = None
        if lead.company:
            company = self.hubspot.create_company({"name": lead.company})
            company_id = company.get("id")
            if contact_id:
                self.hubspot.associate_objects("contacts", contact_id, "companies", company_id, association_type=1)

        deal_properties = {
            "dealname": lead.dealname or f"{lead.firstname} {lead.lastname} - {lead.source}",
            "amount": lead.amount,
            "dealstage": lead.dealstage,
            "lifecyclestage": lead.lifecyclestage,
            "pipeline": "default",
            "source": lead.source,
        }
        associations: Dict[int, List[str]] = {}
        if contact_id:
            associations[3] = [contact_id]  # Contacts to deals association type
        if company_id:
            associations[341] = [company_id]  # Companies to deals association type
        deal = self.hubspot.create_deal(deal_properties, associations=associations or None)

        self._notify_new_deal(lead, deal)
        self._log_internal_note(contact_id, lead)
        return deal

    def _notify_new_deal(self, lead: LeadPayload, deal: Dict[str, Any]) -> None:
        dealname = deal.get("properties", {}).get("dealname") or lead.dealname or "Unnamed Deal"
        amount_raw = deal.get("properties", {}).get("amount")
        try:
            amount_val = float(amount_raw) if amount_raw is not None else lead.amount
        except (TypeError, ValueError):
            amount_val = lead.amount
        message = self.slack.format_new_deal_message(
            dealname=dealname,
            amount=amount_val,
            owner=f"{lead.firstname} {lead.lastname}",
            source=lead.source,
        )
        self.slack.send(message)
        if self.project_board_hook:
            self._sync_project_board(dealname, lead)

    def _sync_project_board(self, dealname: str, lead: LeadPayload) -> None:
        if not self.project_board_hook:
            return
        payload = {
            "dealname": dealname,
            "contact": f"{lead.firstname} {lead.lastname}",
            "email": lead.email,
            "stage": lead.dealstage,
            "source": lead.source,
        }
        requests.post(self.project_board_hook, json=payload, timeout=10)

    def _log_internal_note(self, contact_id: Optional[str], lead: LeadPayload) -> None:
        if not contact_id:
            return
        note = f"Lead captured on {datetime.now(UTC):%Y-%m-%d} via {lead.source}."
        self.log_touchpoint(contact_id, event_type="note", note=note)

    # ------------------------------------------------------------------
    # Touchpoint logging
    def log_touchpoint(self, object_id: str, *, event_type: str, note: str, occurred_at: Optional[datetime] = None) -> None:
        event = TimelineEvent(
            object_id=object_id,
            event_template_id="momentum-touchpoint",
            event_type=event_type,
            occurred_at=occurred_at or datetime.now(UTC),
            tokens={"note": note},
        )
        self.hubspot.log_timeline_event(event)

    # ------------------------------------------------------------------
    # Reporting
    def generate_weekly_report(self, *, anchor: Optional[datetime] = None) -> WeeklyDealSummary:
        anchor = anchor or datetime.now(UTC)
        deals = self.hubspot.fetch_weekly_summary(anchor)
        summary = summarize_deals(deals, generated_at=anchor)
        return summary
