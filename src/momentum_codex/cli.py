"""Command line entry points for Momentum Codex."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any, Dict

from .config import Settings
from .hubspot_client import HubSpotClient
from .slack_notifier import SlackNotifier
from .workflow import MomentumCodex


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Momentum Codex automation CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Process a new lead payload")
    ingest.add_argument("--firstname", required=True)
    ingest.add_argument("--lastname", required=True)
    ingest.add_argument("--email", required=True)
    ingest.add_argument("--company")
    ingest.add_argument("--phone")
    ingest.add_argument("--dealname")
    ingest.add_argument("--amount", type=float)
    ingest.add_argument("--lifecyclestage", default="lead")
    ingest.add_argument("--dealstage", default="appointmentscheduled")
    ingest.add_argument("--source", default="webform")

    sub.add_parser("weekly-report", help="Generate the weekly deal summary")
    return parser


def _init_codex(settings: Settings) -> MomentumCodex:
    hubspot = HubSpotClient(settings.hubspot_access_token, base_url=settings.hubspot_base_url)
    slack = SlackNotifier(settings.slack_webhook_url)
    return MomentumCodex(hubspot, slack=slack, project_board_hook=settings.project_board_webhook_url)


def handle_ingest(args: argparse.Namespace, codex: MomentumCodex) -> Dict[str, Any]:
    payload = {
        "firstname": args.firstname,
        "lastname": args.lastname,
        "email": args.email,
        "company": args.company,
        "phone": args.phone,
        "dealname": args.dealname,
        "amount": args.amount,
        "lifecyclestage": args.lifecyclestage,
        "dealstage": args.dealstage,
        "source": args.source,
    }
    return codex.process_lead(payload)


def handle_weekly_report(codex: MomentumCodex) -> str:
    summary = codex.generate_weekly_report(anchor=datetime.now(UTC))
    return summary.to_markdown()


def main(argv: Any = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_environment()
    codex = _init_codex(settings)

    if args.command == "ingest":
        result = handle_ingest(args, codex)
        print(result)
    elif args.command == "weekly-report":
        report = handle_weekly_report(codex)
        print(report)
    else:
        parser.error("Unknown command")


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
