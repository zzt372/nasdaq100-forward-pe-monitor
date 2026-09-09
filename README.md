# Nasdaq 100 Forward P/E Monitor

GitHub Actions monitor for Trendonify's **Nasdaq 100 Forward P/E Ratio**.

## Design

- Runs every 5 minutes, offset from minute `0`.
- Canonical source: Trendonify `/forward-pe-ratio` → **Nasdaq 100** row.
- Fallback pages are used only when the canonical source cannot be fetched or parsed:
  1. Nasdaq 100 main page
  2. Dedicated Nasdaq 100 Forward P/E page
- A valid canonical reading always wins, so same-day differences on fallback pages do not create false conflicts.
- Validates forward P/E, 10-year percentile, and data date.
- Rejects future/stale dates and date rollback.
- Preserves last-known-good `latest.json` if acquisition fails.
- Uses browser-like TLS/headers via `curl-cffi`, with `urllib` fallback.
- Commits immediately on material value changes and roughly hourly as a freshness heartbeat.
- Regression tests run before each fetch.

## Consumer validation

Consumers should require:

- `schema_version == 2`
- `ok == true`
- `forward_pe` is a positive finite number
- `percentile_10y` is between 0 and 100
- `data_date` is plausible and recent
- `fetched_at` is fresh
- `source == "Trendonify"`
- `source_url` is a Trendonify URL

No API keys or secrets are stored in this repository.
