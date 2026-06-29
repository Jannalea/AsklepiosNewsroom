# -*- coding: utf-8 -*-
"""
scripts/update-feed.py
Taeglich per GitHub Actions: befuellt index.html mit aktuellen Meldungen.
Quellen:  Morning Brief  → briefing-Feed
          Wettbewerbsreport → radar-Feed
          Stellenmarktreport (Google News, da Scraping in CI geblockt) → stellen-Feed
"""

import re, ssl, json, time, datetime as dt, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

# ── Pfade ────────────────────────────────────────────────────────────────────

INDEX_PATH = Path(__file__).parent.parent / "index.html"

_FEED_RE  = re.compile(
    r"/\* ===== ASKLEPIOS-FEED:START.*?ASKLEPIOS-FEED:END ===== \*/", re.S)
_CTRL_RE  = re.compile(r"[\x00-\x1f\x7f]")

# ── SSL (GitHub Actions CA ist in Ordnung; corporate Proxy deaktiviert) ──────

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE

# ── Quellen: Briefing (aus Morning Brief/brief.py) ────────────────────────────

BRIEFING_FEEDS = [
    {"name": "medinfoweb",   "url": "https://medinfoweb.de/feed/"},
    {"name": "GKV-Politik",  "url": "https://news.google.com/rss/search?q=Krankenhausreform+OR+GKV-Reform+OR+Stabilisierungsgesetz+OR+Bundesgesundheitsminister&hl=de&gl=DE&ceid=DE:de"},
    {"name": "Klinikmarkt",  "url": "https://news.google.com/rss/search?q=Klinikinsolvenz+OR+Krankenhausschlie%C3%9Fung+OR+Krankenhausfinanzierung+OR+DRG&hl=de&gl=DE&ceid=DE:de"},
    {"name": "Hamburg",      "url": "https://news.google.com/rss/search?q=Asklepios+OR+%22UKE+Hamburg%22+OR+%22Klinik+Hamburg%22&hl=de&gl=DE&ceid=DE:de"},
]

KATEGORIEN = [
    {"label": "Aufmacher",                  "category": "Gesundheitspolitik",
     "keywords": ["bundesrat", "bundestag", "gkv-reform", "krankenhausreform",
                  "stabilisierungsgesetz", "spargesetz", "gmk", "ministerium"],
     "exclude": ["geschäftsführer", "personalien", "wechsel"], "max": 1},
    {"label": "Klinikmanagement & Strategie", "category": "Klinikmanagement & Strategie",
     "keywords": ["klinik", "krankenhaus", "strategie", "qualität", "zertifizierung",
                  "ambulant", "stationär", "versorgung", "kapazität", "personal"],
     "exclude": ["geschäftsführer wechselt", "verlässt", "tritt zurück"], "max": 2},
    {"label": "Gesundheitspolitik",         "category": "Gesundheitspolitik",
     "keywords": ["gkv", "g-ba", "gesetz", "verordnung", "politik", "reform",
                  "regulatorik", "koalition", "beitrag", "zulassung"],
     "exclude": [], "max": 2},
    {"label": "Finanzen & Erlöse",          "category": "Finanzen & Erlöse",
     "keywords": ["vergütung", "drg", "budget", "finanzierung", "defizit", "erlös",
                  "investition", "insolvenz", "casemix", "tarif", "kostensteigerung"],
     "exclude": [], "max": 2},
    {"label": "Hamburg & Asklepios",        "category": "Hamburg & Asklepios",
     "keywords": ["hamburg", "asklepios", "uke", "schlotzhauer", "altona",
                  "barmbek", "harburg", "st. georg", "gemmel"],
     "exclude": [], "max": 2},
]

# ── Quellen: Radar (aus Wettbewerbsreport/brief.py) ───────────────────────────

RADAR_SOURCES = [
    {"name": "Universitätsklinikum Hamburg-Eppendorf", "category": "Universitätsklinikum", "relevance": "Hoch",
     "gnews": '"UKE Hamburg" OR "Universitätsklinikum Hamburg-Eppendorf"'},
    {"name": "Helios ENDO-Klinik / Mariahilf Hamburg", "category": "Privater Konzern", "relevance": "Hoch",
     "gnews": '"Helios" "Hamburg" Klinik'},
    {"name": "Albertinen Krankenhaus",                 "category": "Konfessionell",    "relevance": "Mittel",
     "gnews": '"Albertinen" Hamburg Krankenhaus'},
    {"name": "Katholisches Marienkrankenhaus",         "category": "Konfessionell",    "relevance": "Mittel",
     "gnews": '"Marienkrankenhaus Hamburg"'},
    {"name": "Schön Klinik Hamburg Eilbek",            "category": "Privater Konzern", "relevance": "Mittel",
     "gnews": '"Schön Klinik" Hamburg OR "Eilbek"'},
    {"name": "Agaplesion Diakonieklinikum Hamburg",    "category": "Konfessionell",    "relevance": "Mittel",
     "gnews": '"Agaplesion" Hamburg OR "Diakonieklinikum Hamburg"'},
]

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _clean(text):
    return _CTRL_RE.sub(" ", text or "").strip()


def _strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()[:300]


def _gnews_url(query, days=7):
    q = quote(f"{query} when:{days}d")
    return f"https://news.google.com/rss/search?q={q}&hl=de&gl=DE&ceid=DE:de"


