#!/usr/bin/env python3
import argparse
import html as htmlmod
import json
import math
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LATEST = ROOT / "latest.json"
DEDICATED = "https://trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio"
SEARCH_QUERY = 'Trendonify "Nasdaq 100 Forward PE Ratio" "percentile"'
SEARCH_URL = "https://lite.duckduckgo.com/lite/?q=" + quote_plus(SEARCH_QUERY)
SOURCE_KIND = "dedicated-forward-pe-search-index"
FETCH_METHOD = "duckduckgo-lite"
SCHEMA_VERSION = 2
MAX_DATA_AGE_DAYS = 7
MAX_RESPONSE_BYTES = 500_000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Connection": "close",
}


def utcnow():
    return datetime.now(timezone.utc)


def parse_date(text: str):
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"bad date: {text}")


def parse_utc_timestamp(text: str):
    if not isinstance(text, str) or not text:
        raise ValueError("invalid timestamp")
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def textify(raw: str) -> str:
    raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return " ".join(htmlmod.unescape(raw).split())


def parse_search_index(raw: str):
    text = textify(raw)
    low = text.lower()

    challenge_markers = (
        "unfortunately, bots use duckduckgo too",
        "select all squares containing a duck",
        "please complete the following challenge",
    )
    if any(marker in low for marker in challenge_markers):
        raise RuntimeError("DuckDuckGo bot challenge")

    marker = "Nasdaq 100 Forward PE Ratio - trendonify.com"
    positions = [m.start() for m in re.finditer(re.escape(marker), text, flags=re.I)]
    if not positions:
        raise ValueError("Trendonify dedicated result not found")

    candidates = set()
    exact_url = "trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio"

    for pos in positions:
        block = text[pos : pos + 3500]
        if exact_url not in block.lower():
            continue

        valuation = re.search(
            r"current\s+P/E\s+Ratio\s+of\s+(\d+(?:\.\d+)?)\s+ranks\s+in\s+the\s+"
            r"(\d+(?:\.\d+)?)(?:st|nd|rd|th)?\s+percentile",
            block,
            re.I,
        )
        date_match = re.search(
            r"trendonify\.com/united-states/stock-market/nasdaq-100/forward-pe-ratio\s+"
            r"(20\d{2}-\d{2}-\d{2})T",
            block,
            re.I,
        )
        if valuation and date_match:
            candidates.add(
                (
                    float(valuation.group(1)),
                    float(valuation.group(2)),
                    date_match.group(1),
                )
            )

    if not candidates:
        raise ValueError("complete Trendonify P/E, percentile, date tuple not found")
    if len(candidates) != 1:
        raise ValueError(f"conflicting Trendonify snippets: {sorted(candidates)}")
    return next(iter(candidates))


def validate_values(
    forward_pe: float,
    percentile: float,
    data_date: str,
    previous_date=None,
    now_date=None,
    max_data_age_days=MAX_DATA_AGE_DAYS,
):
    if isinstance(forward_pe, bool) or not isinstance(forward_pe, (int, float)):
        raise ValueError("forward_pe must be numeric")
    if isinstance(percentile, bool) or not isinstance(percentile, (int, float)):
        raise ValueError("percentile must be numeric")
    if not math.isfinite(float(forward_pe)) or not (1 <= float(forward_pe) <= 100):
        raise ValueError("invalid forward_pe")
    if not math.isfinite(float(percentile)) or not (0 <= float(percentile) <= 100):
        raise ValueError("invalid percentile")

    d = parse_date(data_date)
    today = now_date or utcnow().date()
    if d > today + timedelta(days=1):
        raise ValueError("future data date")
    if d < today - timedelta(days=max_data_age_days):
        raise ValueError("stale data date")
    if previous_date and d < previous_date:
        raise ValueError("data date rollback")
    return d


