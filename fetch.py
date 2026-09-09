#!/usr/bin/env python3
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None

ROOT = Path(__file__).resolve().parent
LATEST = ROOT / "latest.json"
CANONICAL = "https://trendonify.com/forward-pe-ratio"
MAIN = "https://trendonify.com/united-states/stock-market/nasdaq-100"
DEDICATED = "https://trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

@dataclass
class Candidate:
    forward_pe: float
    percentile_10y: float
    data_date: str
    source_url: str
    source_kind: str
    fetch_method: str


def parse_date(text: str):
    text = " ".join(text.replace(",", ", ").split())
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"bad date: {text}")


def num(text: str) -> float:
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not m:
        raise ValueError(f"number not found: {text}")
    return float(m.group())


def clean(html: str) -> str:
    return " ".join(BeautifulSoup(html, "html.parser").stripped_strings)


def parse_table(html: str, method: str) -> Candidate:
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        cells = [" ".join(x.stripped_strings) for x in tr.find_all(["th", "td"])]
        if cells and cells[0].strip().lower() == "nasdaq 100" and len(cells) >= 5:
            return Candidate(num(cells[1]), num(cells[2]), parse_date(cells[4]).isoformat(), CANONICAL, "forward-pe-ratio-table", method)
    text = clean(html)
    m = re.search(r"Nasdaq\s+100\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)%\s+(?:Attractive|Undervalued|Fair\s+Value|Overvalued|Expensive)\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4})", text, re.I)
    if not m:
        raise ValueError("Nasdaq 100 table row not found")
    return Candidate(float(m.group(1)), float(m.group(2)), parse_date(m.group(3)).isoformat(), CANONICAL, "forward-pe-ratio-table-text", method)


def parse_page(html: str, method: str, url: str, kind: str) -> Candidate:
    text = clean(html)
    m = re.search(r"currently\s+trades\s+at\s+a\s+forward\s+P/E\s+ratio\s+of\s+(\d+(?:\.\d+)?)\s+as\s+of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", text, re.I)
    if not m:
        raise ValueError("forward P/E sentence not found")
    window = text[m.end():m.end()+1200]
    p = re.search(r"Valuation\s+Percentile\s+Rank\s+(\d+(?:\.\d+)?)%", window, re.I)
    if not p:
        p = re.search(r"ranks\s+in\s+the\s+(\d+(?:\.\d+)?)(?:st|nd|rd|th)?\s+percentile", window, re.I)
    if not p:
        raise ValueError("10Y percentile not found")
    return Candidate(float(m.group(1)), float(p.group(1)), parse_date(m.group(2)).isoformat(), url, kind, method)


def validate(c: Candidate, previous_date=None):
    if not math.isfinite(c.forward_pe) or not (1 <= c.forward_pe <= 100):
        raise ValueError("invalid forward_pe")
    if not math.isfinite(c.percentile_10y) or not (0 <= c.percentile_10y <= 100):
        raise ValueError("invalid percentile")
    d = parse_date(c.data_date)
    today = datetime.now(timezone.utc).date()
    if d > today + timedelta(days=1) or d < today - timedelta(days=10):
        raise ValueError("implausible data date")
    if previous_date and d < previous_date:
        raise ValueError("data date rollback")


def fetch_html(url: str):
    errors = []
    for attempt in range(1, 4):
        if curl_requests is not None:
            try:
                r = curl_requests.get(url, headers=HEADERS, impersonate="chrome", timeout=25, allow_redirects=True)
                if r.status_code == 200 and len(r.text) > 300:
                    return r.text, f"curl-cffi-attempt-{attempt}"
                errors.append(f"curl:{r.status_code}")
            except Exception as e:
                errors.append(f"curl:{e}")
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=25) as r:
                text = r.read().decode("utf-8", "replace")
            if len(text) > 300:
                return text, f"urllib-attempt-{attempt}"
        except Exception as e:
            errors.append(f"urllib:{e}")
        time.sleep(attempt * 2)
    raise RuntimeError("; ".join(errors[-8:]))


def load_previous():
    try:
        return json.loads(LATEST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def acquire(previous):
    previous_date = None
    if previous.get("ok") is True and previous.get("data_date"):
        try:
            previous_date = parse_date(previous["data_date"])
        except Exception:
            pass

    # Canonical table is authoritative. Fallback pages are consulted only if it fails,
    # so same-day discrepancies across Trendonify pages cannot create false conflicts.
    sources = [
        (CANONICAL, lambda h, m: parse_table(h, m)),
        (MAIN, lambda h, m: parse_page(h, m, MAIN, "nasdaq-100-main-page")),
        (DEDICATED, lambda h, m: parse_page(h, m, DEDICATED, "dedicated-forward-pe-page")),
    ]
    errors = []
    for url, parser in sources:
        try:
            html, method = fetch_html(url)
            c = parser(html, method)
            validate(c, previous_date)
            return c
        except Exception as e:
            errors.append(f"{url}: {type(e).__name__}: {e}")
    raise RuntimeError(" | ".join(errors))


def main():
    previous = load_previous()
    try:
        c = acquire(previous)
        payload = {
            "schema_version": 2,
            "ok": True,
            "forward_pe": round(c.forward_pe, 4),
            "percentile_10y": round(c.percentile_10y, 4),
            "data_date": c.data_date,
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "Trendonify",
            "source_url": c.source_url,
            "source_kind": c.source_kind,
            "fetch_method": c.fetch_method,
        }
        tmp = LATEST.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(LATEST)
        print(json.dumps(payload))
        return 0
    except Exception as e:
        # Keep last-known-good latest.json untouched on failure.
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
