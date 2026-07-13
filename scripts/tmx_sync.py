#!/usr/bin/env python3
"""
FURROW <- TMX live sync.
Reads the public Datawrapper chart TMX uses to publish its trade table
(chart ID ZJSS6 on tmx.co.tz > Market Data > Commodities Trade Information),
parses it defensively, and writes tmx_live.json for the site.

Fail-safe contract:
- On ANY failure, exits non-zero and writes NOTHING -> the last good
  tmx_live.json stays in place, GitHub emails the failed run, and the
  workflow opens/updates a 'tmx-pipe' issue.
- Only writes when it has confidently parsed at least MIN_ROWS rows.
"""
import csv
import io
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

CHART_ID = "ZJSS6"
MIN_ROWS = 2
OUT = "tmx_live.json"
EAT = timezone(timedelta(hours=3))

CANDIDATE_URLS = [
    f"https://datawrapper.dwcdn.net/{CHART_ID}/dataset.csv",
    f"https://datawrapper.dwcdn.net/{CHART_ID}/data.csv",
    f"https://datawrapper.dwcdn.net/{CHART_ID}/embed.json",
]

UA = {"User-Agent": "FURROW-price-board/1.0 (+https://www.joinfurrow.com; data attributed to TMX)"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


CODE_MARKERS = ("use strict", "function", "=>", "return {", "var ", "const ", "delimiters:")


def looks_like_code(s):
    head = s[:400]
    return any(m in head for m in CODE_MARKERS)


def csv_from_embed_json(text):
    """embed.json carries the chart data; prefer Datawrapper's canonical keys, never JS blobs."""
    obj = json.loads(text)

    # 1) Canonical: a key literally named chartData (string CSV/TSV)
    found = []

    def walk(o, key=None):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, str):
            found.append((key, o))

    walk(obj)
    for k, s in found:
        if k in ("chartData", "csv", "dataset") and s.count("\n") >= MIN_ROWS:
            return s

    # 2) Versioned dataset.csv on the CDN (embed.json usually names the published version)
    version = None
    for cand in ("publicVersion", "version"):
        v = obj.get(cand)
        if isinstance(v, int):
            version = v
            break
    if version is None:
        m = re.search(r'"(?:publicVersion|version)"\s*:\s*(\d+)', text)
        if m:
            version = int(m.group(1))
    if version is not None:
        try:
            body = fetch(f"https://datawrapper.dwcdn.net/{CHART_ID}/{version}/dataset.csv")
            if body.count("\n") >= MIN_ROWS and not looks_like_code(body):
                return body
        except Exception:  # noqa: BLE001 - fall through to heuristic
            pass

    # 3) Last resort: largest tabular string that is clearly NOT JavaScript
    best = None
    for _, s in found:
        if s.count("\n") >= MIN_ROWS and re.search(r"[,;\t]", s) and not looks_like_code(s):
            lines = [l for l in s.splitlines() if l.strip()][:6]
            delim_counts = {d: [l.count(d) for l in lines] for d in ",;\t"}
            consistent = any(len(set(cs)) == 1 and cs[0] >= 1 for cs in delim_counts.values())
            if consistent and (best is None or len(s) > len(best)):
                best = s
    return best


def parse_table(text):
    """Parse CSV/TSV with unknown delimiter and header names; map by keyword."""
    sample = text[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < MIN_ROWS + 1:
        raise ValueError(f"table too small: {len(rows)} rows")

    header = [h.strip().lower() for h in rows[0]]

    def col(*keys):
        for i, h in enumerate(header):
            if any(k in h for k in keys):
                return i
        return None

    ci = {
        "commodity": col("commodity", "bidhaa", "crop", "product"),
        "warehouse": col("warehouse", "ghala", "region", "location", "centre", "center"),
        "low":       col("low", "min", "chini"),
        "high":      col("high", "max", "juu"),
        "clearing":  col("clear", "settle", "closing", "price"),
        "change":    col("change", "chg", "badiliko", "%"),
        "session":   col("date", "session", "tarehe"),
    }
    if ci["commodity"] is None or (ci["clearing"] is None and ci["high"] is None):
        raise ValueError(
            "could not map columns from header: "
            f"{header} | first data row: {rows[1][:6] if len(rows) > 1 else 'n/a'}"
        )

    def num(s):
        if s is None:
            return None
        s = re.sub(r"[^\d.\-]", "", str(s))
        try:
            return float(s) if s not in ("", "-", ".") else None
        except ValueError:
            return None

    out, session_date = [], None
    for r in rows[1:]:
        def cell(k):
            i = ci[k]
            return r[i].strip() if i is not None and i < len(r) else None

        commodity = cell("commodity")
        if not commodity:
            continue
        clearing = num(cell("clearing"))
        high = num(cell("high"))
        low = num(cell("low"))
        if clearing is None and high is None:
            continue
        chg_raw = cell("change")
        chg = num(chg_raw)
        direction = "flat"
        if chg is not None:
            direction = "up" if chg > 0 else ("dn" if chg < 0 else "flat")
        elif chg_raw:
            if "-" in chg_raw:
                direction = "dn"
            elif re.search(r"\d", chg_raw):
                direction = "up"
        if session_date is None:
            session_date = cell("session")
        out.append({
            "commodity": commodity,
            "warehouse": cell("warehouse") or "",
            "low": low,
            "high": high,
            "clearing": clearing if clearing is not None else high,
            "change_pct": chg,
            "change_raw": chg_raw or "",
            "dir": direction,
        })
    if len(out) < MIN_ROWS:
        raise ValueError(f"parsed only {len(out)} usable rows")
    return out, session_date


def main():
    errors = []
    table_text = None
    for url in CANDIDATE_URLS:
        try:
            body = fetch(url)
            table_text = csv_from_embed_json(body) if url.endswith(".json") else body
            if table_text and table_text.count("\n") >= MIN_ROWS:
                print(f"fetched table via {url}")
                break
            table_text = None
            errors.append(f"{url}: no tabular payload")
        except Exception as e:  # noqa: BLE001 - collect and report every failure mode
            errors.append(f"{url}: {e}")
    if not table_text:
        print("FETCH FAILED:\n  " + "\n  ".join(errors), file=sys.stderr)
        sys.exit(1)

    try:
        rows, session_date = parse_table(table_text)
    except Exception as e:  # noqa: BLE001
        print(f"PARSE FAILED: {e}\nFirst 500 chars of payload:\n{table_text[:500]}", file=sys.stderr)
        sys.exit(1)

    # Preserve previous rows' fetched_at if data is identical (avoids commit noise)
    try:
        prev = json.load(open(OUT))
        if prev.get("rows") == rows:
            print("rows unchanged; leaving file as-is")
            return
    except Exception:  # noqa: BLE001 - no previous file or unreadable: proceed to write
        pass

    payload = {
        "status": "ok",
        "source": "Tanzania Mercantile Exchange (TMX), published trade table",
        "chart_id": CHART_ID,
        "fetched_at_eat": datetime.now(EAT).strftime("%Y-%m-%d %H:%M EAT"),
        "session_date": session_date,
        "rows": rows,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"wrote {OUT}: {len(rows)} rows, session {session_date}")


if __name__ == "__main__":
    main()
