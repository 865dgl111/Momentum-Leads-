# Momentum Leads Diagnostics

This repository contains a standalone diagnostic utility for verifying
connectivity to Momentum Leads LLC integrations.

## Usage

```
python diagnostics_report.py
```

The script exercises the following checks:

- **OPENAI** – calls the Responses API using `OPENAI_API_KEY` and prints a
  snippet of the model output.
- **STRIPE** – retrieves the Stripe balance using `STRIPE_SECRET_KEY`. If
  that variable is missing it will fall back to the commonly misspelled
  `STRIPE_SECRETE_KEY`.
- **SMTP** – sends a test email through Outlook using
  `OUTLOOK_SMTP_USER`/`OUTLOOK_SMTP_PASS`. Override the destination with
  `SMTP_TEST_RECIPIENT` when needed.

For machine-readable output, add the `--json` flag:

```
python diagnostics_report.py --json
```

Each check is resilient to missing dependencies or networking
restrictions so operators always receive a concise status report.
