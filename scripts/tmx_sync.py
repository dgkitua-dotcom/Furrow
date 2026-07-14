#!/usr/bin/env python3
"""
FURROW <- TMX live sync.
Reads TMX's own market-data CSV feed directly, aggregates individual trades
into one row per commodity per warehouse for the latest known trade (trades
trickle in individually, not on a fixed daily schedule), and writes
tmx_live.json for the site. Each sync also appends a timestamped snapshot to
tmx_history.json so real price trends can build up over time.

Fail-safe contract:
- On ANY failure, exits non-zero and writes NOTHING -> the last good
  tmx_live.json / tmx_history.json stay in place, GitHub emails the failed
  run, and the workflow opens/updates a 'tmx-pipe' issue.
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
HISTORY_OUT = "tmx_history.json"
MAX_HISTORY_SNAPSHOTS = 2000  # roughly ~11 weeks at an hourly cadence; keeps the file bounded
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


def append_history(rows, synced_at):
    """Append this sync's snapshot to tmx_history.json so real trend charts
    can build up over time. Skips the append if nothing actually changed
    since the last snapshot, to avoid flooding the file with duplicates."""
    try:
        with open(HISTORY_OUT, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:  # noqa: BLE001 - no previous history file, start fresh
        hist = {"history": []}

    snapshots = hist.get("history", [])
    if snapshots and snapshots[-1].get("rows") == rows:
        return  # nothing changed since the last snapshot; don't duplicate

    snapshots.append({"synced_at": synced_at, "rows": rows})
    if len(snapshots) > MAX_HISTORY_SNAPSHOTS:
        snapshots = snapshots[-MAX_HISTORY_SNAPSHOTS:]

    hist["history"] = snapshots
    with open(HISTORY_OUT, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=2, ensure_ascii=False)


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

    synced_at = datetime.now(EAT).strftime("%Y-%m-%d %H:%M EAT")

    # Always try to extend history, even if tmx_live.json itself is unchanged --
    # append_history() has its own duplicate check, so this is safe either way.
    try:
        append_history(rows, synced_at)
    except Exception as e:  # noqa: BLE001 - history is a bonus, never fail the whole run over it
        print(f"WARNING: could not update {HISTORY_OUT}: {e}", file=sys.stderr)

    # tmx_live.json is rewritten every successful run -- even when the trade
    # rows themselves are unchanged -- so "Last synced" always reflects that
    # the bot actually checked in, not just the last time a price moved.
    payload = {
        "status": "ok",
        "source": "Tanzania Mercantile Exchange (TMX), official market-data feed",
        "fetched_at_eat": synced_at,
        "session_date": session_date,
        "rows": rows,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"wrote {OUT}: {len(rows)} rows, session {session_date}")


if __name__ == "__main__":
    main()
