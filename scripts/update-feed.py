# -*- coding: utf-8 -*-
"""
scripts/update-feed.py
Taeglich ausgefuehrt (GitHub Actions Cron oder lokal).
Ruft RSS-Feeds ab und schreibt die Ergebnisse in dashboard.html.
"""

import sys
import os
import re
import ssl
import datetime
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from brief_dashboard_snippet import update_dashboard

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

DASHBOARD_PATH = Path(__file__).parent.parent / "dashboard.html"

# XML namespaces
_NS_RSS1 = "http://purl.org/rss/1.0/"
_NS_DC   = "http://purl.org/dc/elements/1.1/"


def _fetch_rss(url, timeout=20):
    """Fetches a feed URL and returns a list of raw dicts. Handles RSS 2.0, Atom, and RSS 1.0/RDF."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AsklepiosNewsroom/1.0"})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        items = []

        # RSS 1.0 / RDF
        for item in root.findall(f"{{{_NS_RSS1}}}item"):
            items.append({
                "title":       (item.findtext(f"{{{_NS_RSS1}}}title") or "").strip(),
                "link":        (item.findtext(f"{{{_NS_RSS1}}}link") or "").strip(),
                "description": re.sub(r"<[^>]+>", "", item.findtext(f"{{{_NS_RSS1}}}description") or "").strip(),
                "pubDate":     item.findtext(f"{{{_NS_DC}}}date") or item.findtext(f"{{{_NS_RSS1}}}pubDate") or "",
            })

        # RSS 2.0
        for item in root.findall(".//item"):
            items.append({
                "title":       (item.findtext("title") or "").strip(),
                "link":        (item.findtext("link") or "").strip(),
                "description": re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip(),
                "pubDate":     item.findtext("pubDate") or "",
            })

        # Atom
        for entry in root.findall(f".//{{{_NS_RSS1}}}entry"):
            link_el = entry.find(f"{{{_NS_RSS1}}}link")
            items.append({
                "title":       (entry.findtext(f"{{{_NS_RSS1}}}title") or "").strip(),
                "link":        link_el.get("href", "") if link_el is not None else "",
                "description": re.sub(r"<[^>]+>", "", entry.findtext(f"{{{_NS_RSS1}}}summary") or "").strip(),
                "pubDate":     entry.findtext(f"{{{_NS_RSS1}}}updated") or "",
            })

        # Deduplicate by link
        seen = set()
        unique = []
        for it in items:
            key = it.get("link") or it.get("title")
            if key and key not in seen:
                seen.add(key)
                unique.append(it)
        return unique

    except Exception as e:
        print(f"  Warnung: {url}: {e}", file=sys.stderr)
        return []


def _parse_date(s):
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except (ValueError, AttributeError):
            continue
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _build_items(raw, feed, source, category, max_items=6, relevance=None):
    result = []
    for entry in raw[:max_items]:
        if not entry.get("title"):
            continue
        item = {
            "feed":     feed,
            "source":   source,
            "category": category,
            "title":    entry["title"],
            "url":      entry["link"],
            "summary":  entry["description"][:280] if entry["description"] else "",
            "date":     _parse_date(entry["pubDate"]),
        }
        if relevance:
            item["relevance"] = relevance
        result.append(item)
    return result


def get_briefing():
    items = []
    for url, source, cat in [
        ("https://medinfoweb.de/feed/",  "medinfoweb.de", "Gesundheitspolitik"),
        ("https://bibliomed.de/feed/",   "bibliomed.de",  "Klinikmanagement & Strategie"),
    ]:
        raw = _fetch_rss(url)
        items += _build_items(raw, "briefing", source, cat, max_items=8)
    return items


def get_stellen():
    items = []
    for url, source in [
        ("https://karriere.asklepios.com/stellenangebote.rss", "karriere.asklepios.com"),
        ("https://www.stepstone.de/rss/jobs/?what=Asklepios",  "stepstone.de"),
    ]:
        raw = _fetch_rss(url)
        items += _build_items(raw, "stellen", source, "Stellenmarkt", max_items=10)
    return items


def get_radar():
    items = []
    for url, source, relevance in [
        ("https://www.ndr.de/nachrichten/hamburg/index~rdf.xml", "NDR.de", "Mittel"),
    ]:
        raw = _fetch_rss(url)
        items += _build_items(raw, "radar", source, "Wettbewerber", max_items=6, relevance=relevance)
    return items


if __name__ == "__main__":
    print("Morning Briefing ...")
    briefing = get_briefing()
    print(f"  {len(briefing)} Meldungen")

    print("Stellenreport ...")
    stellen = get_stellen()
    print(f"  {len(stellen)} Meldungen")

    print("Wettbewerbs-Radar ...")
    radar = get_radar()
    print(f"  {len(radar)} Meldungen")

    all_items = briefing + stellen + radar
    if not all_items:
        print("WARNUNG: Keine Meldungen abgerufen – Dashboard bleibt unveraendert.", file=sys.stderr)
        sys.exit(1)

    update_dashboard(all_items, str(DASHBOARD_PATH))
    print(f"dashboard.html aktualisiert: {len(all_items)} Meldungen gesamt.")
