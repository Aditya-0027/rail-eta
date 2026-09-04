from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import sqlite3, random, math
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)
DB = "rail_eta.db"

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
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    c=conn()
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
    count=c.execute("SELECT COUNT(*) FROM trains").fetchone()[0]
    if count==0:
        now=datetime.now()
        for i,t in enumerate(SEED_TRAINS):
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
            if delay:
                c.execute("INSERT INTO events(train_no,event_type,impact,message,created) VALUES(?,?,?,?,?)",
                          (no,"CONGESTION",min(delay,12),f"Downstream congestion contributed +{min(delay,12)} min",now.isoformat(timespec="seconds")))
        c.commit()
    c.close()

def train_dict(r):
    d=dict(r)
    d["updated_ago"]="live"
    return d

@app.route("/")
def home(): return render_template("index.html")

@app.route("/api/health")
def health(): return jsonify({"ok":True,"service":"RailETA API","time":datetime.now().isoformat()})

@app.route("/api/trains")
def trains():
    q=request.args.get("q","").strip().lower()
    c=conn()
    if q:
        rows=c.execute("SELECT * FROM trains WHERE lower(train_no) LIKE ? OR lower(name) LIKE ? OR lower(origin) LIKE ? OR lower(destination) LIKE ?",
                       (f"%{q}%",)*4).fetchall()
    else: rows=c.execute("SELECT * FROM trains ORDER BY train_no").fetchall()
    c.close()
    return jsonify([train_dict(r) for r in rows])

@app.route("/api/trains/<train_no>")
def train(train_no):
    c=conn(); r=c.execute("SELECT * FROM trains WHERE train_no=?",(train_no,)).fetchone(); c.close()
    if not r: return jsonify({"error":"Train not found"}),404
    return jsonify(train_dict(r))

@app.route("/api/trains/<train_no>/stations")
def station_list(train_no):
    c=conn(); tr=c.execute("SELECT delay FROM trains WHERE train_no=?",(train_no,)).fetchone()
    rows=c.execute("SELECT * FROM stations WHERE train_no=? ORDER BY seq",(train_no,)).fetchall(); c.close()
    if not tr: return jsonify({"error":"Train not found"}),404
    delay=tr["delay"]
    out=[]
    for r in rows:
        d=dict(r)
        # Demonstration dynamic forecast: delay attenuates by recovery + local variability.
        recovery=min(delay*0.35, max(0, r["seq"]*2))
        variance=((r["seq"]*7)%9)-4
        predicted=max(0, round(delay-recovery+variance))
        h,m=map(int,r["scheduled"].split(":"))
        mins=(h*60+m+predicted)%1440
        d["predicted_delay"]=predicted
        d["eta"]=f"{mins//60:02d}:{mins%60:02d}"
        d["confidence"]=max(61,min(97,round(96-predicted*1.1-r["seq"]*.8)))
        out.append(d)
    return jsonify(out)

@app.route("/api/trains/<train_no>/events")
def events(train_no):
    c=conn(); rows=c.execute("SELECT * FROM events WHERE train_no=? ORDER BY id DESC LIMIT 12",(train_no,)).fetchall(); c.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/trains/<train_no>/simulate", methods=["POST"])
def simulate(train_no):
    c=conn(); r=c.execute("SELECT * FROM trains WHERE train_no=?",(train_no,)).fetchone()
    if not r: c.close(); return jsonify({"error":"Train not found"}),404
    # Simulated streaming update.
    delta=random.choice([-2,-1,0,0,1,2,4,7])
    new_delay=max(0,min(180,r["delay"]+delta))
    speed=max(0,min(125,r["speed"]+random.choice([-8,-4,0,3,6])))
    if speed==0: status="AT STATION"
    elif new_delay>=10: status="DELAYED"
    else: status="RUNNING"
    lat=(r["lat"] or 20)+random.uniform(-.03,.03)
    lon=(r["lon"] or 77)+random.uniform(-.03,.03)
    now=datetime.now().isoformat(timespec="seconds")
    c.execute("UPDATE trains SET delay=?,speed=?,status=?,lat=?,lon=?,updated=? WHERE train_no=?",
              (new_delay,round(speed,1),status,lat,lon,now,train_no))
    if delta>=4:
        c.execute("INSERT INTO events(train_no,event_type,impact,message,created) VALUES(?,?,?,?,?)",
                  (train_no,"LIVE UPDATE",delta,f"Live network condition added +{delta} min",now))
    c.commit()
    nr=c.execute("SELECT * FROM trains WHERE train_no=?",(train_no,)).fetchone(); c.close()
    return jsonify(train_dict(nr))

init_db()
if __name__=="__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
