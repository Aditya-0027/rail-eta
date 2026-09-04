from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import os, random, sqlite3, threading, math
from datetime import datetime, timedelta

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    import joblib
except ImportError:  # pragma: no cover
    joblib = None

app = Flask(__name__)
CORS(app)
DB = "rail_eta.db"

RAILRADAR_BASE = "https://api.railradar.in/v1"
RAILRADAR_API_KEY = os.getenv("RAILRADAR_API_KEY", "").strip()
DEFAULT_LIVE_NUMBERS = "12919,12952,12002,12259,12301,12424,12431,12622,12627,12910,12951,12432,12433,12434,12453,12454,12302,12313,12314,12309,12310,12903,12904,12905,12906,12907,12908,12909,12911,12912,12925,12926,12927,12928,12931,12932,12933,12934,12935,12936,12937,12938,12939,12940,12941,12942,12943,12944,12945,12946,12001,12003,12004,12005,12006,12007,12008,12009,12010,12011,12012,12013,12014,12015,12016,12017,12018,12023,12024,12029,12030,12031,12032,12033,12034,12039,12040,12045,12046,12127,12128,12129,12130,12131,12132,12133,12134,12269,12270,12271,12272,12273,12274,12281,12282,12283,12284,12285,12286,12621"
LIVE_NUMBERS = [x.strip() for x in os.getenv("LIVE_TRAIN_NUMBERS", DEFAULT_LIVE_NUMBERS).split(",") if x.strip()]
LIVE_CACHE_SECONDS = int(os.getenv("LIVE_CACHE_SECONDS", "300"))  # 5 min cache; 100 trains can consume a large API quota quickly
_live_cache = {}
# Previous live snapshots used to derive speed when RailRadar does not supply speedKmh.
_speed_history = {}
_live_lock = threading.Lock()
_weather_cache = {}
_weather_lock = threading.Lock()
WEATHER_CACHE_SECONDS = int(os.getenv("WEATHER_CACHE_SECONDS", "900"))  # 15 min
WEATHER_BASE = "https://api.open-meteo.com/v1/forecast"
MODEL_PATH = os.getenv("ETA_MODEL_PATH", "model/eta_delay_model.joblib")
ETA_MODEL = None
ETA_MODEL_FEATURES = []
if joblib and os.path.exists(MODEL_PATH):
    try:
        bundle = joblib.load(MODEL_PATH)
        ETA_MODEL = bundle.get("model") if isinstance(bundle, dict) else bundle
        ETA_MODEL_FEATURES = bundle.get("features", []) if isinstance(bundle, dict) else []
    except Exception:
        ETA_MODEL = None

