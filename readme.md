# Weather-Aware Truck Routing

A React + Django app that helps a truck driver pick the safest route based on
weather, load weight and travel time. Built for the Spotter AI Full Stack
Developer assessment.

- **Hosted app:** https://spotter-weather-routing-one.vercel.app
- **Walkthrough video (Loom):** LOOM_LINK_HERE
- **Code:** this repository

> The backend runs on a free hosting plan and the plan has to be renewed
> about every month. If the hosted app shows a network error, the backend is
> probably asleep or expired, so please let me know and I will bring it back.

## What it does

You enter an origin, a destination, a departure time and a load weight. The
app then:

1. Gets up to 3 route options from a routing API.
2. Samples each route at checkpoints (every 10, 25 or 50 miles, depending on
   trip length).
3. Works out the truck's estimated arrival time at each checkpoint and uses the
   hourly forecast for that exact hour.
4. Classifies each checkpoint as Low, Moderate, High, Severe or No Travel from
   wind, rain and snow, with the load-weight rules applied on top.
5. Ranks the routes and recommends one, with a plain-language explanation.
6. Shows all routes, checkpoints, ETAs and risk levels on a map, plus a forecast
   heatmap with a 0 to 48 hour slider.

## Risk rules

| Level | Wind (mph) | Rain (in/hr) | Snow (in/hr) |
|---|---|---|---|
| Low | < 25 | < 0.10 | < 0.5 |
| Moderate | 25 to 34 | 0.10 to 0.25 | 0.5 to 1.0 |
| High | 35 to 44 | 0.25 to 0.50 | 1.0 to 2.0 |
| Severe | 45 to 54 | 0.50 to 1.00 | 2.0 to 3.0 |
| No Travel | 55 or more | > 1.00 | > 3.0 |

Load rules: 55 mph or more is No Travel for any load. 45 to 54 mph with a load
over 30,000 lb is No Travel. 35 to 44 mph with a load over 40,000 lb is Severe.

## Tech stack (all free, no credit card)

| Purpose | Choice |
|---|---|
| Backend | Django 6.1 + Django REST Framework, Python 3.13 |
| Frontend | React 19 + Vite, Leaflet (react-leaflet) |
| Routing | OSRM public server (car profile) |
| Weather and time zone | Open-Meteo |
| Geocoding | Nominatim (OpenStreetMap) |
| Hosting | Vercel (frontend), PythonAnywhere free plan (backend) |

## Design decisions and assumptions

These are the places where the brief was ambiguous or the free APIs have
limits. Each one is a deliberate choice.

- **Recommendation order.** Routes are ranked by: any No Travel segment, No
  Travel miles, Severe miles, High miles, average risk, then travel time. The
  brief lists "fewest Severe miles" first. I put No Travel above it on purpose,
  because a route with a segment you must not drive should not win just because
  it has fewer Severe miles. A test covers this.
- **Band boundaries.** Each band includes its lower bound and excludes its upper
  bound, so wind of 35.0 mph is High and 34.9 is Moderate. Rain above 1.00 and
  snow above 3.0 are No Travel, so exactly 1.00 and 3.0 are Severe.
- **Load rules** use strict "greater than" and never lower a risk level that is
  already higher.
- **Checkpoint risk** is the worst of wind, rain and snow at that point. Rain
  includes showers.
- **Miles per risk level.** Each checkpoint covers half the distance to its
  neighbours, so the segment lengths add up to the exact route distance.
- **Average risk** is weighted by distance.
- **Truck speed.** OSRM uses car speeds, so durations are divided by 0.9.
- **Third route.** OSRM often returns only 2 alternatives. When that happens a
  third route is generated through a via-point and accepted only if it is
  different enough and not much longer. If a trip has a single road (for
  example Cheyenne to Salt Lake City) the app honestly shows one route.
- **Departure time is local time at the origin.** The frontend sends the wall
  time and the backend reads it in the origin's IANA time zone, so daylight
  saving is handled. Times on the wire are UTC.
- **No-route handling.** The public OSRM server snaps far-away points to the
  nearest road, so it rarely says "no route". The backend checks the snap
  distance and returns a clear 400 when a point is more than 5 km from a road.
- **Heatmap.** The backend returns all 48 hours at once. The slider changes one
  number in the browser and redraws, so there are no network requests while
  scrubbing.
- **Risk is never color only.** Every level has a text label, and map markers
  grow with severity.
- **No accounts and no database.** It is a stateless tool. Rate limiting
  protects the free APIs, and caching uses Django's in-memory cache, so it
  resets on restart.
- **Worldwide geocoding** by default (a setting can restrict it by country).

## Demo mode (development only)

Real weather is often calm, which makes every checkpoint Low. For the walkthrough
there is a `DEMO_MODE` setting that overlays a deterministic wind, rain and snow
pattern. It works only when `DEBUG=True`, it is off in production, responses are
flagged with `demo_mode`, and the UI shows a "Demo weather, not real data"
banner. Heatmap cells and checkpoints can show slightly different demo colors
because they sample at different points.

## Known limitations

- Free services have no uptime guarantee and can be slow or rate limited.
- The hosted backend is on a free plan that expires if it is not renewed.
- OSRM uses a car profile, not a true truck profile (no height or weight limits).
- Open-Meteo's free tier is for non-commercial use.
- The cache is per process, so a restart clears it.
- There are no frontend tests yet. The backend has 145 tests.

## Run locally

### Backend (Windows PowerShell)

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`: set `SECRET_KEY`, and set `DEBUG=True` for local development
(production settings force HTTPS). Then:

```powershell
python manage.py test
python manage.py runserver
```

Generate a secret key with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

The "unapplied migrations" message is harmless, because the app has no database
models.

### Frontend

```powershell
cd frontend
npm install
copy .env.example .env
npm run dev
```

The frontend runs at http://localhost:5173 and expects the backend at
http://127.0.0.1:8000. `VITE_API_BASE_URL` must be set for production builds.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health/` | Health check |
| `GET /api/geocode/?q=` | Place search |
| `GET /api/timezone/?lat=&lon=` | Time zone for a point |
| `POST /api/analyze/` | Routes, checkpoints, risk and recommendation |
| `POST /api/heatmap/` | 48 hour corridor forecast grid |

## Deployment

- **Backend:** PythonAnywhere free plan, Python 3.13 virtualenv, WSGI app,
  configuration in an untracked `.env` file. `DEBUG` and `DEMO_MODE` are off.
- **Frontend:** Vercel, project root `frontend`, with `VITE_API_BASE_URL` set to
  the backend URL at build time. `CORS_ALLOWED_ORIGINS` on the backend lists the
  frontend origin.
- Missing required settings (`SECRET_KEY`, `CORS_ALLOWED_ORIGINS`,
  `VITE_API_BASE_URL`) fail loudly instead of falling back to unsafe defaults.