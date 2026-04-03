"""Staffing optimizer — determines minimum agents per shift to meet quality targets."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

from src.config import (
    CSAT_TARGET,
    MAX_WAIT_SECONDS,
    TOTAL_SENIORS,
    TOTAL_JUNIORS,
    TOTAL_ENGLISH,
)

QUALITY_FEATURES = ["ticket_volume", "senior_staffed", "junior_staffed", "english_staffed"]


@dataclass
class QualityModels:
    """Trained models predicting CSAT and wait time from staffing + volume."""

    csat_model: GradientBoostingRegressor
    wait_model: GradientBoostingRegressor
    csat_r2: float
    wait_r2: float


def train_quality_models(historical: pd.DataFrame) -> QualityModels:
    """Train models that predict CSAT and wait time from (volume, staffing)."""
    X = historical[QUALITY_FEATURES]

    # CSAT model
    csat_model = GradientBoostingRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.1,
        subsample=0.8, min_samples_leaf=5, random_state=42,
    )
    csat_model.fit(X, historical["avg_csat"])
    csat_r2 = csat_model.score(X, historical["avg_csat"])

    # Wait time model
    wait_model = GradientBoostingRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.1,
        subsample=0.8, min_samples_leaf=5, random_state=42,
    )
    wait_model.fit(X, historical["avg_wait_seconds"])
    wait_r2 = wait_model.score(X, historical["avg_wait_seconds"])

    return QualityModels(
        csat_model=csat_model,
        wait_model=wait_model,
        csat_r2=csat_r2,
        wait_r2=wait_r2,
    )


def predict_quality(
    quality_models: QualityModels,
    ticket_volume: int,
    senior: int,
    junior: int,
    english: int,
) -> tuple[float, float]:
    """Predict CSAT and wait time for a given staffing configuration."""
    X = pd.DataFrame(
        [[ticket_volume, senior, junior, english]],
        columns=QUALITY_FEATURES,
    )
    csat = quality_models.csat_model.predict(X)[0]
    wait = quality_models.wait_model.predict(X)[0]
    return float(csat), float(wait)


def _build_staffing_grid(
    min_senior: int = 0,
    min_junior: int = 1,
    min_english: int = 0,
    max_senior: int = TOTAL_SENIORS,
    max_junior: int = TOTAL_JUNIORS,
    max_english: int = TOTAL_ENGLISH,
    max_total: int = 20,
) -> np.ndarray:
    """Pre-build all feasible (senior, junior, english) staffing combos."""
    combos = []
    for senior in range(min_senior, max_senior + 1):
        for junior in range(min_junior, max_junior + 1):
            if senior + junior > max_total:
                break
            for english in range(min_english, max_english + 1):
                combos.append([senior, junior, english])
    return np.array(combos)


def compute_shift_floors(historical: pd.DataFrame) -> dict[int, dict]:
    """Compute minimum staffing floors per shift from historical data.

    Uses the 10th percentile of staffing levels observed when quality targets
    were met, ensuring we don't extrapolate outside the training distribution.
    """
    floors = {}
    for shift in [1, 2, 3, 4]:
        shift_data = historical[historical["shift"] == shift]
        # Use shifts where targets were met, or all if too few met targets
        good = shift_data[
            (shift_data["avg_csat"] >= CSAT_TARGET) &
            (shift_data["avg_wait_seconds"] <= MAX_WAIT_SECONDS)
        ]
        if len(good) < 10:
            good = shift_data

        floors[shift] = {
            "min_senior": max(0, int(good["senior_staffed"].quantile(0.10))),
            "min_junior": max(1, int(good["junior_staffed"].quantile(0.10))),
            "min_english": max(0, int(good["english_staffed"].quantile(0.10))),
        }
    return floors


def find_minimum_staffing_batch(
    quality_models: QualityModels,
    volumes: list[int],
    shifts: list[int],
    shift_floors: dict[int, dict],
    csat_target: float = CSAT_TARGET,
    max_wait: float = MAX_WAIT_SECONDS,
    max_senior: int = TOTAL_SENIORS,
    max_junior: int = TOTAL_JUNIORS,
    max_english: int = TOTAL_ENGLISH,
) -> list[dict]:
    """Find minimum staffing for multiple volumes at once using vectorized prediction.

    Uses per-shift historical staffing floors to avoid extrapolation.
    """
    # Pre-build grids per shift (different floors per shift)
    grids_by_shift = {}
    for shift_id in [1, 2, 3, 4]:
        floors = shift_floors.get(shift_id, {})
        grids_by_shift[shift_id] = _build_staffing_grid(
            min_senior=floors.get("min_senior", 0),
            min_junior=floors.get("min_junior", 1),
            min_english=floors.get("min_english", 0),
            max_senior=max_senior,
            max_junior=max_junior,
            max_english=max_english,
        )
    results = []

    for volume, shift_id in zip(volumes, shifts):
        grid = grids_by_shift[shift_id]
        # Build feature matrix: [volume, senior, junior, english] for all combos
        X = pd.DataFrame({
            "ticket_volume": volume,
            "senior_staffed": grid[:, 0],
            "junior_staffed": grid[:, 1],
            "english_staffed": grid[:, 2],
        })

        csat_preds = quality_models.csat_model.predict(X)
        wait_preds = quality_models.wait_model.predict(X)

        # Find combos meeting both targets
        meets_targets = (csat_preds >= csat_target) & (wait_preds <= max_wait)
        totals = grid[:, 0] + grid[:, 1]

        if meets_targets.any():
            # Among those meeting targets, pick the one with lowest total headcount
            # Break ties by lowest wait time
            valid_idx = np.where(meets_targets)[0]
            valid_totals = totals[valid_idx]
            min_total = valid_totals.min()
            min_total_idx = valid_idx[valid_totals == min_total]
            # Among min-total options, pick lowest wait
            best_i = min_total_idx[np.argmin(wait_preds[min_total_idx])]

            results.append({
                "senior": int(grid[best_i, 0]),
                "junior": int(grid[best_i, 1]),
                "english": int(grid[best_i, 2]),
                "total": int(totals[best_i]),
                "predicted_csat": round(float(csat_preds[best_i]), 2),
                "predicted_wait": round(float(wait_preds[best_i]), 1),
                "targets_met": True,
            })
        else:
            # Best effort: highest composite score
            scores = csat_preds * 10 - wait_preds * 0.1 - totals * 0.5
            best_i = np.argmax(scores)
            results.append({
                "senior": int(grid[best_i, 0]),
                "junior": int(grid[best_i, 1]),
                "english": int(grid[best_i, 2]),
                "total": int(totals[best_i]),
                "predicted_csat": round(float(csat_preds[best_i]), 2),
                "predicted_wait": round(float(wait_preds[best_i]), 1),
                "targets_met": False,
            })

    return results


def compute_staffing_requirements(
    volume_predictions: pd.DataFrame,
    quality_models: QualityModels,
    historical: pd.DataFrame,
    csat_target: float = CSAT_TARGET,
    max_wait: float = MAX_WAIT_SECONDS,
) -> pd.DataFrame:
    """Compute staffing requirements for all predicted (date, shift) combinations."""
    shift_floors = compute_shift_floors(historical)
    volumes = volume_predictions["predicted_volume"].tolist()
    shifts = volume_predictions["shift"].astype(int).tolist()

    staffing_list = find_minimum_staffing_batch(
        quality_models, volumes, shifts, shift_floors, csat_target, max_wait
    )

    rows = []
    for (_, vol_row), staffing in zip(volume_predictions.iterrows(), staffing_list):
        rows.append({
            "date": vol_row["date"],
            "shift": int(vol_row["shift"]),
            "predicted_volume": int(vol_row["predicted_volume"]),
            **staffing,
        })

    return pd.DataFrame(rows)
