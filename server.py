from flask import Flask, request, jsonify, send_from_directory
import requests
from bs4 import BeautifulSoup
import re
import os

app = Flask(__name__, static_folder=".")

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,OPTIONS"
    return response

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Preet Sports API"})

@app.route("/", methods=["GET"])
@app.route("/mobile.html", methods=["GET"])
def index():
    if os.path.exists("mobile.html"):
        return send_from_directory(".", "mobile.html")
    return jsonify({"status": "ready"})

# Team Flag Fallback Dictionary for international/domestic cricket
TEAM_FLAGS = {
    "PAK": "https://cricketvectors.akamaized.net/teams/org/PAK.png",
    "SL": "https://cricketvectors.akamaized.net/teams/org/SL.png",
    "IND": "https://cricketvectors.akamaized.net/teams/org/IND.png",
    "AUS": "https://cricketvectors.akamaized.net/teams/org/AUS.png",
    "ENG": "https://cricketvectors.akamaized.net/teams/org/ENG.png",
    "NZ": "https://cricketvectors.akamaized.net/teams/org/NZ.png",
    "SA": "https://cricketvectors.akamaized.net/teams/org/SA.png",
    "BAN": "https://cricketvectors.akamaized.net/teams/org/BAN.png",
    "AFG": "https://cricketvectors.akamaized.net/teams/org/AFG.png",
    "WI": "https://cricketvectors.akamaized.net/teams/org/WI.png",
}

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
            return jsonify({"success": False, "error": f"CREX HTTP {res.status_code}"}), 502
        html = res.text
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    soup = BeautifulSoup(html, "html.parser")
    raw_text = soup.get_text()

    # 1. Match Title & Teams
    title_el = soup.select_one(".sub-title, .match-info-title, h1")
    match_title = title_el.get_text(strip=True) if title_el else "PAK vs SL Live"
    
    t1_name = "PAK"
    t2_name = "SL"
    teams_match = re.search(r"([A-Za-z]+)\s+vs\s+([A-Za-z]+)", match_title, re.IGNORECASE)
    if teams_match:
        t1_name = teams_match.group(1).upper()
        t2_name = teams_match.group(2).upper()

    # Team Flags / Crests
    t1_logo = TEAM_FLAGS.get(t1_name, f"https://cricketvectors.akamaized.net/teams/org/{t1_name}.png")
    t2_logo = TEAM_FLAGS.get(t2_name, f"https://cricketvectors.akamaized.net/teams/org/{t2_name}.png")

    # 2. Extract Scores and Overs cleanly
    t1_score, t1_overs = "—", "—"
    t2_score, t2_overs = "—", "—"

    # Regex search for pattern like "94-2 18.0" or "325-8 50.0"
    score_matches = re.findall(r"(\b\d{1,3}-\d{1,2}\b|\b\d{2,3}\/\d{1,2}\b)\s*(\d{1,2}\.\d{1})?", raw_text)
    if len(score_matches) >= 1:
        t1_score = score_matches[0][0]
        if score_matches[0][1]:
            t1_overs = score_matches[0][1]
    if len(score_matches) >= 2:
        t2_score = score_matches[1][0]
        if score_matches[1][1]:
            t2_overs = score_matches[1][1]

    # Explicit overs search if not captured
    if t1_overs == "—":
        ov_match = re.search(r"(\d{1,2}\.\d{1})\s*(?:OV|overs)", raw_text, re.IGNORECASE)
        if ov_match:
            t1_overs = ov_match.group(1)

    # 3. Center Live Action Text
    result_box = soup.select_one(".team-result .result-box") or soup.select_one(".team-result") or soup.select_one(".font2")
    live_action = " ".join(result_box.stripped_strings) if result_box else ""
    if not live_action:
        # Fallback to checking active over / match status
        act_match = re.search(r"\b(Over|Wicket|Four|Six|Ball in air|Review|No ball|Wide)\b", raw_text, re.IGNORECASE)
        live_action = act_match.group(0).upper() if act_match else "OVER"

    # 4. CRR, RRR & Equation
    crr = "—"
    rrr = "—"
    crr_match = re.search(r"CRR\s*:\s*([\d\.]+)", raw_text, re.IGNORECASE)
    rrr_match = re.search(r"RRR\s*:\s*([\d\.]+)", raw_text, re.IGNORECASE)
    if crr_match:
        crr = crr_match.group(1)
    if rrr_match:
        rrr = rrr_match.group(1)

    eq_match = re.search(r"([A-Z]{2,4}\s+need\s+\d+\s+runs\s+in\s+\d+\s+balls)", raw_text, re.IGNORECASE)
    equation = eq_match.group(1).upper() if eq_match else "MATCH IN PROGRESS"

    # Partnership & Last Wicket
    partnership = "—"
    last_wicket = "—"
    pship_match = re.search(r"P'?ship\s*:\s*([\d\(\)\s]+)", raw_text, re.IGNORECASE)
    if pship_match:
        partnership = pship_match.group(1).strip()

    lw_match = re.search(r"Last\s*Wkt\s*:\s*([A-Za-z\s]+[\d\(\)]+)", raw_text, re.IGNORECASE)
    if lw_match:
        last_wicket = lw_match.group(1).strip()

    # 5. Active Batsmen & Bowler (2-Layer Avatar & Stats)
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
            return {"name": name, "figures": figures, "overs": overs, "econ": econ, "face": face, "jersey": jersey}
        else:
            score_p = card.select(".batsmen-score p")
            runs = score_p[0].get_text(strip=True) if len(score_p) > 0 else "0"
            balls = score_p[1].get_text(strip=True).replace("(", "").replace(")", "") if len(score_p) > 1 else "0"

            fours, sixes, sr = "0", "0", "0.00"
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
                "name": name, "runs": runs, "balls": balls,
                "fours": fours, "sixes": sixes, "sr": sr,
                "on_strike": on_strike, "face": face, "jersey": jersey
            }

    cards = soup.select(".playing-batsmen-wrapper .batsmen-partnership")
    batsman1 = parse_card(cards[0], False) if len(cards) > 0 else {}
    batsman2 = parse_card(cards[1], False) if len(cards) > 1 else {}
    bowler = parse_card(cards[2], True) if len(cards) > 2 else {}

    # 6. Current Over Balls
    balls = []
    # Scrape numbers inside recent over circles (e.g. 4 0 1 2 0 0)
    for b_el in soup.select("div[class*='over'] span, .circle-ball, div[class*='ball']"):
        txt = b_el.get_text(strip=True)
        if re.match(r"^([0-6]|W|WD|NB|B|LB)$", txt, re.IGNORECASE):
            balls.append(txt)

    # Keep only the last 6 balls
    current_balls = balls[-6:] if len(balls) >= 6 else (balls if balls else ["0","0","4","1","4","0"])

    return jsonify({
        "success": True,
        "live_action": live_action,
        "equation": equation,
        "match_title": match_title,
        "crr": crr,
        "rrr": rrr,
        "partnership": partnership,
        "last_wicket": last_wicket,
        "team1": {"name": t1_name, "score": t1_score, "overs": t1_overs, "logo": t1_logo},
        "team2": {"name": t2_name, "score": t2_score, "overs": t2_overs, "logo": t2_logo},
        "batsman1": batsman1,
        "batsman2": batsman2,
        "bowler": bowler,
        "current_over": {"balls": current_balls, "total": 0}
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
