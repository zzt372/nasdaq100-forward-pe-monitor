#!/usr/bin/env python3
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
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


def parse_date(text: str):
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"bad date: {text}")


def textify(raw: str) -> str:
    raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return " ".join(htmlmod.unescape(raw).split())


def parse_search_index(raw: str):
    text = textify(raw)
    low = text.lower()
    if "unfortunately, bots use duckduckgo too" in low or "select all squares containing a duck" in low:
        raise RuntimeError("DuckDuckGo bot challenge")

    # Require the exact Trendonify Nasdaq 100 Forward PE result, not another provider.
    marker = "Nasdaq 100 Forward PE Ratio - trendonify.com"
    pos = text.find(marker)
    if pos < 0:
        raise ValueError("Trendonify dedicated result not found")
    block = text[pos : pos + 2600]
    if "trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio" not in block:
        raise ValueError("dedicated Trendonify URL not present")

    # Current dedicated-page snippets expose all three required fields in one result:
    # "The current P/E Ratio of 20.7 ranks in the 21.7th percentile ..."
    valuation = re.search(
        r"current\s+P/E\s+Ratio\s+of\s+(\d+(?:\.\d+)?)\s+ranks\s+in\s+the\s+"
        r"(\d+(?:\.\d+)?)(?:st|nd|rd|th)?\s+percentile",
        block,
        re.I,
    )
    if not valuation:
        raise ValueError("forward P/E and 10Y percentile pair not found")

    # DuckDuckGo exposes the indexed page date immediately after the result URL.
    date_match = re.search(
        r"trendonify\.com/united-states/stock-market/nasdaq-100/forward-pe-ratio\s+"
        r"(20\d{2}-\d{2}-\d{2})T",
        block,
        re.I,
    )
    if not date_match:
        raise ValueError("Trendonify data/index date not found")

    return float(valuation.group(1)), float(valuation.group(2)), date_match.group(1)


def validate(forward_pe: float, percentile: float, data_date: str, previous_date=None):
    if not math.isfinite(forward_pe) or not (1 <= forward_pe <= 100):
        raise ValueError("invalid forward_pe")
    if not math.isfinite(percentile) or not (0 <= percentile <= 100):
        raise ValueError("invalid percentile")
    d = parse_date(data_date)
    today = datetime.now(timezone.utc).date()
    if d > today + timedelta(days=1) or d < today - timedelta(days=10):
        raise ValueError("implausible data date")
    if previous_date and d < previous_date:
        raise ValueError("data date rollback")


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
        raw = response.read().decode("utf-8", "replace")
    if len(raw) < 1000:
        raise RuntimeError("search response too short")
    return raw


def main():
    previous = load_previous()
    previous_date = None
    if previous.get("ok") is True and previous.get("data_date"):
        try:
            previous_date = parse_date(previous["data_date"])
        except Exception:
            pass

    try:
        # Exactly one search request per run. Repeated queries from the same runner are more
        # likely to trigger a challenge; the 5-minute workflow cadence provides natural retry.
        raw = fetch_once()
        forward_pe, percentile, data_date = parse_search_index(raw)
        validate(forward_pe, percentile, data_date, previous_date)
        payload = {
            "schema_version": 2,
            "ok": True,
            "forward_pe": round(forward_pe, 4),
            "percentile_10y": round(percentile, 4),
            "data_date": data_date,
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "Trendonify",
            "source_url": DEDICATED,
            "source_kind": "dedicated-forward-pe-search-index",
            "fetch_method": "duckduckgo-lite",
        }
        tmp = LATEST.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(LATEST)
        print(json.dumps(payload))
        return 0
    except Exception as exc:
        # Never overwrite a known-good reading with an acquisition/parser failure.
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
