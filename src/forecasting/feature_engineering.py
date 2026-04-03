"""Feature engineering for demand forecasting."""

import numpy as np
import pandas as pd


def add_time_features(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Add temporal features for forecasting.

    Operates on a DataFrame that has a date column and a shift column.
    """
    df = df.copy()
    dt = df[date_col]

    df["day_of_week"] = dt.dt.dayofweek  # 0=Mon, 6=Sun
    df["day_of_month"] = dt.dt.day
    df["week_of_month"] = (dt.dt.day - 1) // 7 + 1
    df["is_weekend"] = (dt.dt.dayofweek >= 5).astype(int)

    # Beginning and end of month flags
    df["is_month_start"] = (dt.dt.day <= 5).astype(int)
    df["is_month_end"] = (dt.dt.day >= 26).astype(int)

    # Cyclical encoding for day of week
    df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)

    # Cyclical encoding for day of month
    df["dom_sin"] = np.sin(2 * np.pi * df["day_of_month"] / 31)
    df["dom_cos"] = np.cos(2 * np.pi * df["day_of_month"] / 31)

    # Month cyclical (useful for training data spanning multiple months)
    month = dt.dt.month
    df["month_sin"] = np.sin(2 * np.pi * month / 12)
    df["month_cos"] = np.cos(2 * np.pi * month / 12)

    return df


FEATURE_COLUMNS = [
    "shift",
    "day_of_week",
    "day_of_month",
    "week_of_month",
    "is_weekend",
    "is_month_start",
    "is_month_end",
    "dow_sin",
    "dow_cos",
    "dom_sin",
    "dom_cos",
    "month_sin",
    "month_cos",
]
