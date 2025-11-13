from __future__ import annotations

from datetime import UTC, datetime
from typing import Dict
from unittest.mock import ANY, MagicMock

import pytest

from momentum_codex.reporting import summarize_deals
from momentum_codex.workflow import MomentumCodex


@pytest.fixture()
def sample_lead_payload() -> Dict[str, str]:
    return {
        "firstname": "David",
        "lastname": "Lamb",
        "email": "david@example.com",
        "company": "Momentum Leads LLC",
        "phone": "8653837990",
        "dealname": "Momentum Sites AI Setup",
        "amount": "1499",
        "lifecyclestage": "customer",
        "dealstage": "appointmentscheduled",
        "source": "webform",
    }


def test_process_lead_creates_records(sample_lead_payload: Dict[str, str]) -> None:
    hubspot = MagicMock()
    hubspot.find_contact_by_email.return_value = None
    hubspot.create_contact.return_value = {"id": "123"}
    hubspot.create_company.return_value = {"id": "456"}
    hubspot.create_deal.return_value = {"id": "789", "properties": {"dealname": "Momentum Sites AI Setup", "amount": "1499"}}

    slack = MagicMock()
    slack.format_new_deal_message.return_value = "New deal message"

    codex = MomentumCodex(hubspot, slack=slack)
    codex.process_lead(sample_lead_payload)

    hubspot.create_contact.assert_called_once()
    hubspot.update_contact.assert_not_called()
    hubspot.create_company.assert_called_once_with({"name": "Momentum Leads LLC"})
    hubspot.associate_objects.assert_called_once()
    hubspot.create_deal.assert_called_once()
    slack.format_new_deal_message.assert_called_once()
    slack.send.assert_called_once_with("New deal message")
    hubspot.log_timeline_event.assert_called_once()


def test_process_lead_updates_existing_contact(sample_lead_payload: Dict[str, str]) -> None:
    hubspot = MagicMock()
    hubspot.find_contact_by_email.return_value = {"id": "321"}
    hubspot.create_deal.return_value = {"id": "789", "properties": {"dealname": "Momentum Sites AI Setup"}}

    slack = MagicMock()
    slack.format_new_deal_message.return_value = "message"

    codex = MomentumCodex(hubspot, slack=slack)
    codex.process_lead(sample_lead_payload)

    hubspot.update_contact.assert_called_once_with("321", ANY)
    hubspot.create_contact.assert_not_called()
    hubspot.create_deal.assert_called_once()


def test_generate_weekly_report_aggregates_data() -> None:
    hubspot = MagicMock()
    deals = [
        {"properties": {"dealstage": "closedwon", "amount": "1499"}},
        {"properties": {"dealstage": "closedwon", "amount": "999"}},
        {"properties": {"dealstage": "closedlost", "amount": "0"}},
    ]
    hubspot.fetch_weekly_summary.return_value = deals

    slack = MagicMock()
    codex = MomentumCodex(hubspot, slack=slack)
    summary = codex.generate_weekly_report(anchor=datetime(2024, 3, 1, tzinfo=UTC))

    assert summary.total_deals == 3
    assert summary.by_stage["closedwon"] == 2
    assert summary.total_amount == pytest.approx(2498.0)


def test_summarize_deals_handles_invalid_amounts() -> None:
    deals = [
        {"properties": {"dealstage": "closedwon", "amount": "1000"}},
        {"properties": {"dealstage": "appointmentscheduled", "amount": "invalid"}},
    ]
    summary = summarize_deals(deals, generated_at=datetime.now(UTC))
    assert summary.total_deals == 2
    assert summary.by_stage["closedwon"] == 1
    assert summary.by_stage["appointmentscheduled"] == 1
    assert summary.total_amount == pytest.approx(1000.0)
