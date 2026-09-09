# Nasdaq 100 Forward P/E Monitor

GitHub Actions monitor for Trendonify's **Nasdaq 100 Forward PE Ratio**.

## Production architecture

- Main workflow runs every 5 minutes, offset from minute `0`.
- An independent watchdog runs at minutes `7,22,37,52` and refreshes only when committed data is stale.
- The authoritative Trendonify page is the dedicated Nasdaq 100 Forward PE Ratio page:
  `https://trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio`
- Trendonify blocks GitHub-hosted runner IPs with HTTP 403/Cloudflare. The monitor therefore reads the **public search-index snippet for that exact Trendonify page** through DuckDuckGo Lite. DuckDuckGo is transport only; values from other domains are never accepted.
- One query must contain all three required fields from the same Trendonify result: forward P/E, 10-year percentile, and indexed data date.
- Only one search request is made per run to reduce bot-challenge risk. A failed run leaves the last-known-good `latest.json` untouched; the next 5-minute run naturally retries from a fresh runner.
- Regression tests run before each production fetch.
- Values and dates are validated; future/stale dates and date rollback are rejected.
- Material value changes are committed immediately. When values do not change, a freshness heartbeat is committed roughly hourly.
- No API keys or repository secrets are required.

## `latest.json` consumer validation

Consumers should require:

- `schema_version == 2`
- `ok == true`
- `forward_pe` is a positive finite number
- `percentile_10y` is between 0 and 100
- `data_date` is plausible and recent
- `fetched_at` is fresh
- `source == "Trendonify"`
- `source_url == "https://trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio"`
- `source_kind == "dedicated-forward-pe-search-index"`
- `fetch_method == "duckduckgo-lite"`

This repository deliberately preserves the last-known-good value when acquisition or validation fails instead of publishing guessed, partial, or cross-source data.
