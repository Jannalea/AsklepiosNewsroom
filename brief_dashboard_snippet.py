# -*- coding: utf-8 -*-
"""
Asklepios Newsroom-Cockpit  –  taegliches Befuellen des Dashboards
==================================================================

Diese Funktion fuegt sich in eure bestehende brief.py ein. Sie braucht
NICHTS zusaetzlich installiert (nur Standardbibliothek: json, re).
Es wird KEINE separate JSON-Datei erzeugt – die Artikel werden direkt
in die fertige dashboard.html eingebacken (in den von uns markierten
Platzhalter-Block). Genau wie ihr die E-Mail-HTMLs schon erzeugt.

Ablauf im Tagesbetrieb:
  1. brief.py sammelt wie gewohnt die Meldungen der drei Quellen.
  2. brief.py baut daraus eine Liste `items` (siehe Schema unten).
  3. update_dashboard(items) ueberschreibt den Feed-Block in dashboard.html.
  4. Nutzer:in oeffnet dashboard.html (Lesezeichen / Startseite) -> aktuell.

Per Cron / Aufgabenplanung einmal morgens laufen lassen.
"""

import json
import re

# ---------------------------------------------------------------------------
# Schema fuer jeden Eintrag in `items` (ein dict pro Artikel):
#
#   feed       (Pflicht)  "briefing" | "stellen" | "radar"
#                         -> steuert Farbe (Petrol/Magenta/Navy), Reihenfolge
#                            und die Spalte in der "Spalten"-Ansicht
#   source     (Pflicht)  z.B. "medinfoweb.de", "stepstone.de", "NDR.de"
#   category   (Pflicht)  frei waehlbarer Label-Text, z.B. "Gesundheitspolitik",
#                         "Stellenmarkt", "Wettbewerber"
#   title      (Pflicht)  Schlagzeile
#   url        (empfohlen) Link zum Artikel (Klick auf Kachel oeffnet ihn)
#   summary    (empfohlen) 1-2 Saetze Anriss
#   date       (empfohlen) ISO-String "YYYY-MM-DDTHH:MM:SS" (Veroeffentlichung)
#   relevance  (optional)  nur fuer feed="radar": "Hoch" | "Mittel" | "Niedrig"
#
# Reihenfolge in der Liste ist egal – das Dashboard sortiert selbst
# (Standard: Morning Briefing -> Stellenreport -> Wettbewerbs-Radar, neueste oben).
# ---------------------------------------------------------------------------

_FEED_RE = re.compile(
    r"/\* ===== ASKLEPIOS-FEED:START.*?ASKLEPIOS-FEED:END ===== \*/",
    re.S,
)


def update_dashboard(items, path="dashboard.html"):
    """Schreibt die Tages-Artikel in den Platzhalter-Block von dashboard.html."""
    payload = json.dumps(items, ensure_ascii=False)
    new_block = (
        "/* ===== ASKLEPIOS-FEED:START - taeglich von brief.py ersetzt ===== */\n"
        "  window.__ASK_FEED__ = " + payload + ";\n"
        "  /* ===== ASKLEPIOS-FEED:END ===== */"
    )

    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()

    if not _FEED_RE.search(html):
        raise RuntimeError("Feed-Platzhalter in %s nicht gefunden." % path)

    # lambda statt String, damit Backslashes/Sonderzeichen nicht interpretiert werden
    html = _FEED_RE.sub(lambda m: new_block, html, count=1)

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)


# ---------------------------------------------------------------------------
# Beispiel (zum Testen). In brief.py ersetzt ihr `demo` durch eure echten,
# aus den Feeds gesammelten Meldungen.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    demo = [
        {
            "feed": "briefing",
            "source": "medinfoweb.de",
            "category": "Gesundheitspolitik",
            "title": "Bundesrat lehnt GKV-Reform ab",
            "summary": "Der Bundesrat kritisiert das geplante Gesetz in einer "
                       "umfangreichen Stellungnahme scharf.",
            "url": "https://medinfoweb.de/...",
            "date": "2026-06-18T07:40:00",
        },
        {
            "feed": "stellen",
            "source": "stepstone.de",
            "category": "Stellenmarkt",
            "title": "Personalreferent (w/m/d)",
            "summary": "Asklepios Klinik Barmbek - Hamburg.",
            "url": "https://www.stepstone.de/...",
            "date": "2026-06-18T08:10:00",
        },
        {
            "feed": "radar",
            "source": "NDR.de",
            "category": "Wettbewerber",
            "title": "UKE buendelt Traumaversorgung am Standort Eppendorf",
            "summary": "Grossinvestition mit Sogwirkung auf Zuweiser und Personal.",
            "url": "https://www.ndr.de/...",
            "date": "2026-06-18T06:30:00",
            "relevance": "Hoch",
        },
    ]
    update_dashboard(demo, "dashboard.html")
    print("dashboard.html aktualisiert:", len(demo), "Meldungen")
