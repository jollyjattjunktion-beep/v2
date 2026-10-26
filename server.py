import os
import re
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
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
PLACEHOLDER_RE = re.compile(r"(placeholder|default[-_ ]?(avatar|player)|no[-_ ]?(image|photo|avatar)|unknown|dummy|blank|avatar[-_ ]?default|/(placeholder|default|noimage))", re.I)
BAD_IMAGE_EXTENSIONS = (".svg",)
IMAGE_HOST_ALLOWLIST = {"cricketvectors.akamaized.net", "crex.com", "www.crex.com"}

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def valid_crex_url(url):
    try:
        p = urlparse(url or "")
        return p.scheme == "https" and (p.hostname or "").lower() in {"crex.com", "www.crex.com"}
    except Exception:
        return False

def unavailable(source=None, reason="No reliable data source configured", **extra):
    return {"status": "unavailable", "source": source, "retrieved_at": utc_now(), "reason": reason, **extra}

def normalize_name(value):
    value = str(value or "").casefold()
    value = re.sub(r"\b(mr|mrs|ms|dr)\.?\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def valid_image_url(raw, page_url):
    if not raw:
        return None
    raw = str(raw).strip()
    if not raw or raw.startswith(("data:", "blob:", "javascript:")) or PLACEHOLDER_RE.search(raw):
        return None
    url = urljoin(page_url, raw)
    try:
        p = urlparse(url)
        if p.scheme != "https" or not p.hostname or p.hostname.lower() not in IMAGE_HOST_ALLOWLIST:
            return None
        if p.path.lower().endswith(BAD_IMAGE_EXTENSIONS):
            return None
        return url
    except Exception:
        return None

def player_names_from_score(data):
    players = []
    for key, role in (("batsman1", "batter"), ("batsman2", "batter"), ("bowler", "bowler")):
        obj = data.get(key)
        if isinstance(obj, dict) and obj.get("name"):
            players.append({"name": str(obj["name"]).strip(), "role": role})
    for key in ("next_batsmen", "next_bowlers"):
        vals = data.get(key)
        if isinstance(vals, list):
            for obj in vals:
                name = obj.get("name") if isinstance(obj, dict) else obj
                if name:
                    players.append({"name": str(name).strip(), "role": "up-next"})
    unique = {}
    for p in players:
        unique.setdefault(normalize_name(p["name"]), p)
    return list(unique.values())

def build_portrait_map(html, page_url, live):
    """Only associates a portrait when the nearby DOM text matches a player name exactly."""
    soup = BeautifulSoup(html or "", "html.parser")
    players = player_names_from_score(live)
    names = {normalize_name(p["name"]): p for p in players if normalize_name(p["name"])}
    associations = {}
    candidates = []
    for img in soup.find_all("img"):
        raw = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or img.get("data-original")
        url = valid_image_url(raw, page_url)
        if not url:
            continue
        alt = (img.get("alt") or "").strip()
        title = (img.get("title") or "").strip()
        # Restrict association to explicit alt/title or the closest compact player card text.
        explicit = [alt, title]
        for label in explicit:
            key = normalize_name(label)
            if key in names:
                associations.setdefault(key, {"name": names[key]["name"], "role": names[key]["role"], "image": url, "association": "exact-alt-title", "source": "CREX", "source_url": page_url})
                break
        else:
            parent = img
            for _ in range(4):
                if not parent or not getattr(parent, "parent", None):
                    break
                parent = parent.parent
                # Match an exact text node/line inside the compact player card, not a substring.
                text_lines = [normalize_name(line) for line in parent.stripped_strings]
                keys = [line for line in text_lines if line in names]
                if len(keys) == 1:
                    key = keys[0]
                    associations.setdefault(key, {"name": names[key]["name"], "role": names[key]["role"], "image": url, "association": "exact-card-name", "source": "CREX", "source_url": page_url})
                    break
        candidates.append({"image": url, "alt": alt or None, "title": title or None})
    mapped = [associations[k] for k in names if k in associations]
    unmatched = [{"name": p["name"], "role": p["role"], "status": "unmatched"} for k,p in names.items() if k not in associations]
    return {
        "status": "ok" if not unmatched else ("partial" if mapped else "unavailable"),
        "source": "CREX",
        "source_url": page_url,
        "retrieved_at": utc_now(),
        "players": mapped,
        "unmatched_players": unmatched,
        "candidate_image_count": len(candidates),
        "reason": None if not unmatched else "No exact player-to-image association found for every player; unmatched players are listed for diagnostics."
    }

def fetch_crex_html(url):
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    return response.text

def extract_pitch(html, page_url):
    soup = BeautifulSoup(html or "", "html.parser")
    # Accept only text explicitly labelled as a pitch report/condition, not generic pitch words.
    for node in soup.find_all(string=re.compile(r"\b(pitch report|pitch condition|pitch update)\b", re.I)):
        parent = node.parent
        for _ in range(3):
            if parent is None:
                break
            text = re.sub(r"\s+", " ", parent.get_text(" ", strip=True)).strip()
            if 25 <= len(text) <= 700 and re.search(r"\b(pitch report|pitch condition|pitch update)\b", text, re.I):
                return {"status": "ok", "source": "CREX match page", "source_url": page_url, "retrieved_at": utc_now(), "report": text}
            parent = parent.parent
    return unavailable("CREX match page", "No explicitly labelled pitch report found in the fetched match page", source_url=page_url)

def geocode_venue(venue):
    if not venue:
        return None
    try:
        r = requests.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": venue, "count": 5, "language": "en", "format": "json"}, timeout=8)
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            # Stadium names can fail geocoding; try the city after the comma.
            city = venue.split(",")[-1].strip()
            if city and city.lower() != venue.lower():
                r = requests.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 5, "language": "en", "format": "json"}, timeout=8)
                r.raise_for_status()
                results = r.json().get("results") or []
        if not results:
            return None
        item = results[0]
        return {"latitude": item["latitude"], "longitude": item["longitude"], "name": item.get("name"), "timezone": item.get("timezone") or "auto"}
    except Exception:
        logger.exception("Venue geocoding failed")
        return None

