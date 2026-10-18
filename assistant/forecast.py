"""Small, auditable count forecasts with chronological selection and evaluation.

No claim of weather-aware building risk or future coverage guarantees is made.
"""
from datetime import timedelta
import math

import numpy as np

METHODS = ('last_week', 'weekday_4w', 'weekday_8w_trend')


def predict(values, horizon, method):
    y = np.asarray(values, dtype=float)
    if len(y) < 70 or not np.isfinite(y).all() or (y < 0).any():
        raise ValueError('At least 70 consecutive, finite daily counts are required')
    output = []
    for h in range(1, horizon + 1):
        # Calendar weekday relative to the end of the observed sequence.
        offsets = [h - 7*k for k in range(1, 11) if h - 7*k <= 0]
        idx = [len(y)-1+offset for offset in offsets if len(y)-1+offset >= 0]
        if method == 'last_week':
            estimate = y[idx[0]]
        elif method == 'weekday_4w':
            estimate = np.mean(y[idx[:4]])
        elif method == 'weekday_8w_trend':
            scale = np.clip((np.mean(y[-7:])+1)/(np.mean(y[-35:-7])+1), .5, 2)
            estimate = np.mean(y[idx[:8]]) * scale
        else:
            raise ValueError('Unknown count forecast method')
        output.append(float(max(0, estimate)))
    return np.asarray(output)


def forecast(dates, values, targets):
    """History -> selection -> interval calibration -> retrospective test, in order."""
    y = np.asarray(values, dtype=float)
    if len(y) < 300 or len(dates) != len(y):
        raise ValueError('Need 300 consecutive days to evaluate a count forecast')
    if any(b-a != timedelta(days=1) for a,b in zip(dates, dates[1:])):
        raise ValueError('Forecast input dates must be consecutive')
    horizon = (targets[-1] - dates[-1]).days
    if not 1 <= horizon <= 14:
        raise ValueError('Forecast is unavailable: data gap plus horizon exceeds 14 days')
    # Every origin's outcomes finish before the next phase starts.
    n = len(y)
    test_start = n-30-horizon
    calibration_start = test_start-90-horizon
    selection_start = calibration_start-45-horizon
    if selection_start < 70:
        raise ValueError('Insufficient nonoverlapping backtest history')
    origins = range(selection_start, selection_start+45)
    losses = {}
    for method in METHODS:
        losses[method] = float(np.mean([
            np.mean(np.abs(predict(y[:i], horizon, method)-y[i:i+horizon]))
            for i in origins]))
    chosen = min(METHODS, key=lambda m: losses[m])
    residuals=[]
    for i in range(calibration_start, calibration_start+90):
        p=predict(y[:i],horizon,chosen)
        # Scale errors to complaint volume so summer calibration does not give
        # deceptively tight absolute ranges when the heating season starts.
        scale=np.maximum(10,np.maximum(p,np.mean(y[i-14:i])))
        residuals.append(np.abs(p-y[i:i+horizon])/scale)
    residuals=np.asarray(residuals)
    # Finite-sample absolute-residual radius for a nominal 80% interval.
    quantile = min(1, math.ceil((len(residuals)+1)*.8)/len(residuals))
    ratios = np.quantile(residuals, quantile, axis=0, method='higher')
    evaluations = []
    baseline_errors = []
    for i in range(test_start, test_start+30):
        p = predict(y[:i], horizon, chosen)
        radii=ratios*np.maximum(10,np.maximum(p,np.mean(y[i-14:i])))
        actual = y[i:i+horizon]
        evaluations.append((np.abs(p-actual), (actual >= np.maximum(0,p-radii)) & (actual <= p+radii)))
        baseline_errors.append(np.abs(predict(y[:i], horizon, 'last_week')-actual))
    point = predict(y, horizon, chosen)
    radii=ratios*np.maximum(10,np.maximum(point,np.mean(y[-14:])))
    errors = np.array([r[0] for r in evaluations])
    coverage = np.array([r[1] for r in evaluations])
    rows = []
    for day in targets:
        j = (day-dates[-1]).days-1
        if j < 0:
            raise ValueError('Forecast target must follow input cutoff')
        rows.append({'day':day.isoformat(), 'expected':round(float(point[j]),1),
                     'lower':int(max(0,math.floor(point[j]-radii[j]))),
                     'upper':int(math.ceil(point[j]+radii[j])),
                     'backtest_mae':round(float(errors[:,j].mean()),1),
                     'backtest_coverage':round(float(coverage[:,j].mean()),3)})
    observed_coverage=float(np.mean([r['backtest_coverage'] for r in rows]))
    return {'method':chosen,'rows':rows,'nominal_interval':.8,
            'quality': 'experimental_low_coverage' if observed_coverage < .7 else 'experimental_backtested',
            'test_interval_coverage':round(observed_coverage,3),
            'selection_mae':{k:round(v,1) for k,v in losses.items()},
            'test_origins':30,'calibration_origins':90,
            'test_first_origin':dates[test_start-1].isoformat(),
            'test_last_origin':dates[test_start+28].isoformat(),
            'baseline_test_mae':round(float(np.mean(baseline_errors)),1),
            'model_test_mae':round(float(errors.mean()),1),
            'note':'Experimental count forecast, without weather covariates. Nominal 80% marginal intervals; historical coverage is reported, not a guarantee. Overlapping test windows are correlated. Do not sum daily interval bounds as a joint interval.'}
