# RailETA — Dynamic Live ETA + Weather + ML

RailETA is a prototype for dynamic train ETA and delay-risk prediction.

## Current stack
- Flask backend
- RailRadar live train running API
- Open-Meteo weather API (no key for non-commercial use)
- Cached live requests
- Optional trained historical delay-risk model
- Browser dashboard

## ML truth
The included ML training pipeline uses the Kaggle **Indian Railways: Predict Train Delay** competition dataset. Kaggle describes 1.5M training journeys and a target `is_delayed` (>15 min late). The competition rules identify the data as synthetic/educational. Therefore the model is a **historical delay-risk demo**, not a model trained on official Indian Railways operational history. For a true exact-minute ETA model, collect authorized historical actual-vs-scheduled arrival records and train a regression/time-to-arrival model.

## Free weather
Open-Meteo provides a no-key weather API for non-commercial use. Cache weather calls to reduce load.

## Speed fallback update

If RailRadar supplies `currentLocation.speedKmh`, RailETA uses it directly. If it is missing, RailETA now derives a live speed estimate from `segmentProgress` plus route distance and timing (actual departure when available, otherwise consecutive live snapshots). The UI marks this with `*` and does not confuse the provider's `speedToNextStationKmph` with current speed. At a genuine halt, current speed is 0 km/h.
