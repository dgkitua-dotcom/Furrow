#!/usr/bin/env python3
"""
FURROW <- TMX live sync.
Reads TMX's own market-data CSV feed directly. Trades trickle in one at a
time whenever they happen (not all on the same day), so this takes the most
recent trade for each commodity/warehouse pair rather than filtering by a
single calendar date, and writes tmx_live.json for the site.

Fail-safe contract:
- On ANY failure, exits non-zero and writes NOTHING -> the last good
  tmx_live.json stays in place, GitHub emails the failed run, and the
  workflow opens/updates a 'tmx-pipe' issue.
- Only writes when it has confidently parsed at least MIN_ROWS rows.
"""
import csv
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

SOURCE_URL = "https://www.tmx.co.tz/pages/api/v1/market-data/read_csv.php"
MIN_ROWS = 2
OUT = "tmx_live.json"
EAT = timezone(timedelta(hours=3))

UA = {"User-Agent": "FURROW-price-board/1.0 (+https://www.joinfurrow.com; data attributed to TMX)"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def num(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def parse_and_aggregate(text):
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < MIN_ROWS:
        raise ValueError(f"too few rows in source CSV: {len(rows)}")

    # Keep only the most recent trade (highest ID) for each commodity/warehouse
    # pair -- trades trickle in individually, they don't all land on one day.
    latest = {}
    for r in rows:
        commodity = (r.get("Commodity") or "").strip()
        warehouse = (r.get("Location") or "").strip()
        if not commodity:
            continue
        key = (commodity, warehouse)
        rid = num(r.get("ID")) or 0
        if key not in latest or rid > (num(latest[key].get("ID")) or 0):
            latest[key] = r

    out = []
    for (commodity, warehouse), r in latest.items():
        high = num(r.get("High Price (TZS/kg)"))
        low = num(r.get("Low Price (TZS/kg)"))
        if high is None and low is None:
            continue
        clearing = high if high is not None else low
        change_tzs = num(r.get("Price Change (TZS/kg)"))
        direction = "flat"
        if change_tzs is not None:
            direction = "up" if change_tzs > 0 else ("dn" if change_tzs < 0 else "flat")
        out.append({
            "commodity": commodity,
            "warehouse": warehouse,
            "low": low if low is not None else clearing,
            "high": high if high is not None else clearing,
            "clearing": clearing,
            "change_tzs": change_tzs,
            "change_raw": r.get("Price Change (TZS/kg)") or "",
            "dir": direction,
            "trade_date": (r.get("Date") or "").strip(),
        })

    if len(out) < MIN_ROWS:
        raise ValueError(f"only {len(out)} usable commodity/warehouse rows")

    session_date = max((o["trade_date"] for o in out if o["trade_date"]), default="")
    return out, session_date


def main():
    try:
        body = fetch(SOURCE_URL)
    except Exception as e:  # noqa: BLE001
        print(f"FETCH FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        rows, session_date = parse_and_aggregate(body)
    except Exception as e:  # noqa: BLE001
        print(f"PARSE FAILED: {e}\nFirst 500 chars of payload:\n{body[:500]}", file=sys.stderr)
        sys.exit(1)

    try:
        prev = json.load(open(OUT))
        if prev.get("rows") == rows:
            print("rows unchanged; leaving file as-is")
            return
    except Exception:  # noqa: BLE001
        pass

    payload = {
        "status": "ok",
        "source": "Tanzania Mercantile Exchange (TMX), official market-data feed",
        "fetched_at_eat": datetime.now(EAT).strftime("%Y-%m-%d %H:%M EAT"),
        "session_date": session_date,
        "rows": rows,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"wrote {OUT}: {len(rows)} rows, session {session_date}")


if __name__ == "__main__":
    main()
