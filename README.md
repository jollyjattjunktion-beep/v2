# Preet Sports V2

Separate V2 deployment of the Preet Sports CREX live scoreboard. This project references the original `jollyjattjunktion-beep/preet-sports` implementation while keeping V2 independent.

## Render setup

- **Runtime:** Python 3
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn server:app --bind 0.0.0.0:$PORT`
- **Health check path:** `/api/health`
- **Root directory:** leave blank

After deployment, open the service URL. The scoreboard uses the same-origin API in V2; it does not call the old Render service.

## API

- `GET /api/health` — service health
- `GET /api/scrape?url=https://crex.com/...` — backwards-compatible live score response
- `GET /api/crex-assets?url=https://crex.com/...` — fetches the source HTML for the browser's CREX image/player parser
- `GET /api/data?url=https://crex.com/...` — structured response separating live score, lineups, portraits, venue, pitch, weather and head-to-head with status/source metadata

## Data integrity

V2 does not invent a Playing XI, pitch report, weather report, or head-to-head numbers. Sections not reliably available from the current CREX scraper are marked `unavailable`. A live batter/bowler list or “yet to bat” list is not treated as a confirmed full lineup.

## Notes

The CREX source may change its markup or restrict automated requests. If so, the API reports the failure rather than fabricating data. Use only source data and imagery you are authorized to access and display.


## Enrichment and data provenance (V2)

`GET /api/data?url=https://crex.com/...` keeps the live-score scrape as the core result and enriches sections independently. A failure in weather, portraits, pitch or historical records does not turn a successful live-score response into an HTTP error. Check each section's `status`, `source`, `source_url` where available, and `retrieved_at`; inspect the top-level `errors` array for section-specific failures.

- **Player portraits:** The backend normalizes player names and accepts only exact-name matches from image alt/title or compact nearby card text. Relative image URLs are resolved against the CREX page URL. Placeholder assets and non-approved hosts are rejected. `portraits.unmatched_players` lists players without a safe exact association; `candidate_image_count` helps diagnose page markup changes. No fuzzy name guesses are used.
- **Venue:** Uses venue information extracted from CREX SportsEvent JSON-LD and includes source URL and retrieval timestamp.
- **Pitch:** Looks for an explicitly labelled pitch report/condition/update in the CREX match page. It returns unavailable when no such text is present instead of treating generic pitch mentions as a report.
- **Weather:** Uses Open-Meteo geocoding and forecast APIs, tied to the match venue coordinates, not the user's location. A match-time hourly forecast is selected only if a usable match timestamp is supplied and matches an hourly forecast; otherwise the response labels the result as current conditions/forecast context and does not claim it is match-time weather. Provider errors are isolated from live score.
- **Head-to-head:** Computed only from a verified historical records JSON array configured with `H2H_RECORDS_PATH` (default `data/historical_matches.json`). Each record should contain `team1`, `team2`, `format`, and either `winner` or `result` (result values include `draw`, `tie`, `no result`, or `abandoned`). Set `H2H_SCOPE` to a declared format such as `ODI`, `Test`, `T20I`, or `all international formats`. The default scope is `all international formats` and is returned explicitly. Draws, ties and no-results are counted separately. If the dataset is absent or has no matching records, the section is marked unavailable; totals are never invented.

**Important limits:** This deployment does not include a historical results dataset, so head-to-head remains unavailable until you provide verified records. CREX HTML may not include a labelled pitch report or explicit image-to-player associations. Venue geocoding may resolve to the city rather than the exact stadium; the returned coordinates/source should be checked before relying on weather. The CREX scraper currently may not provide a match start timestamp, so weather will not be represented as a match-time forecast unless that timestamp is available.