def validate_transition(forward_pe, percentile, data_date, previous):
    if not isinstance(previous, dict) or previous.get("ok") is not True:
        return
    try:
        old_pe = float(previous["forward_pe"])
        old_pct = float(previous["percentile_10y"])
        old_date = parse_date(previous["data_date"])
        new_date = parse_date(data_date)
    except Exception:
        return

    if old_pe <= 0 or new_date < old_date:
        return

    relative_pe_change = abs(float(forward_pe) - old_pe) / old_pe
    percentile_change = abs(float(percentile) - old_pct)
    day_gap = (new_date - old_date).days

    # Only block extreme jumps that strongly suggest a wrong metric/result. Keep the
    # guard loose enough that a genuine market crash/rally can still trigger alerts.
    if day_gap == 0 and (relative_pe_change > 0.25 or percentile_change > 45):
        raise ValueError("implausible same-date value jump")
    if 0 < day_gap <= 7 and (relative_pe_change > 0.50 or percentile_change > 60):
        raise ValueError("implausible short-window value jump")


def validate_payload(payload, max_fetch_age_seconds=None, now=None):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("schema_version mismatch")
    if payload.get("ok") is not True:
        raise ValueError("ok must be true")
    if payload.get("source") != "Trendonify":
        raise ValueError("source mismatch")
    if payload.get("source_url") != DEDICATED:
        raise ValueError("source_url mismatch")
    if payload.get("source_kind") != SOURCE_KIND:
        raise ValueError("source_kind mismatch")
    if payload.get("fetch_method") != FETCH_METHOD:
        raise ValueError("fetch_method mismatch")

    current = now or utcnow()
    validate_values(
        payload.get("forward_pe"),
        payload.get("percentile_10y"),
        payload.get("data_date"),
        now_date=current.date(),
    )

    fetched_at = parse_utc_timestamp(payload.get("fetched_at"))
    age = (current - fetched_at).total_seconds()
    if age < -600:
        raise ValueError("fetched_at is too far in the future")
    if max_fetch_age_seconds is not None and age > max_fetch_age_seconds:
        raise ValueError("fetched_at is stale")
    return age


def load_previous():
    try:
        return json.loads(LATEST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fetch_once():
    req = Request(SEARCH_URL, headers=HEADERS)
    with urlopen(req, timeout=25) as response:
        if response.status != 200:
            raise RuntimeError(f"search HTTP {response.status}")
        raw_bytes = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw_bytes) > MAX_RESPONSE_BYTES:
        raise RuntimeError("search response too large")
    raw = raw_bytes.decode("utf-8", "replace")
    if len(raw) < 1000:
        raise RuntimeError("search response too short")
    return raw


def build_payload(forward_pe, percentile, data_date, fetched_at=None):
    stamp = fetched_at or utcnow()
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "forward_pe": round(float(forward_pe), 4),
        "percentile_10y": round(float(percentile), 4),
        "data_date": data_date,
        "fetched_at": stamp.isoformat().replace("+00:00", "Z"),
        "source": "Trendonify",
        "source_url": DEDICATED,
        "source_kind": SOURCE_KIND,
        "fetch_method": FETCH_METHOD,
    }


def write_atomic(payload):
    tmp = LATEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(LATEST)


def check_latest(max_fetch_age_seconds):
    payload = load_previous()
    age = validate_payload(payload, max_fetch_age_seconds=max_fetch_age_seconds)
    print(f"latest.json healthy; fetched_age_seconds={age:.0f}")


def run_fetch():
    previous = load_previous()
    previous_date = None
    if previous.get("ok") is True and previous.get("data_date"):
        try:
            previous_date = parse_date(previous["data_date"])
        except Exception:
            pass

    raw = fetch_once()
    forward_pe, percentile, data_date = parse_search_index(raw)
    validate_values(forward_pe, percentile, data_date, previous_date=previous_date)
    validate_transition(forward_pe, percentile, data_date, previous)
    payload = build_payload(forward_pe, percentile, data_date)
    validate_payload(payload, max_fetch_age_seconds=60)
    write_atomic(payload)
    print(json.dumps(payload))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-latest", action="store_true")
    parser.add_argument("--max-fetch-age-seconds", type=int, default=3600)
    args = parser.parse_args(argv)

    try:
        if args.check_latest:
            check_latest(args.max_fetch_age_seconds)
        else:
            run_fetch()
        return 0
    except Exception as exc:
        # Never overwrite a known-good reading with acquisition/parser/validation failure.
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