def fetch_weather(venue, match_time=None):
    # Open-Meteo is tied to the match venue, never the user's device location.
    point = geocode_venue(venue)
    if not point:
        return unavailable("Open-Meteo", "Could not geocode the match venue; no weather returned", venue=venue)
    try:
        params = {
            "latitude": point["latitude"], "longitude": point["longitude"],
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
            "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code,wind_speed_10m",
            "forecast_days": 3, "timezone": point["timezone"]
        }
        r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=10)
        r.raise_for_status()
        payload = r.json()
        hourly = payload.get("hourly") or {}
        selected = None
        requested = str(match_time or "").strip()
        times = hourly.get("time") or []
        if requested and times:
            # Match supplied time by hour when parseable; never silently label current conditions as match-time weather.
            target = requested[:13].replace("T", "T")
            candidates = [(i,t) for i,t in enumerate(times) if t[:13] == target]
            if candidates:
                selected = {"time": times[candidates[0][0]], **{k: (v[candidates[0][0]] if candidates[0][0] < len(v) else None) for k,v in hourly.items() if k != "time"}}
        current = payload.get("current")
        if selected:
            conditions = {"match_time_forecast": selected, "current": current}
            timing = "match_time_forecast"
        elif current:
            conditions = {"current": current, "hourly_forecast_available": bool(times)}
            timing = "current_conditions; match time was not resolved to an hourly forecast"
        else:
            conditions = {"hourly": hourly}
            timing = "hourly_forecast"
        return {"status": "ok", "source": "Open-Meteo Forecast API", "source_url": r.url, "retrieved_at": utc_now(), "venue": venue, "coordinates": {"latitude": point["latitude"], "longitude": point["longitude"]}, "timezone": point["timezone"], "timing": timing, "data": conditions}
    except Exception as exc:
        logger.warning("Weather provider failed: %s", exc)
        return unavailable("Open-Meteo Forecast API", "Weather provider request failed; live score remains available", venue=venue, detail=str(exc))

