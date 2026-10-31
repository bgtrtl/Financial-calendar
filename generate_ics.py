#!/usr/bin/env python3
"""
Génère un flux iCal (.ics) des publications de résultats (earnings)
pour une liste de tickers, à partir de l'API gratuite Finnhub.
 
- Avant la publication : date, moment (avant ouverture / après clôture), estimations.
- Après la publication : compte rendu chiffré (BPA et CA publiés vs estimés,
  surprise en %, verdict battu / manqué) + lien vers le communiqué déposé à la SEC.
- L'historique est conservé dans docs/history.json : les événements passés restent
  dans le calendrier au lieu de disparaître.
 
Usage :
    export FINNHUB_API_KEY="votre_cle"
    python generate_ics.py            # écrit docs/earnings.ics et docs/history.json
 
Aucune dépendance externe (bibliothèque standard uniquement).
"""
 
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
 
API_URL = "https://finnhub.io/api/v1/calendar/earnings"
TICKERS_FILE = "tickers.txt"
OUTPUT_FILE = os.path.join("docs", "earnings.ics")
HISTORY_FILE = os.path.join("docs", "history.json")
DAYS_BACK = 21        # fenêtre interrogée dans le passé (rattrape les chiffres publiés)
DAYS_AHEAD = 180      # horizon de recherche
KEEP_DAYS = 730       # durée de conservation de l'historique (2 ans)
 
HOUR_LABELS = {
    "bmo": "avant l'ouverture",
    "amc": "après la clôture",
    "dmh": "pendant la séance",
}
 
 
# ---------------------------------------------------------------- données
 
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
 
 
def event_key(ev):
    """Identifiant stable d'une publication : ticker + exercice + trimestre."""
    if ev.get("year") and ev.get("quarter"):
        return f"{ev['symbol']}|{ev['year']}|Q{ev['quarter']}"
    return f"{ev['symbol']}|{ev['date']}"
 
 
def load_history(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
 
 
def merge(history, fetched):
    """Met à jour l'historique sans jamais effacer un chiffre déjà connu."""
    for ev in fetched:
        key = event_key(ev)
        old = history.get(key, {})
        merged = dict(old)
        for k, v in ev.items():
            if v is not None or k not in old:
                merged[k] = v
        history[key] = merged
    return history
 
 
def prune(history, tickers, today):
    limit = (today - timedelta(days=KEEP_DAYS)).isoformat()
    return {
        k: v for k, v in history.items()
        if v.get("symbol") in tickers and v.get("date", "") >= limit
    }
 
 
# ---------------------------------------------------------------- mise en forme
 
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
    if len(line.encode("utf-8")) <= 75:
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
 
 
def fmt_number(value):
    if value is None:
        return "n.d."
    if abs(value) >= 1e9:
        return f"{value / 1e9:.2f} Md"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.0f} M"
    return f"{value:.2f}"
 
 
def surprise(actual, estimate):
    """Écart en % entre publié et estimé (None si incalculable)."""
    if actual is None or estimate in (None, 0):
        return None
    return (actual - estimate) / abs(estimate) * 100
 
 
def fmt_pct(p):
    return "n.d." if p is None else f"{p:+.1f} %"
 
 
def verdict(p, tol=0.5):
    if p is None:
        return None
    if p > tol:
        return "battu"
    if p < -tol:
        return "manqué"
    return "en ligne"
 
 
def sec_link(symbol):
    return (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&CIK={urllib.parse.quote(symbol)}&type=8-K&dateb=&owner=include&count=10"
    )
 
 
def build_event(ev, stamp):
    symbol = ev["symbol"]
    d = datetime.strptime(ev["date"], "%Y-%m-%d").date()
    quarter, year = ev.get("quarter"), ev.get("year")
    period = f"T{quarter} {year}" if quarter and year else ""
    hour = HOUR_LABELS.get((ev.get("hour") or "").lower(), "horaire non précisé")
 
    eps_a, eps_e = ev.get("epsActual"), ev.get("epsEstimate")
    rev_a, rev_e = ev.get("revenueActual"), ev.get("revenueEstimate")
    published = eps_a is not None or rev_a is not None
 
    if published:
        eps_s, rev_s = surprise(eps_a, eps_e), surprise(rev_a, rev_e)
        tags = []
        if verdict(eps_s):
            tags.append(f"BPA {verdict(eps_s)} {fmt_pct(eps_s)}")
        if verdict(rev_s):
            tags.append(f"CA {verdict(rev_s)} {fmt_pct(rev_s)}")
        summary = f"✅ {symbol} {period} – " + (" · ".join(tags) or "résultats publiés")
        desc = [
            f"COMPTE RENDU – {symbol} {period}".strip(),
            f"Publié {hour} le {d.strftime('%d/%m/%Y')}",
            "",
            f"BPA : {fmt_number(eps_a)} publié vs {fmt_number(eps_e)} estimé "
            f"→ surprise {fmt_pct(eps_s)}" + (f" ({verdict(eps_s)})" if verdict(eps_s) else ""),
            f"CA : {fmt_number(rev_a)} publié vs {fmt_number(rev_e)} estimé "
            f"→ surprise {fmt_pct(rev_s)}" + (f" ({verdict(rev_s)})" if verdict(rev_s) else ""),
            "",
            f"Communiqué (8-K SEC) : {sec_link(symbol)}",
        ]
    else:
        summary = f"{symbol} – résultats {period}".strip() + f" ({hour})"
        desc = [
            f"Société : {symbol}",
            f"Période : {period or 'n.d.'}",
            f"Moment : {hour}",
            f"BPA estimé : {fmt_number(eps_e)}",
            f"CA estimé : {fmt_number(rev_e)}",
            "Horaire exact du call : voir la page Investor Relations.",
            "Le compte rendu chiffré s'ajoutera ici après la publication.",
        ]
 
    uid = f"{symbol}-{year or d.year}-Q{quarter or 'x'}@earnings-ics"
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"LAST-MODIFIED:{stamp}",
        f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
        f"SUMMARY:{escape(summary)}",
        f"DESCRIPTION:{escape(chr(10).join(desc))}",
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
 
 
# ---------------------------------------------------------------- programme
 
def main():
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        sys.exit("FINNHUB_API_KEY manquante.")
 
    tickers = load_tickers(TICKERS_FILE)
    today = date.today()
    start, end = today - timedelta(days=DAYS_BACK), today + timedelta(days=DAYS_AHEAD)
 
    fetched = []
    for i, symbol in enumerate(tickers):
        for ev in fetch_earnings(symbol, api_key, start, end):
            if ev.get("symbol", "").upper() == symbol and ev.get("date"):
                fetched.append(ev)
        if i % 50 == 49:
            time.sleep(60)  # reste sous 60 requêtes/minute (offre gratuite)
 
    history = prune(merge(load_history(HISTORY_FILE), fetched), set(tickers), today)
    events = sorted(history.values(), key=lambda e: (e["date"], e["symbol"]))
 
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(build_calendar(events))
 
    done = sum(1 for e in events if e.get("epsActual") is not None or e.get("revenueActual") is not None)
    print(f"{len(events)} événements écrits ({done} avec compte rendu) dans {OUTPUT_FILE}")
 
 
if __name__ == "__main__":
    main()
