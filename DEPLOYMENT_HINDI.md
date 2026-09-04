# RailETA — Live + Weather + ML deployment

1. Keep `RAILRADAR_API_KEY` in Render Environment Variables.
2. Keep `LIVE_TRAIN_NUMBERS` as your selected trains. Do not continuously poll 100 trains on the free API quota.
3. Train the ML model in Colab using `RailETA_ML_Training.ipynb`.
4. Copy `model/eta_delay_model.joblib` into the project before deploying if you want the trained historical delay-risk model loaded.
5. Render runs the model for inference only.

## Important truth for the demo
- RailRadar = live provider feed when API returns live data.
- Open-Meteo = live weather; no key required.
- Congestion = derived indicator, not railway track-occupancy telemetry.
- Signal aspect = NOT SUPPLIED unless an authorized railway signalling feed is connected.
- Kaggle competition data = synthetic/educational; use it to demonstrate the ML pipeline, not to claim official IR historical training.
