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
