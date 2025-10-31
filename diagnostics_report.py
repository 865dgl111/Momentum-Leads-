#!/usr/bin/env python3
"""Environment diagnostics for Momentum Leads LLC.

This script exercises integrations used by the project and emits a
human-readable summary that matches the format requested by operators.
Each check is resilient to missing dependencies or networking
restrictions so the resulting report clearly communicates why a test
failed rather than crashing abruptly.
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
import textwrap
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Callable, Dict, Optional, Tuple

import base64
import urllib.error
import urllib.request


def _load_requests() -> Optional[object]:
    """Attempt to import requests and return the module if available."""
    try:
        import requests  # type: ignore

        return requests
    except ModuleNotFoundError:
        return None


@dataclass
class SimpleResponse:
    status_code: int
    text: str
    headers: Dict[str, str]

    def json(self) -> Dict[str, object]:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if not 200 <= self.status_code < 300:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")


def _http_request(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json_payload: Optional[Dict[str, object]] = None,
    auth: Optional[Tuple[str, str]] = None,
    timeout: int = 15,
) -> SimpleResponse:
    """Send an HTTP request using requests or urllib as a fallback."""

    headers = dict(headers or {})
    requests = _load_requests()

    if requests is not None:
        response = requests.request(
            method,
            url,
            headers=headers,
            json=json_payload,
            auth=auth,
            timeout=timeout,
        )
        return SimpleResponse(
            status_code=response.status_code,
            text=response.text,
            headers=dict(response.headers or {}),
        )

    data: Optional[bytes] = None
    if json_payload is not None:
        data = json.dumps(json_payload).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    if auth is not None:
        user, password = auth
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return SimpleResponse(
                status_code=response.getcode(),
                text=body,
                headers=dict(response.headers),
            )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return SimpleResponse(status_code=exc.code, text=body, headers=dict(exc.headers or {}))


@dataclass
class CheckResult:
    name: str
    status: str
    message: str
    details: Dict[str, object] = field(default_factory=dict)

    def to_summary_line(self) -> str:
        return f"{self.name} {self.status} – {self.message}"


def _openai_check() -> CheckResult:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return CheckResult(
            name="OPENAI",
            status="❌",
            message="OPENAI_API_KEY is not set",
        )

    prompt = "Momentum Leads system online."
    payload = {"model": "gpt-4o-mini", "input": prompt}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = os.getenv("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses")

    try:
        response = _http_request(
            "POST",
            url,
            headers=headers,
            json_payload=payload,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - provide explicit message to operators
        return CheckResult(
            name="OPENAI",
            status="❌",
            message=f"Failed to call OpenAI Responses API: {exc}",
        )

    text = ""
    # Responses API may return different shapes; we attempt to pull a human-readable snippet.
    if isinstance(data, dict):
        text = (
            data.get("output_text")
            or data.get("output", [{}])[0]
            .get("content", [{}])[0]
            .get("text", "")
            if isinstance(data.get("output"), list)
            else ""
        )
    if text:
        snippet = textwrap.shorten(text, width=120)
        message = f"Received model output: {snippet}"
    else:
        message = "Request succeeded, but no text output was found in the response payload."

    return CheckResult(name="OPENAI", status="✅", message=message, details=data)


def _stripe_check() -> CheckResult:
    secret_key = os.getenv("STRIPE_SECRET_KEY") or os.getenv("STRIPE_SECRETE_KEY")
    if not secret_key:
        return CheckResult(
            name="STRIPE",
            status="❌",
            message="Neither STRIPE_SECRET_KEY nor STRIPE_SECRETE_KEY is set.",
        )

    url = "https://api.stripe.com/v1/balance"
    try:
        response = _http_request(
            "GET",
            url,
            auth=(secret_key, ""),
        )
        response.raise_for_status()
        balance = response.json()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="STRIPE",
            status="❌",
            message=f"Failed to retrieve balance: {exc}",
        )

    available = balance.get("available")
    if isinstance(available, list) and available:
        currency = available[0].get("currency", "unknown").upper()
        amount = available[0].get("amount")
        message = f"Available balance: {amount} {currency}"
    else:
        message = "Balance retrieved successfully."

    return CheckResult(name="STRIPE", status="✅", message=message, details=balance)


def _smtp_check() -> CheckResult:
    user = os.getenv("OUTLOOK_SMTP_USER")
    password = os.getenv("OUTLOOK_SMTP_PASS")
    if not user or not password:
        return CheckResult(
            name="SMTP",
            status="❌",
            message="OUTLOOK_SMTP_USER and/or OUTLOOK_SMTP_PASS are not set.",
        )

    recipient = os.getenv("SMTP_TEST_RECIPIENT", "momentumleadsllc@outlook.com")
    subject = "Momentum Leads System Test"
    body = "This is an automated test confirming SMTP and AI integrations are active."

    message = EmailMessage()
    message["From"] = user
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP("smtp.office365.com", 587, timeout=15) as smtp:
            context = ssl.create_default_context()
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.login(user, password)
            smtp.send_message(message)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="SMTP",
            status="❌",
            message=f"Failed to send test email: {exc}",
        )

    return CheckResult(
        name="SMTP",
        status="✅",
        message=f"Test email sent to {recipient} via Outlook SMTP.",
    )


CHECKS: Dict[str, Callable[[], CheckResult]] = {
    "OPENAI": _openai_check,
    "STRIPE": _stripe_check,
    "SMTP": _smtp_check,
}


def run_checks() -> Dict[str, CheckResult]:
    results: Dict[str, CheckResult] = {}
    for name, check in CHECKS.items():
        results[name] = check()
    return results


def _build_summary(results: Dict[str, CheckResult]) -> str:
    summary_bits = [f"{name} {result.status}" for name, result in results.items()]
    return " / ".join(summary_bits)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the full report as JSON instead of a human readable summary.",
    )
    args = parser.parse_args(argv)

    results = run_checks()
    if args.json:
        payload = {name: result.__dict__ for name, result in results.items()}
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for result in results.values():
            print(result.to_summary_line())
        print("\nStatus Report")
        print(_build_summary(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
