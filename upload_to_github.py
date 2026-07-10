# -*- coding: utf-8 -*-
import urllib.request, urllib.error, json, base64, os, sys, ssl
from pathlib import Path

# Firmennetzwerk verwendet SSL-Inspektion - Zertifikatspruefung deaktivieren
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _load_env():
    env_file = Path(__file__).parent / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass

_load_env()

OWNER = "jannalea"
REPO  = "AsklepiosNewsroom"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

def upload():
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(html_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    api_url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/index.html"
    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "AsklepiosNewsroom",
    }

    # SHA des bestehenden Eintrags holen (benoetigt fuer Updates)
    sha = None
    try:
        with urllib.request.urlopen(urllib.request.Request(api_url, headers=headers), context=_SSL_CTX, timeout=30) as r:
            sha = json.loads(r.read())["sha"]
    except (urllib.error.HTTPError, Exception):
        pass

    body = {"message": "Dashboard aktualisiert", "content": content, "branch": "main"}
    if sha:
        body["sha"] = sha

    req = urllib.request.Request(
        api_url,
        data=json.dumps(body).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as r:
        url = json.loads(r.read())["content"]["html_url"].replace(
            "github.com", "jannalea.github.io"
        ).replace(f"/blob/main", "").replace(f"{REPO}/", f"{REPO}/")
        # GitHub Pages URL ableiten
        pages_url = f"https://{OWNER}.github.io/{REPO}/"
        print(f"Hochgeladen. Erreichbar unter: {pages_url}")

if __name__ == "__main__":
    try:
        upload()
    except Exception as e:
        print(f"Upload fehlgeschlagen: {e}")
        if os.environ.get("GITHUB_ACTIONS"):
            raise SystemExit(1)
