from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import os, random, sqlite3, threading
from datetime import datetime, timedelta

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

app = Flask(__name__)
CORS(app)
DB = "rail_eta.db"

RAILRADAR_BASE = "https://api.railradar.in/v1"
RAILRADAR_API_KEY = os.getenv("RAILRADAR_API_KEY", "").strip()
LIVE_NUMBERS = [x.strip() for x in os.getenv("LIVE_TRAIN_NUMBERS", "12919,12952,12002").split(",") if x.strip()]
LIVE_CACHE_SECONDS = int(os.getenv("LIVE_CACHE_SECONDS", "300"))  # 5 min: keeps free sandbox usage manageable
_live_cache = {}
_live_lock = threading.Lock()

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
            params={"authoritative":"true"}, timeout=12
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


def live_train_dict(data):
    train = data.get("train") or {}
    cur = data.get("currentLocation") or {}
    nxt = data.get("nextHalt") or {}
    route = data.get("route") or []
    current_code = cur.get("stationCode")
    current_route = next((x for x in route if x.get("stationCode") == current_code), {})
    next_code = nxt.get("stationCode")
    next_route = next((x for x in route if x.get("stationCode") == next_code), {})
    delay = int(data.get("delayMinutes") or 0)
    status_raw = str(data.get("status") or "unknown").lower()
    status = "AT STATION" if cur.get("isHalt") else ("DELAYED" if delay >= 10 else "RUNNING")
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
    confidence = max(70, min(98, round(96 - min(delay,30)*0.55)))
    return {
        "train_no": str(train.get("number") or data.get("trainNumber") or ""),
        "name": train.get("name") or "Unknown train",
        "origin": (train.get("source") or {}).get("name") if isinstance(train.get("source"), dict) else train.get("source", ""),
        "destination": (train.get("destination") or {}).get("name") if isinstance(train.get("destination"), dict) else train.get("destination", ""),
        "category": train.get("category") or train.get("type") or "Indian Railways",
        "zone": "LIVE",
        "delay": delay,
        "speed": round(float(cur.get("speedKmh") or 0), 1),
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
                    "live_trains":LIVE_NUMBERS if live_enabled() else []})

@app.route("/api/config")
def config():
    return jsonify({
        "mode": "LIVE" if live_enabled() else "DEMO",
        "provider": "RailRadar" if live_enabled() else "Simulation",
        "live_trains": LIVE_NUMBERS if live_enabled() else [],
        "refresh_seconds": LIVE_CACHE_SECONDS if live_enabled() else 10,
        "message": "Live railway feed connected" if live_enabled() else "Add RAILRADAR_API_KEY in Render to enable live data"
    })


def get_all_trains(q="", force=False):
    # With a live key, show only configured live trains. This avoids falsely labelling demo rows as real.
    if live_enabled():
        out=[]
        errors=[]
        for no in LIVE_NUMBERS:
            d, err = get_live_train(no, force=force)
            if d:
                out.append(d)
            else:
                errors.append({"train_no":no,"error":err})
        q=q.lower().strip()
        if q:
            out=[t for t in out if q in str(t.get("train_no","")).lower() or q in str(t.get("name","")).lower() or q in str(t.get("origin","")).lower() or q in str(t.get("destination","")).lower()]
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
    if live_enabled() and train_no in LIVE_NUMBERS:
        d, err=get_live_train(train_no)
        if d: return jsonify(d)
        return jsonify({"error":err or "Live train unavailable","train_no":train_no}),503
    c=conn(); r=c.execute("SELECT * FROM trains WHERE train_no=?",(train_no,)).fetchone(); c.close()
    if not r: return jsonify({"error":"Train not found"}),404
    return jsonify(demo_train_dict(r))


@app.route("/api/trains/<train_no>/stations")
def station_list(train_no):
    if live_enabled() and train_no in LIVE_NUMBERS:
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
    if live_enabled() and train_no in LIVE_NUMBERS:
        d, err=fetch_live(train_no)
        if not d: return jsonify([])
        return jsonify([{"event_type":"LIVE FEED","impact":int(d.get("delayMinutes") or 0),
                         "message":f"Provider reports {int(d.get('delayMinutes') or 0)} min current delay",
                         "created":d.get("lastUpdatedAt") or datetime.now().isoformat(timespec="seconds")}])
    c=conn(); rows=c.execute("SELECT * FROM events WHERE train_no=? ORDER BY id DESC LIMIT 12",(train_no,)).fetchall(); c.close(); return jsonify([dict(r) for r in rows])


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
    if live_enabled() and train_no in LIVE_NUMBERS:
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