def load_head_to_head(team1, team2):
    scope = os.environ.get("H2H_SCOPE", "all international formats").strip()
    path = os.environ.get("H2H_RECORDS_PATH", "data/historical_matches.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
        if not isinstance(records, list):
            raise ValueError("Historical records file must be a JSON array")
        a, b = normalize_name(team1), normalize_name(team2)
        selected = [m for m in records if normalize_name(m.get("team1")) in {a,b} and normalize_name(m.get("team2")) in {a,b} and normalize_name(m.get("team1")) != normalize_name(m.get("team2"))]
        selected = [m for m in selected if scope == "all formats" or scope == "all international formats" or normalize_name(m.get("format")) == normalize_name(scope)]
        if not selected:
            return unavailable("Configured historical records", "No historical records matched the declared scope; no head-to-head totals inferred", scope=scope, records_count=0, teams=[team1,team2])
        wins = {team1: 0, team2: 0}
        draws = no_results = ties = 0
        for match in selected:
            winner = normalize_name(match.get("winner"))
            if winner == a: wins[team1] += 1
            elif winner == b: wins[team2] += 1
            else:
                result = normalize_name(match.get("result"))
                if result in {"draw", "drawn"}: draws += 1
                elif result in {"no result", "abandoned", "washed out"}: no_results += 1
                elif result in {"tie", "tied"}: ties += 1
        return {"status": "ok", "source": "Configured historical records", "source_url": None, "retrieved_at": utc_now(), "scope": scope, "teams": [team1,team2], "records_count": len(selected), "wins": wins, "draws": draws, "ties": ties, "no_results": no_results, "note": "Counts calculated only from records in the configured dataset and declared scope."}
    except FileNotFoundError:
        return unavailable("Configured historical records", "Historical dataset is not installed. Add verified records to H2H_RECORDS_PATH; totals are not fabricated.", scope=scope, teams=[team1,team2])
    except Exception as exc:
        logger.warning("Head-to-head data failed: %s", exc)
        return unavailable("Configured historical records", "Historical records could not be read", scope=scope, detail=str(exc), teams=[team1,team2])

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
    url = (request.args.get("url") or "").strip()
    if not valid_crex_url(url):
        return jsonify({"success": False, "error": "Provide an HTTPS CREX match URL on crex.com"}), 400
    try:
        response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=False)
        if 300 <= response.status_code < 400:
            return jsonify({"success": False, "error": "CREX returned a redirect; redirect destination was not followed", "source_status": response.status_code}), 502
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower() and "<html" not in response.text[:1000].lower():
            return jsonify({"success": False, "error": "CREX response was not HTML", "content_type": content_type}), 502
        return jsonify({"success": True, "source": "CREX", "source_url": url, "source_status": response.status_code, "content_type": content_type, "html": response.text})
    except requests.RequestException as exc:
        logger.exception("CREX asset fetch failed")
        return jsonify({"success": False, "error": "Unable to fetch CREX page", "detail": str(exc), "source": "CREX"}), 502

