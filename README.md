# Momentum Codex

Momentum Codex is the automation brain for Momentum Leads LLC. It keeps HubSpot in sync with lead capture channels, logs every client touchpoint, and produces weekly revenue summaries.

## Features

- Lead ingestion workflow that creates or updates HubSpot contacts, companies, and deals.
- Slack notifications for every new deal and optional project board sync via webhook.
- Timeline logging utilities to record calls, emails, and payment touchpoints.
- Weekly reporting utilities to summarise deal counts, pipeline stages, and revenue totals.
- Command line interface for ad-hoc ingestion and reporting tasks.

## Getting started

1. Create and activate a Python 3.9+ environment.
2. Install dependencies:

   ```bash
   pip install -e .[dev]
   ```

3. Export the required environment variables:

   ```bash
   export HUBSPOT_ACCESS_TOKEN="YOUR_PRIVATE_APP_TOKEN"
   export HUBSPOT_BASE_URL="https://api.hubapi.com"
   export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."  # optional
   export PROJECT_BOARD_WEBHOOK_URL="https://example.com/webhook"    # optional
   ```

4. Run the automated tests:

   ```bash
   pytest
   ```

5. Process a lead payload from the command line:

   ```bash
   python -m momentum_codex.cli ingest \
       --firstname "David" \
       --lastname "Lamb" \
       --email "david@example.com" \
       --company "Momentum Leads LLC" \
       --phone "8653837990" \
       --dealname "Momentum Sites AI Setup" \
       --amount 1499 \
       --lifecyclestage customer \
       --dealstage appointmentscheduled \
       --source webform
   ```

6. Generate the weekly report:

   ```bash
   python -m momentum_codex.cli weekly-report
   ```

## Test coverage

Unit tests rely on mocks for external services. They can be run with `pytest` and cover lead ingestion, contact updates, and weekly reporting summaries.
