"""Demand forecasting model — predicts ticket volume per shift."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score

from src.forecasting.feature_engineering import FEATURE_COLUMNS, add_time_features


@dataclass
class ForecastResult:
    """Result of demand forecasting."""

    predictions: pd.DataFrame  # date, shift, predicted_volume
    model_metrics: dict  # MAE, R², etc.
    volume_model: GradientBoostingRegressor


def train_volume_model(
    historical: pd.DataFrame,
    validation_months: int = 1,
) -> ForecastResult:
    """Train a ticket volume forecasting model.

    Uses time-based train/validation split: last `validation_months` months for validation.
    """
    df = add_time_features(historical)
    X = df[FEATURE_COLUMNS]
    y = df["ticket_volume"]

    # Time-based split
    cutoff_date = df["date"].max() - pd.DateOffset(months=validation_months)
    train_mask = df["date"] <= cutoff_date
    val_mask = df["date"] > cutoff_date

    X_train, X_val = X[train_mask], X[val_mask]
    y_train, y_val = y[train_mask], y[val_mask]

    model = GradientBoostingRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        min_samples_leaf=5,
        random_state=42,
    )
    model.fit(X_train, y_train)

    val_pred = model.predict(X_val)
    metrics = {
        "val_mae": mean_absolute_error(y_val, val_pred),
        "val_r2": r2_score(y_val, val_pred),
        "val_size": len(y_val),
        "train_size": len(y_train),
    }

    # Retrain on full data for production use
    model.fit(X, y)

    return ForecastResult(
        predictions=pd.DataFrame(),  # filled by predict_april
        model_metrics=metrics,
        volume_model=model,
    )


def predict_april_volume(
    forecast_result: ForecastResult,
    year: int = 2026,
    month: int = 4,
    days: int = 30,
) -> pd.DataFrame:
    """Predict ticket volume for each shift in April 2026."""
    dates = pd.date_range(f"{year}-{month:02d}-01", periods=days, freq="D")
    rows = []
    for date in dates:
        for shift in [1, 2, 3, 4]:
            rows.append({"date": date, "shift": shift})

    pred_df = pd.DataFrame(rows)
    pred_df = add_time_features(pred_df)
    X = pred_df[FEATURE_COLUMNS]

    pred_df["predicted_volume"] = np.round(
        forecast_result.volume_model.predict(X)
    ).astype(int)
    pred_df["predicted_volume"] = pred_df["predicted_volume"].clip(lower=0)

    forecast_result.predictions = pred_df[["date", "shift", "predicted_volume"]]
    return forecast_result.predictions
