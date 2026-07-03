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

# ── Quellen: Radar – pro Bundesland / Region ─────────────────────────────────

RADAR_SOURCES_BY_REGION = {
    "hamburg": [
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
    ],
    "schleswig_holstein": [
        {"name": "UKSH Kiel / Lübeck",           "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"UKSH" OR "Universitätsklinikum Schleswig-Holstein"'},
        {"name": "Schön Klinik Bad Bramstedt",   "category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"Schön Klinik" "Bad Bramstedt" OR "Schön Klinik" "Rendsburg"'},
        {"name": "Helios Klinikum Schleswig",    "category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"Helios Klinikum Schleswig" OR "Helios" "Schleswig" Krankenhaus'},
        {"name": "Sana Kliniken Lübeck",         "category": "Kommunal/Freigemeinnützig", "relevance": "Mittel",
         "gnews": '"Sana Kliniken" Lübeck OR "Sana" Schleswig-Holstein Krankenhaus'},
    ],
    "mecklenburg_vorpommern": [
        {"name": "Universitätsmedizin Greifswald", "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsmedizin Greifswald" OR "UMG Greifswald"'},
        {"name": "Universitätsmedizin Rostock",    "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsmedizin Rostock" OR "UMR Rostock"'},
        {"name": "Helios Kliniken Schwerin",       "category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"Helios" Schwerin Klinik OR "Helios Kliniken Schwerin"'},
        {"name": "Dietrich-Bonhoeffer-Klinikum Neubrandenburg", "category": "Kommunal/Freigemeinnützig", "relevance": "Niedrig",
         "gnews": '"Dietrich-Bonhoeffer-Klinikum" OR "DBK Neubrandenburg"'},
    ],
    "berlin_brandenburg": [
        {"name": "Charité Berlin",               "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Charité" Berlin Krankenhaus OR Klinik'},
        {"name": "Vivantes Berlin",              "category": "Kommunal/Freigemeinnützig", "relevance": "Hoch",
         "gnews": '"Vivantes" Berlin OR "Vivantes Netzwerk"'},
        {"name": "Helios Klinikum Berlin-Buch",  "category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"Helios" Berlin Klinikum OR "Berlin-Buch" Krankenhaus'},
        {"name": "DRK Kliniken Berlin",          "category": "Konfessionell",        "relevance": "Mittel",
         "gnews": '"DRK Kliniken Berlin" OR "DRK" Berlin Krankenhaus'},
        {"name": "Ernst von Bergmann Potsdam",   "category": "Kommunal/Freigemeinnützig", "relevance": "Niedrig",
         "gnews": '"Ernst von Bergmann" Potsdam OR "Klinikum Potsdam"'},
    ],
    "niedersachsen_bremen": [
        {"name": "MHH Hannover",                 "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Medizinische Hochschule Hannover" OR "MHH Hannover"'},
        {"name": "Klinikum Bremen-Mitte",        "category": "Kommunal/Freigemeinnützig", "relevance": "Hoch",
         "gnews": '"Klinikum Bremen-Mitte" OR "Klinikverbund Bremen" Krankenhaus'},
        {"name": "Helios Klinikum Hildesheim",   "category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"Helios Klinikum Hildesheim" OR "Helios" Hildesheim Krankenhaus'},
        {"name": "Klinikum Region Hannover",     "category": "Kommunal/Freigemeinnützig", "relevance": "Mittel",
         "gnews": '"Klinikum Region Hannover" OR "KRH Hannover"'},
    ],
    "nrw": [
        {"name": "Uniklinik Köln",               "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum Köln" OR "Uniklinik Köln"'},
        {"name": "Universitätsklinikum Düsseldorf", "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum Düsseldorf" OR "UKD Düsseldorf"'},
        {"name": "UK Essen",                     "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum Essen" OR "UK Essen"'},
        {"name": "Helios Klinikum Duisburg",     "category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"Helios" Duisburg Klinikum OR "Helios Klinikum Duisburg"'},
        {"name": "St. Franziskus Hospital Münster", "category": "Konfessionell",     "relevance": "Mittel",
         "gnews": '"St. Franziskus-Hospital Münster" OR "Franziskus" Münster Krankenhaus'},
    ],
    "hessen": [
        {"name": "Universitätsklinikum Frankfurt", "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum Frankfurt" OR "Uniklinik Frankfurt"'},
        {"name": "UKGM Gießen / Marburg",        "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"UKGM" OR "Universitätsklinikum Gießen" OR "Universitätsklinikum Marburg"'},
        {"name": "Helios HSK Wiesbaden",         "category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"Helios HSK" OR "Helios Dr. Horst Schmidt Kliniken" Wiesbaden'},
        {"name": "Agaplesion Markus Krankenhaus Frankfurt", "category": "Konfessionell", "relevance": "Mittel",
         "gnews": '"Agaplesion Markus Krankenhaus" OR "Agaplesion" Frankfurt Krankenhaus'},
    ],
    "rheinland_pfalz": [
        {"name": "Universitätsmedizin Mainz",    "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsmedizin Mainz" OR "Uniklinikum Mainz"'},
        {"name": "Gemeinschaftsklinikum Mittelrhein", "category": "Kommunal/Freigemeinnützig", "relevance": "Mittel",
         "gnews": '"Gemeinschaftsklinikum Mittelrhein" OR "GKM" Koblenz Krankenhaus'},
        {"name": "Marienhaus Kliniken",          "category": "Konfessionell",        "relevance": "Mittel",
         "gnews": '"Marienhaus Kliniken" OR "Marienhaus" Rheinland-Pfalz Krankenhaus'},
    ],
    "saarland": [
        {"name": "Universitätsklinikum des Saarlandes", "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum des Saarlandes" OR "UKS Homburg"'},
        {"name": "SHG-Kliniken Saarland",        "category": "Kommunal/Freigemeinnützig", "relevance": "Mittel",
         "gnews": '"SHG-Kliniken" OR "SHG Saarland" Krankenhaus'},
        {"name": "CaritasKlinikum Saarbrücken",  "category": "Konfessionell",        "relevance": "Mittel",
         "gnews": '"CaritasKlinikum Saarbrücken" OR "Caritasklinikum Saarbrücken"'},
    ],
    "sachsen": [
        {"name": "Universitätsklinikum Dresden", "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum Dresden" OR "UKD Dresden"'},
        {"name": "Universitätsklinikum Leipzig", "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum Leipzig" OR "UKL Leipzig"'},
        {"name": "Helios Park-Klinikum Leipzig", "category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"Helios Park-Klinikum" OR "Helios" Leipzig Klinikum'},
        {"name": "Klinikum St. Georg Leipzig",   "category": "Kommunal/Freigemeinnützig", "relevance": "Mittel",
         "gnews": '"Klinikum St. Georg" Leipzig OR "St. Georg" Leipzig Krankenhaus'},
    ],
    "sachsen_anhalt": [
        {"name": "Universitätsklinikum Halle",   "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum Halle" OR "UKH Halle"'},
        {"name": "Universitätsmedizin Magdeburg","category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsmedizin Magdeburg" OR "UKMD Magdeburg"'},
        {"name": "AMEOS Kliniken Sachsen-Anhalt","category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"AMEOS" Sachsen-Anhalt OR "AMEOS Kliniken" Krankenhaus'},
    ],
    "thueringen": [
        {"name": "Universitätsklinikum Jena",    "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum Jena" OR "UKJ Jena"'},
        {"name": "SRH Wald-Klinikum Gera",       "category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"SRH Wald-Klinikum Gera" OR "SRH" Gera Krankenhaus'},
        {"name": "Zentralklinik Bad Berka",      "category": "Kommunal/Freigemeinnützig", "relevance": "Mittel",
         "gnews": '"Zentralklinik Bad Berka" OR "ZKB" Thüringen Klinik'},
    ],
    "bayern": [
        {"name": "LMU Klinikum München",         "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"LMU Klinikum" OR "Klinikum der Universität München"'},
        {"name": "Klinikum rechts der Isar",     "category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Klinikum rechts der Isar" OR "MRI München"'},
        {"name": "Universitätsklinikum Augsburg","category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum Augsburg" OR "UKA Augsburg"'},
        {"name": "Helios Amper-Klinikum Dachau", "category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"Helios Amper-Klinikum" OR "Helios" Dachau Krankenhaus'},
        {"name": "Schön Klinik München",         "category": "Privater Konzern",     "relevance": "Mittel",
         "gnews": '"Schön Klinik" München OR "Schön Klinik Harlaching"'},
    ],
    "bw": [
        {"name": "Universitätsklinikum Freiburg","category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum Freiburg" OR "UKF Freiburg"'},
        {"name": "Universitätsklinikum Tübingen","category": "Universitätsklinikum", "relevance": "Hoch",
         "gnews": '"Universitätsklinikum Tübingen" OR "UKT Tübingen"'},
        {"name": "Robert-Bosch-Krankenhaus Stuttgart", "category": "Freigemeinnützig", "relevance": "Mittel",
         "gnews": '"Robert-Bosch-Krankenhaus" OR "RBK Stuttgart"'},
        {"name": "Klinikum Stuttgart",           "category": "Kommunal/Freigemeinnützig", "relevance": "Mittel",
         "gnews": '"Klinikum Stuttgart" OR "Katharinenhospital Stuttgart"'},
        {"name": "Vinzenz von Paul Kliniken",    "category": "Konfessionell",        "relevance": "Mittel",
         "gnews": '"Vinzenz von Paul" OR "Vinzenz Kliniken" Baden-Württemberg'},
    ],
}

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
    payload = json.dumps(merged, ensure_ascii=False).replace('</script>', r'<\/script>')
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
    Quoted-term-Suche in Google News pro Bundesland/Region.
    Jeder Treffer bekommt ein 'region'-Feld fuer den Dashboard-Filter.
    """
    result = []
    for region, sources in RADAR_SOURCES_BY_REGION.items():
        for src in sources:
            url   = _gnews_url(src["gnews"])
            data  = _fetch(url)
            items = _parse_feed(data)
            time.sleep(0.8)
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
                    "region":    region,
                })
                count += 1
                if count >= 2:
                    break
    return result


# ── Stellen ───────────────────────────────────────────────────────────────────

# Bundesland → Suchbegriffe fuer Google News
REGION_LABELS = {
    "hamburg":               "Hamburg",
    "schleswig_holstein":    "Schleswig-Holstein",
    "mecklenburg_vorpommern":"Mecklenburg-Vorpommern",
    "berlin_brandenburg":    "Berlin OR Brandenburg",
    "niedersachsen_bremen":  "Niedersachsen OR Bremen",
    "nrw":                   "Nordrhein-Westfalen",
    "hessen":                "Hessen",
    "rheinland_pfalz":       "Rheinland-Pfalz",
    "saarland":              "Saarland",
    "sachsen":               "Sachsen",
    "sachsen_anhalt":        "Sachsen-Anhalt",
    "thueringen":            "Thüringen",
    "bayern":                "Bayern",
    "bw":                    "Baden-Württemberg",
}

STELLEN_BUNDESWEIT = [
    {
        "category": "GF/Management Asklepios",
        "gnews": ('Asklepios (Geschäftsführer OR Geschäftsführerin OR Klinikdirektor'
                  ' OR Klinikmanager OR Regionalleiter OR Regionalgeschäftsführer)'),
    },
    {
        "category": "Chefarzt Asklepios",
        "gnews": ('Asklepios (Chefarzt OR Chefärztin OR "Leitender Arzt"'
                  ' OR "Leitende Ärztin" OR Klinikchef OR Klinikchefin)'),
    },
]


def get_stellen():
    """
    Stellen-Feed:
      – GF/Management Asklepios      → bundesweit (region='bundesweit')
      – Chefarzt Asklepios           → bundesweit
      – GF Gesundheitsunternehmen    → regionsgefiltert
      – Kaufm. Leitung Asklepios     → regionsgefiltert
    Nicht enthalten: Sekretariats- und Assistenzpositionen.
    """
    result = []
    seen = set()

    def _add(items_raw, category, region, source_label):
        for item in items_raw:
            title = item["title"]
            if " - " in title:
                title = title.rsplit(" - ", 1)[0].strip()
            title = _clean(title)
            if not title or title in seen:
                continue
            # Sekretariat / Assistenz explizit ausschliessen
            tl = title.lower()
            if any(w in tl for w in ("sekretär", "sekretärin", "assistenz", "rezeption",
                                     "empfang", "pflegeassist")):
                continue
            seen.add(title)
            result.append({
                "feed":     "stellen",
                "source":   source_label,
                "category": category,
                "title":    title,
                "url":      item["link"],
                "summary":  _clean(item["desc"]),
                "date":     _iso(_parse_date(item["pub"])),
                "region":   region,
            })

    # ── Bundesweit: Asklepios GF + Chefarzt ──
    for src in STELLEN_BUNDESWEIT:
        data = _fetch(_gnews_url(src["gnews"], days=30))
        _add(_parse_feed(data)[:4], src["category"], "bundesweit", "Google News")
        time.sleep(0.8)

    # ── Regional: GF Gesundheitsunternehmen + Kaufm. Leitung Asklepios ──
    for region, label in REGION_LABELS.items():
        gf_q = (f'({label}) (Krankenhaus OR Klinik OR Gesundheit)'
                f' (Geschäftsführer OR Geschäftsführerin OR Klinikleitung)')
        data = _fetch(_gnews_url(gf_q, days=30))
        _add(_parse_feed(data)[:2], "GF Gesundheitsunternehmen", region, "Google News")
        time.sleep(0.6)

        kfm_q = (f'Asklepios ({label})'
                 f' ("kaufmännische Leitung" OR "kaufmännischer Direktor"'
                 f' OR "Verwaltungsleitung" OR "Koordinator" OR "Koordinatorin")')
        data = _fetch(_gnews_url(kfm_q, days=30))
        _add(_parse_feed(data)[:2], "Kaufm. Leitung Asklepios", region, "Google News")
        time.sleep(0.6)

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Morning Briefing ...", flush=True)
    briefing = get_briefing()
    print(f"  {len(briefing)} Meldungen", flush=True)

    print("Wettbewerbs-Radar ...", flush=True)
    radar = get_radar()
    print(f"  {len(radar)} Meldungen", flush=True)

    print("Stellenmarkt ...", flush=True)
    stellen = get_stellen()
    print(f"  {len(stellen)} Meldungen", flush=True)

    all_items = briefing + stellen + radar
    if not all_items:
        print("WARNUNG: Keine Meldungen – index.html bleibt unveraendert.")
        raise SystemExit(1)

    update_dashboard(all_items, INDEX_PATH)
    print(f"index.html aktualisiert: {len(all_items)} Meldungen gesamt.", flush=True)
