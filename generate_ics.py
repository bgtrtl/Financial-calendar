#!/usr/bin/env python3
"""
Génère un flux iCal (.ics) des publications de résultats (earnings)
pour une liste de tickers, à partir de l'API gratuite Finnhub.

Usage :
    export FINNHUB_API_KEY="votre_cle"
    python generate_ics.py            # écrit docs/earnings.ics

Aucune dépendance externe (bibliothèque standard uniquement).
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

API_URL = "https://finnhub.io/api/v1/calendar/earnings"
TICKERS_FILE = "tickers.txt"
OUTPUT_FILE = os.path.join("docs", "earnings.ics")
DAYS_BACK = 14      # garde les résultats récents visibles
DAYS_AHEAD = 180    # horizon de recherche

HOUR_LABELS = {
    "bmo": "avant l'ouverture",
    "amc": "après la clôture",
    "dmh": "pendant la séance",
}


def load_tickers(path):
    with open(path, encoding="utf-8") as f:
        return [
            line.split("#")[0].strip().upper()
            for line in f
            if line.split("#")[0].strip()
        ]


def fetch_earnings(symbol, api_key, start, end):
    params = urllib.parse.urlencode(
        {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "token": api_key}
    )
    req = urllib.request.Request(f"{API_URL}?{params}", headers={"User-Agent": "earnings-ics"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp).get("earningsCalendar", []) or []
        except urllib.error.HTTPError as e:
            if e.code == 429:  # limite de requêtes : on patiente
                time.sleep(5 * (attempt + 1))
                continue
            print(f"[{symbol}] erreur HTTP {e.code}", file=sys.stderr)
            return []
        except Exception as e:  # réseau, JSON invalide...
            print(f"[{symbol}] erreur : {e}", file=sys.stderr)
            time.sleep(2)
    return []


def escape(text):
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line):
    """Replie les lignes à 75 octets (RFC 5545)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        limit = 75 if not parts else 74
        if len(current) + len(b) > limit:
            parts.append(current.decode("utf-8"))
            current = b""
        current += b
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def fmt_number(value, suffix=""):
    if value is None:
        return "n.d."
    if abs(value) >= 1e9:
        return f"{value / 1e9:.2f} Md{suffix}"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.0f} M{suffix}"
    return f"{value:.2f}{suffix}"


def build_event(ev, stamp):
    symbol = ev["symbol"]
    d = datetime.strptime(ev["date"], "%Y-%m-%d").date()
    quarter, year = ev.get("quarter"), ev.get("year")
    period = f"T{quarter} {year}" if quarter and year else ""
    hour = HOUR_LABELS.get((ev.get("hour") or "").lower(), "horaire non précisé")

    summary = f"{symbol} – résultats {period}".strip() + f" ({hour})"
    lines_desc = [
        f"Société : {symbol}",
        f"Période : {period or 'n.d.'}",
        f"Moment : {hour}",
        f"BPA estimé : {fmt_number(ev.get('epsEstimate'))}",
        f"CA estimé : {fmt_number(ev.get('revenueEstimate'))}",
    ]
    if ev.get("epsActual") is not None:
        lines_desc.append(f"BPA publié : {fmt_number(ev.get('epsActual'))}")
    if ev.get("revenueActual") is not None:
        lines_desc.append(f"CA publié : {fmt_number(ev.get('revenueActual'))}")
    lines_desc.append("Horaire exact du call : voir la page Investor Relations.")

    uid = f"{symbol}-{year or d.year}-Q{quarter or 'x'}@earnings-ics"
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
        f"SUMMARY:{escape(summary)}",
        f"DESCRIPTION:{escape(chr(10).join(lines_desc))}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]


def build_calendar(events):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//earnings-ics//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Earnings – ma watchlist",
        "X-PUBLISHED-TTL:PT12H",
    ]
    for ev in events:
        out.extend(build_event(ev, stamp))
    out.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in out) + "\r\n"


def main():
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        sys.exit("FINNHUB_API_KEY manquante.")

    tickers = load_tickers(TICKERS_FILE)
    today = date.today()
    start, end = today - timedelta(days=DAYS_BACK), today + timedelta(days=DAYS_AHEAD)

    seen, events = set(), []
    for i, symbol in enumerate(tickers):
        for ev in fetch_earnings(symbol, api_key, start, end):
            if ev.get("symbol", "").upper() != symbol or not ev.get("date"):
                continue
            key = (symbol, ev.get("year"), ev.get("quarter"), ev["date"])
            if key not in seen:
                seen.add(key)
                events.append(ev)
        if i % 50 == 49:
            time.sleep(60)  # reste sous 60 requêtes/minute (offre gratuite)

    events.sort(key=lambda e: (e["date"], e["symbol"]))
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(build_calendar(events))
    print(f"{len(events)} événements écrits dans {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
