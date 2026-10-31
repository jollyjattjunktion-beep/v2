from flask import Flask, request, jsonify, send_from_directory
import requests
from bs4 import BeautifulSoup
import re
import os

app = Flask(__name__, static_folder=".")

# Native CORS: Allows your frontend to fetch data without needing flask-cors
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,OPTIONS"
    return response

# Existing Health Check
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Preet Sports API"})

# Serve mobile.html scoreboard directly from the root if present
@app.route("/", methods=["GET"])
@app.route("/mobile.html", methods=["GET"])
def index():
    if os.path.exists("mobile.html"):
        return send_from_directory(".", "mobile.html")
    return jsonify({"status": "ready", "hint": "Send GET to /api/scrape?url=<CREX_URL>"})

# The /api/scrape Endpoint
@app.route("/api/scrape", methods=["GET"])
def scrape_match():
    url = request.args.get("url")
    if not url:
        return jsonify({"success": False, "error": "Missing match url query parameter"}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://crex.com/"
    }

    try:
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code != 200:
            return jsonify({"success": False, "error": f"CREX responded with HTTP {res.status_code}"}), 502
        html = res.text
    except Exception as e:
        return jsonify({"success": False, "error": f"Connection failed: {str(e)}"}), 500

    soup = BeautifulSoup(html, "html.parser")

    # 1. Center Action Box (Over, Wicket, Ball in Air)
    result_box = soup.select_one(".team-result .result-box") or soup.select_one(".team-result")
    live_action = " ".join(result_box.stripped_strings) if result_box else "OVER"

    # 2. Match Equation / Title
    equation_el = soup.select_one(".equation, .match-status, .banner-text")
    equation = equation_el.get_text(strip=True) if equation_el else "LIVE MATCH"
    title_el = soup.select_one(".sub-title, .match-info-title, h1")
    match_title = title_el.get_text(strip=True) if title_el else "LIVE MATCH CENTRE"

    # 3. Active Batsmen & Bowler (2-Layer Face + Jersey Parser)
    def parse_card(card, is_bowler=False):
        if not card:
            return {}
        name_el = card.select_one(".batsmen-name p, .p-name")
        name = name_el.get_text(strip=True) if name_el else "WAITING..."

        head_el = card.select_one("app-player-profile-img img:not(.mr-top)")
        jersey_el = card.select_one("app-player-profile-img img.mr-top")
        face = head_el.get("src") if head_el else ""
        jersey = jersey_el.get("src") if jersey_el else ""

        if is_bowler:
            score_p = card.select(".batsmen-score p")
            figures = score_p[0].get_text(strip=True) if len(score_p) > 0 else "0-0"
            overs = score_p[1].get_text(strip=True).replace("(", "").replace(")", "") if len(score_p) > 1 else "0.0"
            econ_el = card.select_one(".player-strike-wrapper .strike-rate")
            econ = re.sub(r"[^0-9.]", "", econ_el.get_text()) if econ_el else "0.00"
            return {
                "name": name,
                "figures": figures,
                "overs": overs,
                "econ": econ,
                "face": face,
                "jersey": jersey
            }
        else:
            score_p = card.select(".batsmen-score p")
            runs = score_p[0].get_text(strip=True) if len(score_p) > 0 else "0"
            balls = score_p[1].get_text(strip=True).replace("(", "").replace(")", "") if len(score_p) > 1 else "0"

            fours = "0"
            sixes = "0"
            sr = "0.00"
            for sr_el in card.select(".player-strike-wrapper .strike-rate"):
                t = sr_el.get_text()
                if "4s" in t:
                    fours = re.sub(r"[^0-9]", "", t)
                elif "6s" in t:
                    sixes = re.sub(r"[^0-9]", "", t)
                elif "SR" in t:
                    sr = re.sub(r"[^0-9.]", "", t)

            on_strike = bool(card.select_one(".circle-strike-icon"))
            return {
                "name": name,
                "runs": runs,
                "balls": balls,
                "fours": fours,
                "sixes": sixes,
                "sr": sr,
                "on_strike": on_strike,
                "face": face,
                "jersey": jersey
            }

    cards = soup.select(".playing-batsmen-wrapper .batsmen-partnership")
    batsman1 = parse_card(cards[0], False) if len(cards) > 0 else {}
    batsman2 = parse_card(cards[1], False) if len(cards) > 1 else {}
    bowler = parse_card(cards[2], True) if len(cards) > 2 else {}

    # 4. Over Balls (Recent Overs)
    balls = []
    ball_spans = soup.select(".recent-overs span, .over-balls span, .circle-ball")
    for b in ball_spans[-6:]:
        val = b.get_text(strip=True)
        if val:
            balls.append(val)

    # 5. Team Scores
    score_blocks = soup.select(".team-score, .team-runs")
    s1 = score_blocks[0].get_text(strip=True) if len(score_blocks) > 0 else "—"
    s2 = score_blocks[1].get_text(strip=True) if len(score_blocks) > 1 else "—"

    return jsonify({
        "success": True,
        "live_action": live_action,
        "equation": equation,
        "match_title": match_title,
        "team1": {"name": "TEAM 1", "score": s1, "overs": ""},
        "team2": {"name": "TEAM 2", "score": s2, "overs": ""},
        "batsman1": batsman1,
        "batsman2": batsman2,
        "bowler": bowler,
        "current_over": {"balls": balls, "total": 0}
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
