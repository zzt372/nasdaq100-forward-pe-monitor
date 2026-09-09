# Nasdaq 100 Forward P/E Monitor

GitHub Actions monitor for Trendonify's **Nasdaq 100 Forward PE Ratio**.

## Production architecture

- Main workflow runs every 10 minutes at UTC minutes `3,13,23,33,43,53`.
- An independent watchdog runs at UTC minutes `8,38` and recovers only when the committed state fails strict health validation or its `fetched_at` is 75+ minutes old.
- Main and watchdog share the same GitHub Actions concurrency group with `queue: max`, so overlapping runs are serialized instead of cancelling one another.
- The tracked Trendonify identity is fixed to the dedicated Nasdaq 100 Forward PE Ratio page:
  `https://trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio`
- Trendonify blocks GitHub-hosted runner IPs with HTTP 403/Cloudflare. The monitor therefore reads the **public search-index result for that exact Trendonify page** through DuckDuckGo Lite. DuckDuckGo is transport only; values from other domains are never accepted.
- Exactly one search request is made per production run. Repeated search queries from one runner are intentionally avoided because they increase bot-challenge risk.
- A valid result must provide **forward P/E + 10-year percentile + indexed data date together in the same exact Trendonify result block**. Values from different Trendonify pages or different search results are never merged.
- Identical duplicate result blocks are allowed. Conflicting duplicate tuples fail closed.
- Acquisition, parsing, source-identity, freshness, or sanity-check failures leave the last-known-good `latest.json` untouched.
- Regression tests run before each production fetch. The generated payload is validated again before any commit.
- Material value/date/source changes are committed immediately. When values do not change, a heartbeat is committed after roughly 40 minutes so downstream consumers can verify freshness without creating a commit every 10 minutes.
- GitHub Actions `checkout` and `setup-python` use the current v7 major releases.
- No API keys or repository secrets are required.

## Validation and fail-closed rules

The producer rejects, among other cases:

- malformed or missing Trendonify result blocks
- DuckDuckGo bot/CAPTCHA challenge pages
- another provider masquerading as a matching result
- a wrong Trendonify URL
- conflicting duplicate Trendonify tuples
- P/E outside `1..100`
- percentile outside `0..100`
- data dates more than one day in the future or more than seven calendar days old
- data-date rollback versus the previous known-good state
- implausible same-date or short-window jumps that are more consistent with parsing/index corruption than a genuine update
- malformed, stale, or future `fetched_at`
- schema/source/source URL/source-kind/fetch-method mismatches

## Why one Trendonify representation is used

Trendonify can expose slightly different values on its aggregate forward-P/E table, Nasdaq 100 overview, and dedicated Forward P/E page/search index at the same time. Mixing those representations creates false conflicts and noisy alerts. This repository deliberately tracks one fixed identity and one complete tuple from one result block. A different Trendonify representation is never used as a silent substitute.

## `latest.json` consumer validation

Consumers should require:

- `schema_version == 2`
- `ok == true`
- `forward_pe` is numeric and between `1` and `100`
- `percentile_10y` is numeric and between `0` and `100`
- `data_date` is plausible, recent, and has not rolled backward
- `fetched_at` is timezone-aware, not materially in the future, and fresh enough for the consumer's SLA
- `source == "Trendonify"`
- `source_url == "https://trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio"`
- `source_kind == "dedicated-forward-pe-search-index"`
- `fetch_method == "duckduckgo-lite"`

For the ChatGPT consumer, a roughly 90-minute `fetched_at` tolerance is appropriate because GitHub scheduled workflows are best-effort and the independent watchdog uses a 75-minute recovery threshold.

## Tested failure behavior

Integration tests use multiple fresh GitHub-hosted runners to verify:

1. repeated live acquisition of the same Trendonify tuple,
2. stale-state classification,
3. recovery fetch and post-fetch validation, and
4. preservation of the byte-for-byte last-known-good `latest.json` after a simulated acquisition/CAPTCHA failure.

The design favors **silence and preservation of a known-good value over publishing a guessed, partial, cross-page, or cross-source value**.