def _fetch(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AsklepiosNewsroom/1.0"})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"  Warnung: {url[:60]}: {e}", flush=True)
        return None


def _parse_feed(raw):
    """Parst RSS 2.0, Atom und RSS 1.0/RDF. Gibt Liste von Dicts zurueck."""
    if not raw:
        return []
    try:
        # XML-Deklaration mit korrekter Encoding-Angabe vorsetzen
        if not raw.lstrip()[:5] in (b"<?xml", b"<rss ", b"<feed", b"<RDF:"):
            raw = b'<?xml version="1.0" encoding="utf-8"?>' + raw
        root = ET.fromstring(raw)
    except ET.ParseError:
        try:
            root = ET.fromstring(raw.decode("utf-8", errors="replace").encode("utf-8"))
        except ET.ParseError as e:
            print(f"  XML-Fehler: {e}", flush=True)
            return []

    items = []
    NS_RSS1 = "http://purl.org/rss/1.0/"
    NS_DC   = "http://purl.org/dc/elements/1.1/"
    NS_ATOM = "http://www.w3.org/2005/Atom"

    def _tag(el):
        return el.tag.split("}")[-1].lower()

    for el in root.iter():
        if _tag(el) not in ("item", "entry"):
            continue
        title = link = pub = desc = ""
        for child in el:
            t = _tag(child)
            if t == "title":
                title = (child.text or "").strip()
            elif t == "link":
                link = child.get("href") or child.text or ""
                link = link.strip()
            elif t in ("pubdate", "published", "updated", "date"):
                pub = (child.text or "").strip()
            elif t in ("description", "summary", "content"):
                desc = (child.text or desc or "").strip()
        if title:
            items.append({"title": _strip_html(title), "link": link,
                          "desc": _strip_html(desc), "pub": pub})
    return items


def _parse_date(s):
    if not s:
        return dt.datetime.now()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
    return dt.datetime.now()


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S")


# ── Dashboard schreiben (merge-faehig) ───────────────────────────────────────

def update_dashboard(items, path=INDEX_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()
    if not _FEED_RE.search(html):
        raise RuntimeError(f"Feed-Platzhalter nicht gefunden in {path}")
    # Bestehende Items anderer Feed-Typen behalten
    existing = []
    m = _FEED_RE.search(html)
    if m:
        blk = m.group(0)
        s, e = blk.find("["), blk.rfind("]")
        if s != -1 and e > s:
            try:
                existing = json.loads(blk[s:e+1])
            except Exception:
                existing = []
    new_feeds = {it["feed"] for it in items}
    merged = [it for it in existing
              if isinstance(it, dict) and it.get("feed") not in new_feeds] + items
    payload = json.dumps(merged, ensure_ascii=False)
    new_block = (
        "/* ===== ASKLEPIOS-FEED:START - taeglich von brief.py ersetzt ===== */\n"
        "  window.__ASK_FEED__ = " + payload + ";\n"
        "  /* ===== ASKLEPIOS-FEED:END ===== */"
    )
    html = _FEED_RE.sub(lambda _: new_block, html, count=1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)


# ── Briefing ──────────────────────────────────────────────────────────────────

def get_briefing():
    raw_articles = []
    for feed in BRIEFING_FEEDS:
        data = _fetch(feed["url"])
        for item in _parse_feed(data)[:8]:
            text = (item["title"] + " " + item["desc"]).lower()
            raw_articles.append({
                "source": feed["name"],
                "title":  item["title"],
                "link":   item["link"],
                "desc":   item["desc"],
                "text":   text,
                "date":   _parse_date(item["pub"]),
            })

    result = []
    used = set()
    for kat in KATEGORIEN:
        count = 0
        for a in raw_articles:
            if id(a) in used:
                continue
            has_kw = any(kw in a["text"] for kw in kat["keywords"])
            has_ex = any(ex in a["text"] for ex in kat["exclude"])
            if has_kw and not has_ex:
                result.append({
                    "feed":     "briefing",
                    "source":   _clean(a["source"]),
                    "category": kat["category"],
                    "title":    _clean(a["title"]),
                    "url":      a["link"],
                    "summary":  _clean(a["desc"]),
                    "date":     _iso(a["date"]),
                })
                used.add(id(a))
                count += 1
                if count >= kat["max"]:
                    break
    return result


# ── Radar ─────────────────────────────────────────────────────────────────────

def get_radar():
    """
    Quoted-term-Suche in Google News stellt sicher, dass nur Artikel mit dem
    Krankenhausnamen zurueckkommen. Kein sekundaerer Keyword-Filter noetig.
    """
    result = []
    for src in RADAR_SOURCES:
        url   = _gnews_url(src["gnews"])
        data  = _fetch(url)
        items = _parse_feed(data)
        time.sleep(1.0)
        count = 0
        for item in items:
            title = item["title"]
            if " - " in title:
                title = title.rsplit(" - ", 1)[0].strip()
            if not title:
                continue
            result.append({
                "feed":      "radar",
                "source":    src["name"],
                "category":  src["category"],
                "title":     _clean(title),
                "url":       item["link"],
                "summary":   _clean(item["desc"]),
                "date":      _iso(_parse_date(item["pub"])),
                "relevance": src["relevance"],
            })
            count += 1
            if count >= 3:
                break
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Morning Briefing ...", flush=True)
    briefing = get_briefing()
    print(f"  {len(briefing)} Meldungen", flush=True)

    print("Wettbewerbs-Radar ...", flush=True)
    radar = get_radar()
    print(f"  {len(radar)} Meldungen", flush=True)

    # Stellen kommen vom lokalen scraper.py (Stellenmarktreport) per upload_to_github.py
    # und werden hier nicht ueberschrieben (Merge-Logik in update_dashboard behaelt
    # bestehende "stellen"-Eintraege solange dieser Lauf keine liefert).

    all_items = briefing + radar
    if not all_items:
        print("WARNUNG: Keine Meldungen – index.html bleibt unveraendert.")
        raise SystemExit(1)

    update_dashboard(all_items, INDEX_PATH)
    print(f"index.html aktualisiert: {len(all_items)} Meldungen gesamt.", flush=True)
