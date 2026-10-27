# Forecasting method and findings

How the GridSense forecast, anomaly check and track record work, what was tried, and what the numbers do and do not show. The code lives in [`pipeline/`](../pipeline).

## 1. Data flow

```
GitHub Actions (every 3 h, on pushes to pipeline/**, or manually)
  python -m pipeline.run
    ENTSO-E actual load (A65 / A16)  ─┐
    ENTSO-E TSO day-ahead (A65 / A01) ├─> per country: backtest -> champion model -> forecast,
    Open-Meteo temperature           ─┘   interval, anomalies, track record
  -> forecast.json (schema_version 1) -> asset of the `forecast-data` GitHub release
Backend (Render): downloads it, caches it 10 min, serves /forecast, /anomaly, /trackrecord
```

If a country fails in a run (provider down, no data) its previous entry is carried over and flagged `carried_over`; if every country fails nothing is published, so the last good file stays.

## 2. Data

- **Load**: about 90 days of ENTSO-E actual total load, requested in 30-day chunks, resampled to hourly means. Zero values (a glitch for a national load) are dropped, gaps of up to 3 hours are interpolated, longer gaps stay empty.
- **Temperature**: population-weighted mean of the hourly 2 m temperature of five cities per country (weights are rough metro populations). Two Open-Meteo sources are combined: the Historical Weather API (ERA5 reanalysis, gap-free, about 5 days behind) for the long history and the Forecast API for the last 14 days and the next 3. The reanalysis wins where both have a value. The Forecast API alone is not enough: asked for 90 past days it returned nulls for about 50 of them (seen on 21 October 2026), which made every temperature model refuse to run.
- **Holidays**: national public holidays from the `holidays` package. A Monday to Friday holiday behaves like a Sunday; a holiday on a Saturday stays a Saturday.
- **TSO forecast**: the operators' own day-ahead total-load forecast from ENTSO-E, used only for the track record.

## 3. Candidate models

All models forecast the next 24 hours from the last observed hour. Seasonal references use the local wall clock, so a clock change does not shift them by an hour.

| Model | Idea | Temperature |
| ----- | ---- | ----------- |
| `seasonal_naive` | Same local hour one week ago (baseline) | no |
| `naive_avg3` | Mean of the same hour 1, 2 and 3 weeks ago | no |
| `naive_daytype` | Like `naive_avg3`, but comparable days only: a holiday is predicted from past Sundays and holidays, a holiday in a reference week is skipped | no |
| `naive_level` | `naive_daytype` scaled by how the last 7 days compare with their references (clipped to ±10 %) | no |
| `naive_level_hourly` | Same with one scale factor per hour of the day | no |
| `naive_recent` | Mean of the last 5 weekdays (3 Saturdays or Sundays/holidays) at the same hour | no |
| `prophet_tuned` | Prophet with separate daily curves for workdays and off-days, stiff trend | no |
| `prophet_temp` | `prophet_tuned` on the last 8 weeks plus heating and cooling degree days | yes |
| `ridge_temp` | Weighted ridge regression: hour × day type, temperature terms per part of the day, trend; recent hours count more | yes |
| `ensemble`, `ensemble_temp`, `ensemble_ridge` | Equal-weight averages (Prophet + 3-week mean, Prophet-temp + level model, ridge + recent days) | partly |
| `naive_level_adj`, `ridge_temp_adj`, `prophet_temp_adj`, `ensemble_temp_adj` | A base model scaled by its own error over the last 24 known hours (60 % of it, clipped to ±8 %) | partly |

Plain `prophet` and Holt-Winters (`ets`) exist for research (`pipeline/models.py`) but never won and are not candidates.

## 4. Choosing the model

1. Rolling backtest: for each of the last 10 days, every candidate forecasts 24 hours from midnight UTC using only earlier data. Ensembles and error-corrected variants reuse the forecasts of their components instead of fitting Prophet again.
2. Score each model by mean absolute percentage error (MAPE). Models scored on too few hours (they failed on many days) are dropped.
3. **Simplicity rule**: take the model with the lowest MAPE, then choose the *simplest* model whose MAPE is within 3 % of it (order: baseline, naive family, ensembles, regression, Prophet). Differences of a few percent over ten days are mostly noise, so a complicated model has to win clearly.
4. A model that cannot run (for example a temperature model when no weather is available) is excluded for that run; the others still compete.

