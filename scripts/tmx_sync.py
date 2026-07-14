#!/usr/bin/env python3
"""
FURROW <- TMX live sync.
Reads TMX's own market-data CSV feed directly, aggregates individual trades
into one row per commodity per warehouse for the latest trading date, and
writes tmx_live.json for the site.

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
from collections import defaultdict

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

    dates = sorted({r.get("Date", "").strip() for r in rows if r.get("Date")})
    if not dates:
        raise ValueError("no usable Date values in source CSV")
    latest_date = dates[-1]
    todays = [r for r in rows if r.get("Date", "").strip() == latest_date]
    if len(todays) < MIN_ROWS:
        raise ValueError(f"only {len(todays)} trades on latest date {latest_date}")

    groups = defaultdict(list)
    for r in todays:
        commodity = (r.get("Commodity") or "").strip()
        warehouse = (r.get("Location") or "").strip()
        if not commodity:
            continue
        groups[(commodity, warehouse)].append(r)

    out = []
    for (commodity, warehouse), trades in groups.items():
        trades.sort(key=lambda t: num(t.get("ID")) or 0)
        last = trades[-1]

        highs = [num(t.get("High Price")) for t in trades if num(t.get("High Price")) is not None]
        lows  = [num(t.get("Low Price"))  for t in trades if num(t.get("Low Price"))  is not None]
        if not highs and not lows:
            continue

        clearing = num(last.get("High Price")) or num(last.get("Low Price"))
        change_tzs = num(last.get("Price Change"))
        direction = "flat"
        if change_tzs is not None:
            direction = "up" if change_tzs > 0 else ("dn" if change_tzs < 0 else "flat")

        out.append({
            "commodity": commodity,
            "warehouse": warehouse,
            "low": min(lows) if lows else clearing,
            "high": max(highs) if highs else clearing,
            "clearing": clearing,
            "change_tzs": change_tzs,
            "change_raw": last.get("Price Change") or "",
            "dir": direction,
            "trades": len(trades),
        })

    if len(out) < MIN_ROWS:
        raise ValueError(f"aggregated only {len(out)} usable commodity/warehouse rows")
    return out, latest_date


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
