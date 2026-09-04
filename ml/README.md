# RailETA ML

The included Kaggle competition dataset is a **synthetic educational dataset**, not real passenger/train records. It has 1.5M journey rows and the target `is_delayed` (>15 minutes late). It is useful for demonstrating the ML pipeline, but the resulting model must not be presented as trained on official Indian Railways operational history.

Run on Google Colab or your laptop:

```bash
pip install -r requirements-ml.txt
python ml/train_model.py --csv /content/ir_train.csv --sample 300000
```

The model is a historical **delay-risk classifier**. It does not directly predict exact ETA minutes. RailETA combines the live provider ETA with the model's delay-risk signal and live weather/congestion adjustments.

For a true minute-level ETA model, collect authorized historical running events with actual and scheduled arrival timestamps and train on `target_minutes_to_arrival`.