The 80 % interval comes from the champion's backtest errors: the 10th and 90th percentile of its relative error, applied to the forecast. Plain Prophet intervals covered only 58-82 % in tests, so they are not used.

## 5. Anomaly detection

A plain z-score on the load itself flags nothing on a smooth daily curve. Instead, the champion's forecast for each of the last 24 hours is compared with what happened:

- Forecast errors are correlated within a day (a cold snap moves every hour). So each hour is compared with the *rolling median of the errors around it* (25 hours), and only the part on top of that level counts. The level itself is reported as `window_level_pct`.
- "Unusual" is judged against the same centred errors of the previous days: scale = 95th percentile of their size divided by 1.96 (the standard deviation for normal errors, but honest about heavy tails and tolerant of a few old outliers). Hours above 3.5 times the scale are flagged HIGH or LOW.
- On pure noise this gave zero false alarms in 12 of 12 simulated runs; an injected 3-hour spike on top of a 6 % drift was flagged and the drift was not.
- If the pipeline output is older than 12 hours (or a country was carried over) the backend falls back to a live z-score on the cached load.

## 6. Track record

For each of the last 14 complete days D, the current champion forecasts the 24 hours of D using only data up to 10:00 UTC the day before. The same is done for the seasonal-naive baseline. Both are compared with the realised load and with the TSO's published day-ahead forecast **on exactly the same hours**. A test checks that the forecast does not change when the data from the forecast origin onwards is altered.

How to read it: it is a walk-forward evaluation, not an archive of forecasts GridSense published at the time. The champion was selected on recent days that overlap the window (mildly flattering). Measured temperatures stand in for temperature forecasts (flattering to temperature models). TSOs publish at different times, so the information cut-off is similar, not identical.

## 7. What was tried and what we learned

All numbers are average absolute percentage errors on real ENTSO-E data, autumn 2026, 4 countries; treat them as one season's evidence.

- Default Prophet (3.3-5.5 %) and ETS (4.2-8.5 %) lost to simply copying last week (1.5-3.2 %). Autumn load drifts, and a model that averages 56 days of history lags it.
- **Level adjustment** (`naive_level`) was the first big win (12-23 % better than last week in three countries) because the load was moving.
- Holiday-aware references matter only on holidays; the test window had few weekday holidays, so the benefit is logical but weakly measured.
- **Temperature** helped modestly, mostly in Germany and France. Regression on calendar and temperature (`ridge_temp`) beat Prophet with temperature in Spain.
- **Error correction** removed most of the low bias in France and Poland (France: 3.7 % to 2.5 %) but added a little noise in Germany, where the level was already stable. Hence it is a candidate, not a default.
- Averaging the last few same-type days (`naive_recent`) did not help overall.
- Against the TSOs: GridSense is ahead in Germany over two weeks, and behind in France (about 1.3 points), Spain (about 1.7) and Poland (about 0.7). The gap is every day, not a few bad days; the TSOs' own weather forecasts and richer data are the likely reason.

## 8. Known limitations

- Nationwide load only, four countries, hourly, 24 h ahead.
- No regional holidays or bridge days; some TSOs know them, GridSense does not.
- Coarse temperature (five cities); no wind, cloud or solar information.
- Tests use measured temperatures; no archived weather forecasts yet.
- Only about 90 days of history are used, so there is no yearly seasonality.

## 9. Tools

```bash
python -m pipeline.run [--synthetic] [--countries ...] [--candidates ...] [--no-weather] [--no-tso]
python -m pipeline.backtest      # rolling-origin backtest of all candidates (research)
python -m pipeline.compare       # every candidate against the TSO, day-ahead, per country
python -m pipeline.diagnose      # last hours next to the three reference weeks
python -m pytest pipeline        # tests (no network, no API key)
```

`forecast.json` (per country): `model`, `model_label`, `data_until`, `inputs`, `backtest` (MAPE of every candidate), `interval`, `predictions` (UTC `ds`, `yhat`, `yhat_lower`, `yhat_upper`), `anomalies`, `track_record`.
