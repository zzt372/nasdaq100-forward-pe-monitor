#!/usr/bin/env python3
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote_plus
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
SEARCH_QUERY = 'Trendonify "Nasdaq 100" "Forward P/E Ratio" "Percentile Rank (10Y)"'
SEARCH_URLS = [
    ("bing", "https://www.bing.com/search?q=" + quote_plus(SEARCH_QUERY) + "&count=10"),
    ("google", "https://www.google.com/search?q=" + quote_plus(SEARCH_QUERY) + "&num=10&hl=en"),
    ("duckduckgo", "https://html.duckduckgo.com/html/?q=" + quote_plus(SEARCH_QUERY)),
]

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


def parse_table(html: str, method: str, kind: str = "forward-pe-ratio-table") -> Candidate:
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        cells = [" ".join(x.stripped_strings) for x in tr.find_all(["th", "td"])]
        if cells and cells[0].strip().lower() == "nasdaq 100" and len(cells) >= 5:
            return Candidate(num(cells[1]), num(cells[2]), parse_date(cells[4]).isoformat(), CANONICAL, kind, method)

    text = clean(html)
    # Flexible enough for search snippets with punctuation/separators between fields.
    m = re.search(
        r"Nasdaq\s+100.{0,100}?(\d{1,2}(?:\.\d+)?).{0,100}?(\d{1,3}(?:\.\d+)?)\s*%.{0,120}?"
        r"(?:Attractive|Undervalued|Fair\s+Value|Overvalued|Expensive).{0,120}?"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4})",
        text,
        re.I,
    )
    if not m:
        raise ValueError("Nasdaq 100 table row not found")
    return Candidate(float(m.group(1)), float(m.group(2)), parse_date(m.group(3)).isoformat(), CANONICAL, kind + "-text", method)


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


def fetch_html(url: str, attempts: int = 2, stop_on_403: bool = False):
    errors = []
    for attempt in range(1, attempts + 1):
        if curl_requests is not None:
            try:
                r = curl_requests.get(url, headers=HEADERS, impersonate="chrome", timeout=20, allow_redirects=True)
                if r.status_code == 200 and len(r.text) > 300:
                    return r.text, f"curl-cffi-attempt-{attempt}"
                errors.append(f"curl:{r.status_code}")
                if stop_on_403 and r.status_code == 403:
                    break
            except Exception as e:
                errors.append(f"curl:{e}")
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=20) as r:
                text = r.read().decode("utf-8", "replace")
            if len(text) > 300:
                return text, f"urllib-attempt-{attempt}"
        except Exception as e:
            errors.append(f"urllib:{e}")
            if stop_on_403 and "403" in str(e):
                break
        if attempt < attempts:
            time.sleep(attempt * 2)
    raise RuntimeError("; ".join(errors[-6:]))


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

    errors = []

    # 1) Canonical Trendonify table direct. A 403 is expected on some datacenter IPs,
    # so do not waste retries on it.
    try:
        html, method = fetch_html(CANONICAL, attempts=1, stop_on_403=True)
        c = parse_table(html, method)
        validate(c, previous_date)
        return c
    except Exception as e:
        errors.append(f"canonical-direct: {type(e).__name__}: {e}")

    # 2) Search-index transport for the same Trendonify canonical row.
    # Search engines are transport only; the accepted data must parse as the Trendonify
    # Nasdaq 100 forward-P/E row and still passes the same validation.
    for engine, url in SEARCH_URLS:
        try:
            html, method = fetch_html(url, attempts=2)
            c = parse_table(html, f"{engine}-search-index/{method}", kind=f"search-index-{engine}")
            validate(c, previous_date)
            return c
        except Exception as e:
            errors.append(f"search-{engine}: {type(e).__name__}: {e}")

    # 3) Last-resort Trendonify fallback pages. They are never compared against a valid
    # canonical reading, preventing same-day cross-page discrepancies from causing noise.
    for url, kind in ((MAIN, "nasdaq-100-main-page"), (DEDICATED, "dedicated-forward-pe-page")):
        try:
            html, method = fetch_html(url, attempts=1, stop_on_403=True)
            c = parse_page(html, method, url, kind)
            validate(c, previous_date)
            return c
        except Exception as e:
            errors.append(f"{kind}: {type(e).__name__}: {e}")

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
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
