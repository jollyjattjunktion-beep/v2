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

FLAG_MAP = {
    "PAK": "https://flagcdn.com/w160/pk.png",
    "SL": "https://flagcdn.com/w160/lk.png",
    "IND": "https://flagcdn.com/w160/in.png",
    "AUS": "https://flagcdn.com/w160/au.png",
    "ENG": "https://flagcdn.com/w160/gb-eng.png",
    "NZ": "https://flagcdn.com/w160/nz.png",
    "SA": "https://flagcdn.com/w160/za.png",
    "BAN": "https://flagcdn.com/w160/bd.png",
    "AFG": "https://flagcdn.com/w160/af.png",
    "WI": "https://flagcdn.com/w160/jm.png",
    "ZIM": "https://flagcdn.com/w160/zw.png",
    "IRE": "https://flagcdn.com/w160/ie.png",
    "NED": "https://flagcdn.com/w160/nl.png",
    "SCO": "https://flagcdn.com/w160/gb-sct.png"
}

@app.route("/api/scrape", methods=["GET"])
def scrape_match():
    url = request.args.get("url")
    if not url:
        return jsonify({"success": False, "error": "Missing match URL"}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://crex.com/"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return jsonify({"success": False, "error": f"CREX HTTP {res.status_code}"}), 502
        html = res.text
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    soup = BeautifulSoup(html, "html.parser")
    raw_text = soup.get_text()

    # 1. Teams & Flags
    title_el = soup.select_one(".sub-title, .match-info-title, h1")
    match_title = title_el.get_text(strip=True) if title_el else "PAK vs SL Live"
    
    t1_name = "PAK"
    t2_name = "SL"
    teams_match = re.search(r"([A-Za-z]+)\s+vs\s+([A-Za-z]+)", match_title, re.IGNORECASE)
    if teams_match:
        t1_name = teams_match.group(1).upper()
        t2_name = teams_match.group(2).upper()

    t1_logo = FLAG_MAP.get(t1_name, f"https://flagcdn.com/w160/{t1_name[:2].lower()}.png")
    t2_logo = FLAG_MAP.get(t2_name, f"https://flagcdn.com/w160/{t2_name[:2].lower()}.png")

    # 1. Match the exact target over (e.g., "Over 27 4 0 4 1 W = 9")
    if target_over:
        m = re.search(rf"Over\s+{target_over}[:\s]+([^=]+?)(?:=\s*(\d+)|\s+Over|$)", timeline_text, re.IGNORECASE)
        if m:
            raw_b = re.findall(r"\b([0-6]|W|WD|NB|B|LB)\b", m.group(1), re.IGNORECASE)
            current_balls = [b.upper() for b in raw_b if b.upper() != "OVER"]
            if m.group(2):
                try:
                    over_total = int(m.group(2).strip())
                except:
                    pass

    # 2. Fallback to the latest over in the clean timeline
    if not current_balls:
        over_chunks = re.findall(r"Over\s+\d+[:\s]+([^=]+?)(?:=\s*(\d+)|\s+Over|$)", timeline_text, re.IGNORECASE)
        if over_chunks:
            last_balls_str, total_str = over_chunks[-1]
            raw_b = re.findall(r"\b([0-6]|W|WD|NB|B|LB)\b", last_balls_str, re.IGNORECASE)
            current_balls = [b.upper() for b in raw_b if b.upper() != "OVER"]
            if total_str:
                try:
                    over_total = int(total_str.strip())
                except:
                    pass
    # 3. Center Live Action Text
    result_box = soup.select_one(".team-result .result-box") or soup.select_one(".team-result") or soup.select_one(".font2")
    live_action = " ".join(result_box.stripped_strings) if result_box else ""
    if not live_action:
        act_match = re.search(r"\b(Over|Wicket|Four|Six|Ball in air|Review|No ball|Wide)\b", raw_text, re.IGNORECASE)
        live_action = act_match.group(0).upper() if act_match else "OVER"

    # 4. Telemetry (CRR, RRR, Partnership, Target)
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

    partnership = "—"
    last_wicket = "—"
    pship_match = re.search(r"P'?ship\s*:\s*([\d\(\)\s]+)", raw_text, re.IGNORECASE)
    if pship_match:
        partnership = pship_match.group(1).strip()

    lw_match = re.search(r"Last\s*Wkt\s*:\s*([A-Za-z\s]+[\d\(\)]+)", raw_text, re.IGNORECASE)
    if lw_match:
        last_wicket = lw_match.group(1).strip()

    # 5. Batsmen & Bowler: Fixed Stats Regex
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
            econ_m = re.search(r"([\d\.]+)", econ_el.get_text()) if econ_el else None
            econ = econ_m.group(1) if econ_m else "0.00"
            return {"name": name, "figures": figures, "overs": overs, "econ": econ, "face": face, "jersey": jersey}
        else:
            score_p = card.select(".batsmen-score p")
            runs = score_p[0].get_text(strip=True) if len(score_p) > 0 else "0"
            balls = score_p[1].get_text(strip=True).replace("(", "").replace(")", "") if len(score_p) > 1 else "0"

            fours = "0"
            sixes = "0"
            sr = "0.00"
            for sr_el in card.select(".player-strike-wrapper .strike-rate"):
                t = sr_el.get_text()
                # Targets only numbers appearing after the label
                m4 = re.search(r"4s\D*(\d+)", t, re.IGNORECASE)
                m6 = re.search(r"6s\D*(\d+)", t, re.IGNORECASE)
                msr = re.search(r"SR\D*([\d\.]+)", t, re.IGNORECASE)
                if m4:
                    fours = m4.group(1)
                if m6:
                    sixes = m6.group(1)
                if msr:
                    sr = msr.group(1)

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

   # 6. ACCURATE LIVE OVER BALLS (Scrapes only the active over strip)
    current_balls = []
    over_total = 0

    # Cut off text before Commentary or Probability so old overs are ignored
    timeline_text = raw_text
    for stop_word in ["Probability", "Slow-over rate", "Commentary", "Who will win?", "Match Info"]:
        if stop_word in timeline_text:
            timeline_text = timeline_text.split(stop_word)[0]

    # Calculate active over number (e.g., 26.5 -> 27, 27.0 -> 27)
    target_over = None
    try:
        ov_f = float(t1_overs)
        target_over = (int(ov_f) + 1) if (ov_f % 1 > 0) else int(ov_f)
    except:
        pass
        
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
        "current_over": {"balls": current_balls, "total": over_total}
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
