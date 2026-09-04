"""Train RailETA's historical delay-risk model from the Kaggle competition dataset.

Expected input: ir_train.csv from the Kaggle competition
Indian Railways: Predict Train Delay.
The competition target is `is_delayed` (arrival >15 minutes late).
This model predicts delay risk; it is NOT an exact-minute ETA model.
"""
from pathlib import Path
import argparse, json
import pandas as pd
import joblib
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, accuracy_score
from sklearn.model_selection import train_test_split

FEATURES = [
    "current_delay", "current_speed", "rain_mm", "wind_kmh", "visibility_m",
    "congestion_score",
]
# Historical columns used when available. The live app will provide the live-compatible subset.
HISTORICAL_FEATURES = [
    "zone_congestion_index", "zone_fog_index", "distance_km", "num_scheduled_stops",
    "scheduled_travel_hours", "is_monsoon_season", "is_fog_risk", "fog_risk_score",
    "season_severity_score", "loco_age_years", "coach_age_years", "has_lhb_coaches",
    "is_rake_shared", "maintenance_score", "seat_utilisation_pct", "is_overloaded",
    "late_incoming_rake", "is_special_train", "route_historical_ontime_pct",
    "departure_hour", "month", "day_of_week", "is_weekend", "is_night_departure",
    "is_peak_hour", "is_festival_season", "track_doubled", "is_hdn_route",
    "is_electrified", "psr_count", "is_circular_route", "zone", "zone_abbr",
    "source_station_category", "destination_station_category", "season", "traction_type",
]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to ir_train.csv")
    ap.add_argument("--out", default="model/eta_delay_model.joblib")
    ap.add_argument("--sample", type=int, default=300000, help="Rows to train on; use 0 for all")
    args=ap.parse_args()
    df=pd.read_csv(args.csv, nrows=args.sample or None)
    if "is_delayed" not in df.columns:
        raise ValueError("Target is_delayed not found")
    # Explicitly exclude leakage columns mentioned by the competition.
    usable=[c for c in HISTORICAL_FEATURES if c in df.columns]
    if not usable:
        raise ValueError("No compatible historical features found")
    X=df[usable].copy(); y=df["is_delayed"].astype(int)
    cat=[c for c in usable if X[c].dtype == "object"]
    num=[c for c in usable if c not in cat]
    pre=ColumnTransformer([
        ("num", Pipeline([("impute",SimpleImputer(strategy="median"))]), num),
        ("cat", Pipeline([("impute",SimpleImputer(strategy="most_frequent")),("oh",OneHotEncoder(handle_unknown="ignore"))]), cat),
    ])
    model=HistGradientBoostingClassifier(max_iter=220, learning_rate=0.08, max_leaf_nodes=31, random_state=42)
    # HGB needs dense input, so use pandas one-hot manually for a compact robust pipeline.
    X2=pd.get_dummies(X, columns=cat, dummy_na=True)
    X2=X2.fillna(X2.median(numeric_only=True)).fillna(0)
    Xtr,Xv,ytr,yv=train_test_split(X2,y,test_size=0.2,stratify=y,random_state=42)
    model.fit(Xtr,ytr)
    prob=model.predict_proba(Xv)[:,1]
    print("Validation AUC:", round(roc_auc_score(yv,prob),4))
    print("Validation accuracy:", round(accuracy_score(yv,(prob>=0.5).astype(int)),4))
    bundle={"model":model,"features":list(X2.columns),"source_features":usable,"target":"is_delayed","note":"Historical delay-risk classifier; not exact-minute ETA."}
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); joblib.dump(bundle,out)
    Path(out.with_suffix(".json")).write_text(json.dumps({"features":list(X2.columns),"source_features":usable},indent=2))
    print("Saved",out)
if __name__=="__main__": main()
