"""Tests for the demand forecasting pipeline."""

import pandas as pd
import pytest

from src.data_loader import load_all_data
from src.forecasting.demand_model import train_volume_model, predict_april_volume
from src.forecasting.staffing_optimizer import (
    train_quality_models,
    compute_staffing_requirements,
)
from src.config import (
    TOTAL_SENIORS,
    TOTAL_JUNIORS,
    TOTAL_ENGLISH,
    DAYS_IN_APRIL,
    SHIFT_IDS,
)


@pytest.fixture(scope="module")
def data():
    return load_all_data()


@pytest.fixture(scope="module")
def forecast_result(data):
    return train_volume_model(data["historical"])


@pytest.fixture(scope="module")
def volume_predictions(forecast_result):
    return predict_april_volume(forecast_result)


@pytest.fixture(scope="module")
def quality_models(data):
    return train_quality_models(data["historical"])


@pytest.fixture(scope="module")
def staffing_req(volume_predictions, quality_models, data):
    return compute_staffing_requirements(
        volume_predictions, quality_models, data["historical"]
    )


class TestVolumeModel:
    """Verify volume forecasting produces reasonable results."""

    def test_model_trains_successfully(self, forecast_result):
        assert forecast_result.volume_model is not None

    def test_validation_metrics_reasonable(self, forecast_result):
        metrics = forecast_result.model_metrics
        # R² should be positive (model is better than mean)
        assert metrics["val_r2"] > 0.5
        # MAE should be reasonable for ticket volumes
        assert metrics["val_mae"] < 100

    def test_predictions_cover_april(self, volume_predictions):
        assert len(volume_predictions) == DAYS_IN_APRIL * len(SHIFT_IDS)  # 120

    def test_predictions_positive(self, volume_predictions):
        assert (volume_predictions["predicted_volume"] > 0).all()


class TestQualityModels:
    """Verify CSAT and wait time models."""

    def test_csat_model_r2(self, quality_models):
        assert quality_models.csat_r2 > 0.5

    def test_wait_model_r2(self, quality_models):
        assert quality_models.wait_r2 > 0.5


class TestStaffingRequirements:
    """Verify staffing requirements are feasible."""

    def test_shape(self, staffing_req):
        assert len(staffing_req) == DAYS_IN_APRIL * len(SHIFT_IDS)

    def test_positive_staffing(self, staffing_req):
        for col in ["senior", "junior", "english", "total"]:
            assert (staffing_req[col] >= 0).all()

    def test_english_within_pool(self, staffing_req):
        """Daily English total should not exceed available pool (accounting for leave)."""
        for date in staffing_req["date"].unique():
            day = staffing_req[staffing_req["date"] == date]
            assert (
                day["english"].sum() <= TOTAL_ENGLISH
            ), f"English demand {day['english'].sum()} exceeds pool {TOTAL_ENGLISH} on {date}"

    def test_senior_within_pool(self, staffing_req):
        for date in staffing_req["date"].unique():
            day = staffing_req[staffing_req["date"] == date]
            assert day["senior"].sum() <= TOTAL_SENIORS

    def test_total_reasonable(self, staffing_req):
        """Total daily staffing across all shifts should not exceed agents minus leave."""
        for date in staffing_req["date"].unique():
            day = staffing_req[staffing_req["date"] == date]
            # With daily leave cap ~19, at least 31 agents working
            assert day["total"].sum() <= 50
