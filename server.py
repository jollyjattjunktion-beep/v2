import os
import logging
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify, send_from_directory
from scraper import scrape_crex_match

app = Flask(__name__, static_folder=".")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("preet_sports_v2")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://crex.com/",
}

def valid_crex_url(url):
    try:
        p = urlparse(url or "")
        return p.scheme == "https" and (p.hostname or "").lower() in {"crex.com", "www.crex.com"}
    except Exception:
        return False

def unavailable(source=None, reason="No reliable data source configured"):
    return {"status": "unavailable", "source": source, "reason": reason}

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "service": "preet-sports-v2", "version": 2})

@app.route("/api/scrape", methods=["GET", "POST"])
def api_scrape():
    payload = request.get_json(silent=True) or {}
    url = (request.args.get("url") or payload.get("url") or "").strip()
    if not valid_crex_url(url):
        return jsonify({"success": False, "error": "Provide an HTTPS CREX match URL on crex.com"}), 400
    data = scrape_crex_match(url)
    return jsonify(data), (200 if data.get("success") else 502)

@app.route("/api/crex-assets")
def api_crex_assets():
    """Fetch CREX page HTML for the scoreboard's client-side player/image parser."""
    url = (request.args.get("url") or "").strip()
    if not valid_crex_url(url):
        return jsonify({"success": False, "error": "Provide an HTTPS CREX match URL on crex.com"}), 400
    try:
        # Do not follow redirects to arbitrary hosts.
        response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=False)
        if 300 <= response.status_code < 400:
            return jsonify({
                "success": False,
                "error": "CREX returned a redirect; follow it only after validating the destination host.",
                "source_status": response.status_code,
                "location": response.headers.get("Location")
            }), 502
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower() and "<html" not in response.text[:1000].lower():
            return jsonify({"success": False, "error": "CREX response was not HTML", "content_type": content_type}), 502
        return jsonify({
            "success": True,
            "source": "CREX",
            "source_url": url,
            "source_status": response.status_code,
            "content_type": content_type,
            "html": response.text
        })
    except requests.RequestException as exc:
        logger.exception("CREX asset fetch failed")
        return jsonify({"success": False, "error": "Unable to fetch CREX page", "detail": str(exc), "source": "CREX"}), 502

@app.route("/api/data")
def api_data():
    """Return independent, provenance-labelled data sections; unavailable is explicit."""
    url = (request.args.get("url") or "").strip()
    if not valid_crex_url(url):
        return jsonify({"success": False, "error": "Provide an HTTPS CREX match URL on crex.com"}), 400
    live = scrape_crex_match(url)
    if not live.get("success"):
        return jsonify({
            "success": False,
            "source": "CREX",
            "source_url": url,
            "retrieved_at": None,
            "live_score": {"status": "error", "source": "CREX", "data": None, "error": live.get("error")},
            "lineups": unavailable("CREX", "Live page could not be parsed"),
            "portraits": unavailable("CREX", "No verified player-to-image mapping available"),
            "venue": unavailable("CREX"),
            "pitch": unavailable(),
            "weather": unavailable(),
            "head_to_head": unavailable(),
            "errors": [live.get("error", "Scrape failed")]
        }), 502
    has_score = bool(live.get("team1") or live.get("team2") or live.get("batsman1") or live.get("bowler"))
    venue_value = live.get("venue") or None
    return jsonify({
        "success": True,
        "match": {
            "source": "CREX",
            "source_url": url,
            "title": live.get("match_title") or None,
            "series": live.get("series_name") or None,
            "teams": [live.get("team1"), live.get("team2")]
        },
        "live_score": {
            "status": "ok" if has_score else "partial",
            "source": "CREX",
            "data": live
        },
        "lineups": {
            "status": "unavailable",
            "source": None,
            "confirmed": False,
            "teams": [],
            "reason": "The current scraper does not yet extract a confirmed full Playing XI. Active batters and yet-to-bat names are not a confirmed XI."
        },
        "portraits": {
            "status": "partial",
            "source": "CREX",
            "players": [],
            "reason": "The HTML asset endpoint supports client-side image discovery; backend verified player-to-image mapping is not yet implemented."
        },
        "venue": {
            "status": "ok" if venue_value else "unavailable",
            "source": "CREX SportsEvent JSON-LD" if venue_value else None,
            "name": venue_value
        },
        "pitch": unavailable(reason="No verified pitch-report extraction is configured"),
        "weather": unavailable(reason="No weather provider is configured"),
        "head_to_head": unavailable(reason="No historical match dataset/provider is configured"),
        "errors": []
    })

@app.route("/<path:path>")
def static_files(path):
    if os.path.isfile(path):
        return send_from_directory(".", path)
    return send_from_directory(".", "index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
