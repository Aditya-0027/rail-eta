# RailETA Dynamic — Indian Railways ETA Prototype

A full-stack prototype with a working Flask + SQLite backend and a responsive frontend.

## Features
- Train search by train number/name
- Live-style train dashboard
- Station-wise schedule + predicted ETA
- Delay, speed, platform and status
- Dynamic ETA calculation from current delay, section speed, congestion and historical section time
- Simulated live movement endpoint
- Delay event feed
- REST APIs for apps, displays and control-room dashboards
- SQLite database seeded with sample Indian Railways coaching trains

## Run
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

## API
- GET /api/trains
- GET /api/trains/<train_no>
- GET /api/trains/<train_no>/stations
- GET /api/trains/<train_no>/events
- POST /api/trains/<train_no>/simulate
- GET /api/health

The included data is simulated/demo data; connect an authorized live railway feed to replace the simulator.


## Public deployment
Upload this folder to GitHub, then create a Render Web Service from the repository.
Build: `pip install -r requirements.txt`
Start: `gunicorn app:app`
The service will provide a public HTTPS URL.

This prototype uses SQLite and simulated train data. For persistent production data, migrate to PostgreSQL and connect an authorized live railway feed.