@app.route("/api/data")
def api_data():
    """Return a partial-data envelope: core score failure is fatal; individual sections fail independently."""
    url = (request.args.get("url") or "").strip()
    if not valid_crex_url(url):
        return jsonify({"success": False, "error": "Provide an HTTPS CREX match URL on crex.com"}), 400
    retrieved_at = utc_now()
    try:
        live = scrape_crex_match(url)
    except Exception as exc:
        logger.exception("Live-score extraction failed")
        live = {"success": False, "error": str(exc)}
    if not live.get("success"):
        return jsonify({"success": False, "source": "CREX", "source_url": url, "retrieved_at": retrieved_at,
            "live_score": {"status": "error", "source": "CREX", "source_url": url, "retrieved_at": retrieved_at, "data": None, "error": live.get("error")},
            "lineups": unavailable("CREX", "Live page could not be parsed"),
            "portraits": unavailable("CREX", "Live page could not be parsed"),
            "venue": unavailable("CREX", "Live page could not be parsed"),
            "pitch": unavailable("CREX", "Live page could not be parsed"),
            "weather": unavailable("Open-Meteo", "Live page could not be parsed"),
            "head_to_head": unavailable("Configured historical records", "Live page could not be parsed"),
            "errors": [{"section": "live_score", "error": live.get("error", "Scrape failed")}]
        }), 502

    # All enrichment sections are isolated: one provider failure must not fail the main score.
    errors = []
    html = None
    try:
        html = fetch_crex_html(url)
    except Exception as exc:
        logger.warning("Enrichment HTML fetch failed: %s", exc)
        errors.append({"section": "portraits/pitch", "error": str(exc)})
    venue_name = live.get("venue") or None
    try:
        pitch = extract_pitch(html, url) if html else unavailable("CREX match page", "Source HTML unavailable", source_url=url)
    except Exception as exc:
        pitch = unavailable("CREX match page", "Pitch extraction failed", source_url=url, detail=str(exc))
        errors.append({"section": "pitch", "error": str(exc)})
    try:
        portraits = build_portrait_map(html, url, live) if html else unavailable("CREX", "Source HTML unavailable", players=[], unmatched_players=[{"name":p["name"],"role":p["role"],"status":"unmatched"} for p in player_names_from_score(live)])
    except Exception as exc:
        portraits = unavailable("CREX", "Portrait mapping failed", players=[], unmatched_players=[{"name":p["name"],"role":p["role"],"status":"unmatched"} for p in player_names_from_score(live)], detail=str(exc))
        errors.append({"section": "portraits", "error": str(exc)})
    try:
        weather = fetch_weather(venue_name, live.get("start_date") or live.get("start_time") or live.get("match_time"))
    except Exception as exc:
        weather = unavailable("Open-Meteo Forecast API", "Weather lookup failed; score unaffected", venue=venue_name, detail=str(exc))
        errors.append({"section": "weather", "error": str(exc)})
    try:
        team1 = (live.get("team1") or {}).get("full_name") or (live.get("team1") or {}).get("name") or "Team 1"
        team2 = (live.get("team2") or {}).get("full_name") or (live.get("team2") or {}).get("name") or "Team 2"
        h2h = load_head_to_head(team1, team2)
    except Exception as exc:
        h2h = unavailable("Configured historical records", "Head-to-head calculation failed", detail=str(exc))
        errors.append({"section": "head_to_head", "error": str(exc)})
    venue = {"status": "ok" if venue_name else "unavailable", "source": "CREX SportsEvent JSON-LD" if venue_name else None, "source_url": url, "retrieved_at": utc_now(), "name": venue_name}
    return jsonify({
        "success": True, "partial": bool(errors) or any(x.get("status") in {"partial","unavailable"} for x in (portraits,pitch,weather,h2h,venue)),
        "retrieved_at": retrieved_at,
        "match": {"source": "CREX", "source_url": url, "retrieved_at": retrieved_at, "title": live.get("match_title") or None, "series": live.get("series_name") or None, "teams": [live.get("team1"),live.get("team2")]},
        "live_score": {"status": "ok" if any(live.get(k) for k in ("team1","team2","batsman1","bowler")) else "partial", "source": "CREX", "source_url": url, "retrieved_at": retrieved_at, "data": live},
        "lineups": {"status": "unavailable", "source": "CREX", "source_url": url, "retrieved_at": utc_now(), "confirmed": False, "teams": [], "reason": "A confirmed full Playing XI is not inferred from active batters or yet-to-bat names."},
        "portraits": portraits,
        "venue": venue,
        "pitch": pitch,
        "weather": weather,
        "head_to_head": h2h,
        "errors": errors
    })

@app.route("/<path:path>")
def static_files(path):
    if os.path.isfile(path):
        return send_from_directory(".", path)
    return send_from_directory(".", "index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