SEED_TRAINS = [
    ("12951","Mumbai Rajdhani","Mumbai Central","New Delhi","Rajdhani Express","WR",8),
    ("12952","Mumbai Rajdhani","New Delhi","Mumbai Central","Rajdhani Express","NR",8),
    ("12424","Dibrugarh Rajdhani","New Delhi","Dibrugarh","Rajdhani Express","NFR",10),
    ("12953","August Kranti Rajdhani","Mumbai Central","Hazrat Nizamuddin","Rajdhani Express","WR",7),
    ("12431","Trivandrum Rajdhani","New Delhi","Thiruvananthapuram","Rajdhani Express","NR",10),
    ("12910","Garib Rath","Hazrat Nizamuddin","Bandra Terminus","Garib Rath","WR",7),
    ("12301","Howrah Rajdhani","Howrah","New Delhi","Rajdhani Express","ER",9),
    ("12259","Sealdah Duronto","Sealdah","Bikaner","Duronto Express","ER",8),
    ("12627","Karnataka Express","KSR Bengaluru","New Delhi","Superfast","SWR",10),
    ("12622","Tamil Nadu Express","New Delhi","Chennai Central","Superfast","NR",10),
]


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS trains(
      train_no TEXT PRIMARY KEY, name TEXT, origin TEXT, destination TEXT,
      category TEXT, zone TEXT, delay INTEGER DEFAULT 0, speed REAL DEFAULT 90,
      status TEXT DEFAULT 'RUNNING', current_station TEXT, next_station TEXT,
      platform TEXT, lat REAL, lon REAL, updated TEXT
    );
    CREATE TABLE IF NOT EXISTS stations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, train_no TEXT, seq INTEGER,
      station TEXT, scheduled TEXT, distance REAL, halt INTEGER DEFAULT 2,
      FOREIGN KEY(train_no) REFERENCES trains(train_no)
    );
    CREATE TABLE IF NOT EXISTS events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, train_no TEXT, event_type TEXT,
      impact INTEGER, message TEXT, created TEXT
    );
    """)
    count = c.execute("SELECT COUNT(*) FROM trains").fetchone()[0]
    if count == 0:
        now = datetime.now()
        for i, t in enumerate(SEED_TRAINS):
            no,name,origin,dest,cat,zone,n=t
            delay=[0,4,8,15,22,3,11,6,0,17][i]
            speed=[98,91,76,0,64,72,88,81,102,69][i]
            status="AT STATION" if speed==0 else ("DELAYED" if delay>=10 else "RUNNING")
            lat=19.07 + i*1.2
            lon=72.87 + i*0.8
            stations = [origin,"Surat","Vadodara","Ratlam","Kota","Sawai Madhopur","Agra Cantt",dest]
            if n>8: stations.insert(2,"Ahmedabad")
            if n>9: stations.insert(4,"Jhansi")
            stations=stations[:n]
            c.execute("INSERT INTO trains VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (no,name,origin,dest,cat,zone,delay,speed,status,stations[min(2,len(stations)-1)],
                 stations[min(3,len(stations)-1)],str((i%5)+1),lat,lon,now.isoformat(timespec="seconds")))
            base=datetime(2026,9,4,8,0)+timedelta(minutes=i*7)
            for s,st in enumerate(stations):
                tm=(base+timedelta(minutes=s*92)).strftime("%H:%M")
                c.execute("INSERT INTO stations(train_no,seq,station,scheduled,distance,halt) VALUES(?,?,?,?,?,?)",
                          (no,s,st,tm,s*145,2 if s not in (0,len(stations)-1) else 0))
    c.commit(); c.close()


def eta_from_schedule(scheduled, delay=0):
    if not scheduled:
        return None
    try:
        h, m = map(int, scheduled[:5].split(":"))
        mins = (h * 60 + m + int(delay or 0)) % 1440
        return f"{mins//60:02d}:{mins%60:02d}"
    except Exception:
        return None


def demo_train_dict(r):
    d = dict(r)
    c=conn()
    sr=c.execute("SELECT scheduled FROM stations WHERE train_no=? AND station=? ORDER BY seq LIMIT 1",
                 (d["train_no"], d["next_station"])).fetchone()
    c.close()
    d["next_eta"] = eta_from_schedule(sr["scheduled"], d.get("delay")) if sr else None
    d["confidence"] = max(61,min(97,round(95-(d.get("delay") or 0)*0.8)))
    d["data_source"] = "demo"
    d["is_live"] = False
    return d


def live_enabled():
    return bool(RAILRADAR_API_KEY and requests and LIVE_NUMBERS)


def fetch_live(train_no, force=False):
    now = datetime.now()
    with _live_lock:
        cached = _live_cache.get(train_no)
        if cached and not force and (now - cached["fetched"]).total_seconds() < LIVE_CACHE_SECONDS:
            return cached["data"], None
    try:
        r = requests.get(
            f"{RAILRADAR_BASE}/trains/{train_no}/live",
            headers={"Authorization": f"Bearer {RAILRADAR_API_KEY}"},
            params={"authoritative":"true" if force else "false"}, timeout=12
        )
        if r.status_code != 200:
            return None, f"RailRadar HTTP {r.status_code}"
        payload = r.json()
        if not payload.get("success"):
            return None, payload.get("error", {}).get("message", "Live provider error")
        data = payload.get("data") or {}
        with _live_lock:
            _live_cache[train_no] = {"fetched": now, "data": data}
        return data, None
    except Exception as e:
        return None, str(e)


def fetch_weather(lat, lon, force=False):
    if lat is None or lon is None or requests is None:
        return None, "Weather coordinates unavailable"
    try:
        latf, lonf = float(lat), float(lon)
    except (TypeError, ValueError):
        return None, "Invalid weather coordinates"
    key = (round(latf, 2), round(lonf, 2))
    now = datetime.now()
    with _weather_lock:
        cached = _weather_cache.get(key)
        if cached and not force and (now - cached["fetched"]).total_seconds() < WEATHER_CACHE_SECONDS:
            return cached["data"], None
    try:
        params = {
            "latitude": latf, "longitude": lonf,
            "current": "temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m,visibility",
            "timezone": "Asia/Kolkata"
        }
        r = requests.get(WEATHER_BASE, params=params, timeout=8)
        if r.status_code != 200:
            return None, f"Weather HTTP {r.status_code}"
        payload = r.json()
        cur = payload.get("current") or {}
        code = cur.get("weather_code")
        labels = {0:"Clear",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",45:"Fog",48:"Rime fog",51:"Light drizzle",53:"Drizzle",55:"Heavy drizzle",61:"Light rain",63:"Rain",65:"Heavy rain",71:"Light snow",73:"Snow",75:"Heavy snow",80:"Rain showers",81:"Rain showers",82:"Heavy showers",95:"Thunderstorm",96:"Thunderstorm",99:"Thunderstorm"}
        out={
            "temperature_c": cur.get("temperature_2m"),
            "humidity_pct": cur.get("relative_humidity_2m"),
            "precipitation_mm": cur.get("precipitation"),
            "rain_mm": cur.get("rain"),
            "wind_kmh": cur.get("wind_speed_10m"),
            "visibility_m": cur.get("visibility"),
            "weather_code": code,
            "condition": labels.get(code, "Unknown"),
            "updated": cur.get("time")
        }
        with _weather_lock:
            _weather_cache[key] = {"fetched": now, "data": out}
        return out, None
    except Exception as e:
        return None, str(e)

def compute_congestion(delay, status, next_station=None):
    d=max(0,float(delay or 0))
    if str(status).upper()=="AT STATION": score=45+d*0.6
    else: score=d*1.8
    score=max(0,min(100,round(score)))
    level="LOW" if score<25 else "MEDIUM" if score<60 else "HIGH"
    return {"score":score,"level":level,"source":"derived from live delay/status; no track-occupancy feed"}

def prediction_features(train, weather=None):
    delay=float(train.get("delay") or 0)
    speed=train.get("speed")
    speed=float(speed) if speed is not None else 0
    rain=float((weather or {}).get("rain_mm") or 0)
    wind=float((weather or {}).get("wind_kmh") or 0)
    visibility=float((weather or {}).get("visibility_m") or 10000)
    congestion=compute_congestion(delay, train.get("status"))
    weather_penalty=min(12, rain*0.8 + max(0, wind-35)*0.08 + max(0, 3000-visibility)/1000*1.5)
    congestion_penalty=congestion["score"]*0.05

    # If a trained historical model has been installed, use it for delay risk.
    ml_probability = None
    model_name = "rule-based prototype"
    if ETA_MODEL is not None and hasattr(ETA_MODEL, "predict_proba"):
        try:
            # Model features are deliberately small and available from the live feed.
            vals = {
                "current_delay": delay,
                "current_speed": speed,
                "rain_mm": rain,
                "wind_kmh": wind,
                "visibility_m": visibility,
                "congestion_score": congestion["score"],
            }
            import pandas as pd
            X = pd.DataFrame([{f: vals.get(f, 0) for f in ETA_MODEL_FEATURES}])
            ml_probability = float(ETA_MODEL.predict_proba(X)[0][1])
            model_name = "trained historical-delay ML model"
        except Exception:
            ml_probability = None

    # Transparent ETA adjustment. ML probability modifies the expected extra delay;
    # it does not pretend the historical classifier predicts an exact minute value.
    risk_extra = round((ml_probability or 0) * 8) if ml_probability is not None else 0
    predicted_extra=max(0, round(delay*0.35 + weather_penalty + congestion_penalty + risk_extra - max(0,speed-70)*0.03))
    confidence=max(60,min(96,round(94 - weather_penalty*1.2 - congestion_penalty*0.5)))
    return {
        "predicted_extra_delay":predicted_extra,
        "confidence":confidence,
        "weather_penalty_min":round(weather_penalty,1),
        "congestion_penalty_min":round(congestion_penalty,1),
        "delay_risk_probability":round(ml_probability,3) if ml_probability is not None else None,
        "model":model_name,
        "model_available":bool(ETA_MODEL is not None),
    }

def live_train_dict(data):
    train = data.get("train") or {}
    cur = data.get("currentLocation") or {}
    nxt = data.get("nextHalt") or {}
    route = data.get("route") or []
    current_code = cur.get("stationCode")
    current_route = next((x for x in route if x.get("stationCode") == current_code), {})
    next_code = nxt.get("stationCode")
    next_route = next((x for x in route if x.get("stationCode") == next_code), {})
    raw_delay = int(data.get("delayMinutes") or 0)
    # Keep the API value, but prevent a negative "delay" from being treated as an active delay.
    delay = max(0, raw_delay)
    early_minutes = abs(raw_delay) if raw_delay < 0 else 0
    status_raw = str(data.get("status") or "unknown").lower()
    current_status_raw = str(cur.get("status") or "").lower().replace("_", "-").strip()
    at_station = current_status_raw in ("at-station", "halted", "at station") or (bool(cur.get("isHalt")) and current_status_raw not in ("departed", "running", "enroute", "in-transit"))
    status = "AT STATION" if at_station else ("DELAYED" if delay >= 10 else "RUNNING")
    if status_raw in ("cancelled", "canceled"):
        status = "CANCELLED"
    scheduled = next_route.get("scheduledArrival") or next_route.get("scheduledDeparture")
    next_eta = None
    if scheduled:
        next_eta = eta_from_schedule(scheduled[11:16] if len(scheduled) >= 16 else scheduled, delay)
    lat = current_route.get("lat")
    lon = current_route.get("lng")
    if lat is None: lat = next_route.get("lat")
    if lon is None: lon = next_route.get("lng")
    # Prefer provider telemetry for current speed. Some provider responses can omit
    # speed or use a slightly different telemetry shape; do not collapse a missing
    # value into 0 km/h. A real 0 is preserved (e.g. while halted).
    telemetry = cur.get("telemetry") if isinstance(cur.get("telemetry"), dict) else {}
    raw_speed = cur.get("speedKmh")
    speed_source = "telemetry"
    if raw_speed is None:
        raw_speed = cur.get("speed")
    if raw_speed is None:
        raw_speed = telemetry.get("speedKmh", telemetry.get("speed"))
    try:
        speed = float(raw_speed) if raw_speed is not None and str(raw_speed).strip() != "" else None
    except (TypeError, ValueError):
        speed = None
    # If RailRadar does not provide speedKmh, derive speed from consecutive
    # live segmentProgress snapshots. RailRadar documents segmentProgress as a
    # 0..1 progress value on the current segment. This is a derived live
    # estimate, not a fake replacement for provider telemetry.
    segment_speed = next_route.get("speedToNextStationKmph")
    if speed is None:
        try:
            segment_speed = float(segment_speed) if segment_speed is not None else None
        except (TypeError, ValueError):
            segment_speed = None

        progress = cur.get("segmentProgress")
        updated_raw = data.get("lastUpdatedAt")
        current_seq = cur.get("sequence")
        derived_speed = None
        if progress is not None and updated_raw is not None and current_seq is not None:
            try:
                progress = float(progress)
                current_seq = int(current_seq)
                updated_dt = datetime.fromisoformat(str(updated_raw).replace("Z", "+00:00"))
                history_key = str(train.get("number") or data.get("trainNumber") or "")
                prev = _speed_history.get(history_key)

                # Determine the physical distance of the current route segment.
                route_idx = next((i for i, x in enumerate(route) if int(x.get("sequence", -1)) == current_seq), None)
                if route_idx is not None and route_idx + 1 < len(route):
                    start_stop = route[route_idx]
                    end_stop = route[route_idx + 1]
                    d1 = float(start_stop.get("distance")) if start_stop.get("distance") is not None else None
                    d2 = float(end_stop.get("distance")) if end_stop.get("distance") is not None else None
                    segment_km = (d2 - d1) if d1 is not None and d2 is not None else None

                    if segment_km is not None and segment_km > 0:
                        # First-choice fallback: estimate average speed since the
                        # actual departure from the segment's starting station.
                        # This can work on the very first API snapshot when the
                        # provider includes actualDeparture + segmentProgress.
                        actual_departure = start_stop.get("actualDeparture")
                        if actual_departure:
                            try:
                                dep_dt = datetime.fromisoformat(str(actual_departure).replace("Z", "+00:00"))
                                elapsed_hours = (updated_dt - dep_dt).total_seconds() / 3600.0
                                travelled_km = segment_km * max(0.0, min(1.0, progress))
                                if 0.02 <= elapsed_hours <= 4 and travelled_km >= 0:
                                    candidate = travelled_km / elapsed_hours
                                    if 1 <= candidate <= 160:
                                        derived_speed = candidate
                            except (TypeError, ValueError, OverflowError):
                                pass

                        if prev and prev.get("sequence") == current_seq and derived_speed is None:
                            dt_hours = (updated_dt - prev["updated_dt"]).total_seconds() / 3600.0
                            dp = progress - float(prev.get("progress", 0.0))
                            distance_km = segment_km * dp
                            if 0.0001 < dt_hours <= 2 and distance_km >= 0:
                                candidate = distance_km / dt_hours
                                # Reject obviously bad jumps caused by stale/reset feeds.
                                if 1 <= candidate <= 180:
                                    derived_speed = candidate

                        _speed_history[history_key] = {
                            "sequence": current_seq,
                            "progress": progress,
                            "updated_dt": updated_dt,
                        }
            except (TypeError, ValueError, OverflowError):
                derived_speed = None

        if derived_speed is not None:
            speed = derived_speed
            speed_source = "progress_derived"
        elif at_station:
            # A real halt is stationary. Do not use route segment speed as current speed.
            speed = 0.0
            speed_source = "stationary"
        else:
            speed_source = "unavailable"
    else:
        segment_speed = None
    confidence = max(70, min(98, round(96 - min(delay,30)*0.55)))
    base = {
        "train_no": str(train.get("number") or data.get("trainNumber") or ""),
        "name": train.get("name") or "Unknown train",
        "origin": (train.get("source") or {}).get("name") if isinstance(train.get("source"), dict) else train.get("source", ""),
        "destination": (train.get("destination") or {}).get("name") if isinstance(train.get("destination"), dict) else train.get("destination", ""),
        "category": train.get("category") or train.get("type") or "Indian Railways",
        "zone": "LIVE",
        "delay": delay,
        "early_minutes": early_minutes,
        "speed": round(speed, 1) if speed is not None else None,
        "speed_source": speed_source if speed is not None or segment_speed is not None else "unavailable",
        "segment_speed": round(segment_speed, 1) if segment_speed is not None else None,
        "status": status,
        "current_station": current_code or "—",
        "next_station": nxt.get("stationName") or next_code or "—",
        "platform": next_route.get("platform") or current_route.get("platform"),
        "lat": lat,
        "lon": lon,
        "updated": data.get("lastUpdatedAt") or datetime.now().isoformat(timespec="seconds"),
        "next_eta": next_eta,
        "confidence": confidence,
        "data_source": "RailRadar live feed",
        "is_live": bool(data.get("isLive", True)),
        "live_fetched_at": datetime.now().isoformat(timespec="seconds"),
        "route": route,
    }
    weather = None
    weather_error = None
    if lat is not None and lon is not None:
        weather, weather_error = fetch_weather(lat, lon)
    prediction = prediction_features(base, weather)
    base["weather"] = weather
    base["weather_error"] = weather_error
    base["congestion"] = compute_congestion(base.get("delay"), base.get("status"), base.get("next_station"))
    base["signal"] = {"status":"NOT SUPPLIED", "source":"RailRadar live feed does not provide railway signal aspect in this response"}
    base["prediction"] = prediction
    base["predicted_eta"] = eta_from_schedule(scheduled, delay + prediction["predicted_extra_delay"]) if scheduled else None
    base["actual_provider_eta"] = next_eta
    return base


def get_live_train(train_no, force=False):
    data, err = fetch_live(train_no, force=force)
    if data:
        return live_train_dict(data), None
    return None, err


@app.route("/")
def home(): return render_template("index.html")

@app.route("/api/health")
def health():
    return jsonify({"ok":True,"service":"RailETA API","time":datetime.now().isoformat(),
                    "data_mode":"LIVE" if live_enabled() else "DEMO",
                    "live_provider":"RailRadar" if live_enabled() else None,
                    "live_trains":LIVE_NUMBERS if live_enabled() else [], "ml_model_loaded": bool(ETA_MODEL is not None)})

@app.route("/api/config")
def config():
    return jsonify({
        "mode": "LIVE" if live_enabled() else "DEMO",
        "provider": "RailRadar" if live_enabled() else "Simulation",
        "live_trains": LIVE_NUMBERS if live_enabled() else [],
        "refresh_seconds": LIVE_CACHE_SECONDS if live_enabled() else 10,
        "weather_cache_seconds": WEATHER_CACHE_SECONDS,
        "ml_model_loaded": bool(ETA_MODEL is not None),
        "message": "Live railway feed connected" if live_enabled() else "Add RAILRADAR_API_KEY in Render to enable live data"
    })


def get_all_trains(q="", force=False):
    # Live mode: configured trains populate the dashboard. A numeric search can also
    # fetch ANY train on-demand, so the UI is not limited to LIVE_TRAIN_NUMBERS.
    if live_enabled():
        out=[]
        errors=[]
        q_clean=q.lower().strip()
        for no in LIVE_NUMBERS:
            d, err = get_live_train(no, force=force)
            if d:
                out.append(d)
            else:
                errors.append({"train_no":no,"error":err})

        if q_clean:
            filtered=[t for t in out if q_clean in str(t.get("train_no","")).lower()
                      or q_clean in str(t.get("name","")).lower()
                      or q_clean in str(t.get("origin","")).lower()
                      or q_clean in str(t.get("destination","")).lower()]
            if filtered:
                return filtered, errors

            # On-demand lookup: a train number not in the configured dashboard list.
            # This lets the search box scale beyond the curated list without storing
            # every Indian train number in an environment variable.
            if q_clean.isdigit() and 4 <= len(q_clean) <= 6:
                d, err = get_live_train(q_clean, force=force)
                if d:
                    return [d], errors
                errors.append({"train_no":q_clean,"error":err or "Train not found or live data unavailable"})
            return [], errors
        return out, errors
    c=conn()
    if q:
        rows=c.execute("SELECT * FROM trains WHERE lower(train_no) LIKE ? OR lower(name) LIKE ? OR lower(origin) LIKE ? OR lower(destination) LIKE ?",(f"%{q}%",)*4).fetchall()
    else: rows=c.execute("SELECT * FROM trains ORDER BY train_no").fetchall()
    c.close()
    return [demo_train_dict(r) for r in rows], []


@app.route("/api/trains")
def trains():
    q=request.args.get("q","").strip()
    force=request.args.get("force") == "1"
    data, errors=get_all_trains(q, force)
    return jsonify({"trains":data,"errors":errors,"mode":"LIVE" if live_enabled() else "DEMO"})


@app.route("/api/trains/<train_no>")
def train(train_no):
    if live_enabled():
        if not train_no.isdigit() or not (4 <= len(train_no) <= 6):
            return jsonify({"error":"Enter a valid train number","train_no":train_no}),400
        d, err=get_live_train(train_no)
        if d: return jsonify(d)
        return jsonify({"error":err or "Live train unavailable","train_no":train_no}),503
    c=conn(); r=c.execute("SELECT * FROM trains WHERE train_no=?",(train_no,)).fetchone(); c.close()
    if not r: return jsonify({"error":"Train not found"}),404
    return jsonify(demo_train_dict(r))


@app.route("/api/trains/<train_no>/stations")
def station_list(train_no):
    if live_enabled():
        d, err=fetch_live(train_no)
        if not d: return jsonify({"error":err or "Live route unavailable"}),503
        out=[]
        delay=int(d.get("delayMinutes") or 0)
        for r in d.get("route") or []:
            scheduled=r.get("scheduledArrival") or r.get("scheduledDeparture")
            short=scheduled[11:16] if scheduled and len(scheduled)>=16 else scheduled
            predicted=max(0, delay)
            out.append({"seq":r.get("sequence"),"station":r.get("stationName") or r.get("stationCode"),"scheduled":short,
                        "distance":r.get("distance"),"platform":r.get("platform"),"status":r.get("status"),
                        "predicted_delay":predicted,"eta":eta_from_schedule(short,predicted),"confidence":max(70,min(98,round(96-predicted*.55)))})
        return jsonify(out)
    c=conn(); tr=c.execute("SELECT delay FROM trains WHERE train_no=?",(train_no,)).fetchone(); rows=c.execute("SELECT * FROM stations WHERE train_no=? ORDER BY seq",(train_no,)).fetchall(); c.close()
    if not tr: return jsonify({"error":"Train not found"}),404
    delay=tr["delay"]; out=[]
    for r in rows:
        d=dict(r); predicted=max(0,round(delay-min(delay*.35,max(0,r["seq"]*2))+(((r["seq"]*7)%9)-4)))
        d["predicted_delay"]=predicted; d["eta"]=eta_from_schedule(d["scheduled"],predicted); d["confidence"]=max(61,min(97,round(96-predicted*1.1-r["seq"]*.8))); out.append(d)
    return jsonify(out)


@app.route("/api/trains/<train_no>/events")
def events(train_no):
    if live_enabled():
        d, err=fetch_live(train_no)
        if not d: return jsonify([])
        return jsonify([{"event_type":"LIVE FEED","impact":int(d.get("delayMinutes") or 0),
                         "message":f"Provider reports {int(d.get('delayMinutes') or 0)} min current delay",
                         "created":d.get("lastUpdatedAt") or datetime.now().isoformat(timespec="seconds")}])
    c=conn(); rows=c.execute("SELECT * FROM events WHERE train_no=? ORDER BY id DESC LIMIT 12",(train_no,)).fetchall(); c.close(); return jsonify([dict(r) for r in rows])


@app.route("/api/trains/<train_no>/environment")
def environment(train_no):
    if not live_enabled():
        return jsonify({"weather":None,"signal":{"status":"DEMO / NOT CONNECTED"},"congestion":{"level":"DEMO"}})
    d, err = fetch_live(train_no)
    if not d:
        return jsonify({"error":err or "Live train unavailable"}),503
    live = live_train_dict(d)
    return jsonify({"weather":live.get("weather"),"weather_error":live.get("weather_error"),"signal":live.get("signal"),"congestion":live.get("congestion"),"prediction":live.get("prediction")})

@app.route("/api/live/tick", methods=["POST"])
def live_tick():
    if live_enabled():
        data, errors=get_all_trains(force=True)
        return jsonify({"ok":True,"mode":"LIVE","updated":len(data),"errors":errors,"time":datetime.now().isoformat(timespec="seconds")})
    c=conn(); rows=c.execute("SELECT * FROM trains").fetchall(); now=datetime.now().isoformat(timespec="seconds"); changed=0
    for r in rows:
        delta=random.choices([-2,-1,0,0,1,2,3,5],weights=[4,8,28,20,12,8,4,2])[0]
        new_delay=max(0,min(180,int(r["delay"] or 0)+delta)); speed=max(35,min(125,float(r["speed"] or 80)+random.choice([-7,-3,0,2,5])))
        status="DELAYED" if new_delay>=10 else "RUNNING"
        if random.random()<.04: status="AT STATION"; speed=0
        lat=float(r["lat"] or 20)+random.uniform(-.012,.012); lon=float(r["lon"] or 77)+random.uniform(-.012,.012)
        c.execute("UPDATE trains SET delay=?,speed=?,status=?,lat=?,lon=?,updated=? WHERE train_no=?",(new_delay,round(speed,1),status,lat,lon,now,r["train_no"]))
        changed+=1
    c.commit(); c.close(); return jsonify({"ok":True,"mode":"DEMO","updated":changed,"time":now})


@app.route("/api/trains/<train_no>/simulate", methods=["POST"])
def simulate(train_no):
    if live_enabled():
        d, err=get_live_train(train_no, force=True)
        if d: return jsonify(d)
        return jsonify({"error":err or "Live provider unavailable"}),503
    c=conn(); r=c.execute("SELECT * FROM trains WHERE train_no=?",(train_no,)).fetchone()
    if not r: c.close(); return jsonify({"error":"Train not found"}),404
    delta=random.choice([-2,-1,0,0,1,2,4,7]); new_delay=max(0,min(180,r["delay"]+delta)); speed=max(0,min(125,r["speed"]+random.choice([-8,-4,0,3,6])))
    status="AT STATION" if speed==0 else ("DELAYED" if new_delay>=10 else "RUNNING"); lat=(r["lat"] or 20)+random.uniform(-.03,.03); lon=(r["lon"] or 77)+random.uniform(-.03,.03); now=datetime.now().isoformat(timespec="seconds")
    c.execute("UPDATE trains SET delay=?,speed=?,status=?,lat=?,lon=?,updated=? WHERE train_no=?",(new_delay,round(speed,1),status,lat,lon,now,train_no)); c.commit(); nr=c.execute("SELECT * FROM trains WHERE train_no=?",(train_no,)).fetchone(); c.close(); return jsonify(demo_train_dict(nr))


init_db()
if __name__=="__main__": app.run(debug=True,host="0.0.0.0",port=5000)
