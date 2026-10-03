"""Pick the best model per country from a rolling backtest, and keep its residuals.

Selection rule: take the model with the lowest MAPE, then prefer the *simplest* model whose
MAPE is within ``MARGIN`` (relative) of it. Differences of a percent or two over ~10 days are
mostly noise, so a complicated model has to win clearly to be chosen.
"""
import numpy as np
import pandas as pd

from pipeline.models import HORIZON, MODELS

SIMPLICITY = ["seasonal_naive", "naive_avg3", "ensemble", "prophet_tuned", "prophet", "ets"]
MARGIN = 0.03
MIN_HISTORY_HOURS = 24 * 14
HOUR = pd.Timedelta(hours=1)


def complete_origins(series: pd.Series, n_origins: int, horizon: int = HORIZON) -> list:
    """Midnight-UTC origins whose full ``horizon`` of actuals is already known (oldest first)."""
    latest = (series.index[-1] - (horizon - 1) * HOUR).floor("D")
    return [latest - pd.Timedelta(days=i) for i in range(n_origins)][::-1]


def predict_origin(series, model_name, origin, country, horizon: int = HORIZON):
    """Forecast ``horizon`` hours from ``origin`` using only data before it. None if impossible."""
    train = series[series.index < origin]
    if len(train) < MIN_HISTORY_HOURS or train.index[-1] != origin - HOUR:
        return None
    pred = MODELS[model_name](train, horizon, country)
    pred = pred.assign(actual=series.reindex(pred.index).to_numpy(dtype=float))
    pred["origin"] = origin
    pred.index.name = "ds"
    return pred.reset_index()


def collect_predictions(series, names, country, n_origins: int, horizon: int = HORIZON):
    """Backtest predictions for every candidate. Returns (DataFrame, {model: failures})."""
    frames, failures = [], {name: 0 for name in names}
    for origin in complete_origins(series, n_origins, horizon):
        for name in names:
            try:
                pred = predict_origin(series, name, origin, country, horizon)
            except Exception:  # a single model failing must not stop the run
                failures[name] += 1
                continue
            if pred is not None:
                frames.append(pred.assign(model=name))
    if not frames:
        return pd.DataFrame(columns=["ds", "yhat", "actual", "origin", "model"]), failures
    return pd.concat(frames, ignore_index=True), failures


def score_table(preds: pd.DataFrame) -> pd.DataFrame:
    """MAPE / MAE per model over the backtest hours (rows with missing actuals are ignored)."""
    ok = preds.dropna(subset=["actual", "yhat"]).copy()
    ok["abs_err"] = (ok["actual"] - ok["yhat"]).abs()
    ok["ape"] = ok["abs_err"] / ok["actual"] * 100
    table = ok.groupby("model").agg(
        mape_pct=("ape", "mean"), mae_mw=("abs_err", "mean"), hours=("ape", "count")
    )
    # A model that could only be scored on a fraction of the hours is not comparable.
    return table[table["hours"] >= 0.8 * table["hours"].max()]


def select_champion(table: pd.DataFrame, margin: float = MARGIN) -> str:
    if table.empty:
        raise ValueError("no model could be scored")
    best = table["mape_pct"].min()
    for name in SIMPLICITY:
        if name in table.index and table.loc[name, "mape_pct"] <= best * (1 + margin):
            return name
    return table["mape_pct"].idxmin()  # model not in SIMPLICITY


def champion_residuals(series, champion, country, preds: pd.DataFrame, horizon: int = HORIZON):
    """Hourly (actual, yhat) of the champion on backtest days plus today's partial day."""
    res = preds[preds["model"] == champion][["ds", "actual", "yhat"]]
    today = series.index[-1].floor("D")
    if not (preds["origin"] == today).any():  # today's forecast is only partly observed
        try:
            part = predict_origin(series, champion, today, country, horizon)
        except Exception:
            part = None
        if part is not None:
            res = pd.concat([res, part[["ds", "actual", "yhat"]]], ignore_index=True)
    res = res.dropna(subset=["actual", "yhat"])
    return res.sort_values("ds").drop_duplicates("ds", keep="last").set_index("ds")
