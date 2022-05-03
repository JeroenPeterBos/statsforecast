# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/models.ipynb (unless otherwise specified).

__all__ = ['ses', 'adida', 'historic_average', 'croston_classic', 'croston_sba', 'croston_optimized',
           'seasonal_window_average', 'seasonal_naive', 'imapa', 'naive', 'random_walk_with_drift', 'window_average',
           'seasonal_exponential_smoothing', 'tsb', 'auto_arima']

# Cell
from itertools import count
from numbers import Number
from typing import Collection, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from numba import njit
from scipy.optimize import minimize

from .arima import auto_arima_f, forecast_arima

# Internal Cell
@njit
def _ses_fcst_mse(x: np.ndarray, alpha: float) -> Tuple[float, float]:
    """Perform simple exponential smoothing on a series.

    This function returns the one step ahead prediction
    as well as the mean squared error of the fit.
    """
    smoothed = x[0]
    n = x.size
    mse = 0.

    for i in range(1, n):
        smoothed = (alpha * x[i - 1] + (1 - alpha) * smoothed).item()
        error = x[i] - smoothed
        mse += error * error

    mse /= n
    forecast = alpha * x[-1] + (1 - alpha) * smoothed
    return forecast, mse


def _ses_mse(alpha: float, x: np.ndarray) -> float:
    """Compute the mean squared error of a simple exponential smoothing fit."""
    _, mse = _ses_fcst_mse(x, alpha)
    return mse


@njit
def _ses_forecast(x: np.ndarray, alpha: float) -> float:
    """One step ahead forecast with simple exponential smoothing."""
    forecast, _ = _ses_fcst_mse(x, alpha)
    return forecast


@njit
def _demand(x: np.ndarray) -> np.ndarray:
    """Extract the positive elements of a vector."""
    return x[x > 0]


@njit
def _intervals(x: np.ndarray) -> np.ndarray:
    """Compute the intervals between non zero elements of a vector."""
    y = []

    ctr = 1
    for val in x:
        if val == 0:
            ctr += 1
        else:
            y.append(ctr)
            ctr = 1

    y = np.array(y)
    return y


@njit
def _probability(x: np.ndarray) -> np.ndarray:
    """Compute the element probabilities of being non zero."""
    return (x != 0).astype(np.int32)


def _optimized_ses_forecast(x: np.ndarray,
                            bounds: Sequence[Tuple[float, float]] = [(0.1, 0.3)]
                            ) -> float:
    """Searches for the optimal alpha and computes SES one step forecast."""
    alpha = minimize(
        fun=_ses_mse,
        x0=(0,),
        args=(x,),
        bounds=bounds,
        method='L-BFGS-B'
    ).x[0]
    forecast = _ses_forecast(x, alpha)
    return forecast


@njit
def _chunk_sums(array: np.ndarray, chunk_size: int) -> np.ndarray:
    """Splits an array into chunks and returns the sum of each chunk."""
    n = array.size
    n_chunks = n // chunk_size
    sums = np.empty(n_chunks)
    for i, start in enumerate(range(0, n, chunk_size)):
        sums[i] = array[start : start + chunk_size].sum()
    return sums

# Cell
@njit
def ses(X, h, future_xreg, alpha):
    y = X[:, 0] if X.ndim == 2 else X
    fcst, _ = _ses_fcst_mse(y, alpha)
    return np.full(h, fcst, np.float32)


def adida(X, h, future_xreg):
    y = X[:, 0] if X.ndim == 2 else X
    if (y == 0).all():
        return np.repeat(np.float32(0), h)
    y_intervals = _intervals(y)
    mean_interval = y_intervals.mean()
    aggregation_level = round(mean_interval)
    lost_remainder_data = len(y) % aggregation_level
    y_cut = y[lost_remainder_data:]
    aggregation_sums = _chunk_sums(y_cut, aggregation_level)
    sums_forecast = _optimized_ses_forecast(aggregation_sums)
    forecast = sums_forecast / aggregation_level
    return np.repeat(forecast, h)


@njit
def historic_average(X, h, future_xreg):
    y = X[:, 0] if X.ndim == 2 else X
    return np.repeat(y.mean(), h)


@njit
def croston_classic(X, h, future_xreg):
    y = X[:, 0] if X.ndim == 2 else X
    yd = _demand(y)
    yi = _intervals(y)
    ydp = _ses_forecast(yd, 0.1)
    yip = _ses_forecast(yi, 0.1)
    return ydp / yip


@njit
def croston_sba(X, h, future_xreg):
    y = X[:, 0] if X.ndim == 2 else X
    return 0.95 * croston_classic(y, h, future_xreg)


def croston_optimized(X, h, future_xreg):
    y = X[:, 0] if X.ndim == 2 else X
    yd = _demand(y)
    yi = _intervals(y)
    ydp = _optimized_ses_forecast(yd)
    yip = _optimized_ses_forecast(yi)
    return ydp / yip


@njit
def seasonal_window_average(
    X: np.ndarray,
    h: int,
    future_xreg,
    season_length: int,
    window_size: int,
) -> np.ndarray:
    y = X[:, 0] if X.ndim == 2 else X
    min_samples = season_length * window_size
    if y.size < min_samples:
        return np.full(h, np.nan, np.float32)
    season_avgs = np.zeros(season_length, np.float32)
    for i, value in enumerate(y[-min_samples:]):
        season = i % season_length
        season_avgs[season] += value / window_size
    out = np.empty(h, np.float32)
    for i in range(h):
        out[i] = season_avgs[i % season_length]
    return out


@njit
def seasonal_naive(X, h, future_xreg, season_length):
    return seasonal_window_average(X, h, future_xreg, season_length, 1)


def imapa(X, h, future_xreg):
    y = X[:, 0] if X.ndim == 2 else X
    if (y == 0).all():
        return np.repeat(np.float32(0), h)
    y_intervals = _intervals(y)
    mean_interval = y_intervals.mean().item()
    max_aggregation_level = round(mean_interval)
    forecasts = np.empty(max_aggregation_level, np.float32)
    for aggregation_level in range(1, max_aggregation_level + 1):
        lost_remainder_data = len(y) % aggregation_level
        y_cut = y[lost_remainder_data:]
        aggregation_sums = _chunk_sums(y_cut, aggregation_level)
        forecast = _optimized_ses_forecast(aggregation_sums)
        forecasts[aggregation_level - 1] = (forecast / aggregation_level)
    forecast = forecasts.mean()
    return np.repeat(forecast, h)


@njit
def naive(X, h, future_xreg):
    y = X[:, 0] if X.ndim == 2 else X
    return np.repeat(y[-1], h)


@njit
def random_walk_with_drift(X, h, future_xreg):
    y = X[:, 0] if X.ndim == 2 else X
    slope = (y[-1] - y[0]) / (y.size - 1)
    return slope * (1 + np.arange(h)) + y[-1]


@njit
def window_average(X, h, future_xreg, window_size):
    y = X[:, 0] if X.ndim == 2 else X
    if y.size < window_size:
        return np.full(h, np.nan, np.float32)
    wavg = y[-window_size:].mean()
    return np.repeat(wavg, h)


@njit
def seasonal_exponential_smoothing(X, h, future_xreg, season_length, alpha):
    y = X[:, 0] if X.ndim == 2 else X
    if y.size < season_length:
        return np.full(h, np.nan, np.float32)
    season_vals = np.empty(season_length, np.float32)
    for i in range(season_length):
        season_vals[i] = _ses_forecast(y[i::season_length], alpha)
    out = np.empty(h, np.float32)
    for i in range(h):
        out[i] = season_vals[i % season_length]
    return out


@njit
def tsb(X, h, future_xreg, alpha_d, alpha_p):
    y = X[:, 0] if X.ndim == 2 else X
    if (y == 0).all():
        return np.repeat(np.float32(0), h)
    yd = _demand(y)
    yp = _probability(y)
    ypf = _ses_forecast(yp, alpha_p)
    ydf = _ses_forecast(yd, alpha_d)
    forecast = np.float32(ypf * ydf)
    return np.repeat(forecast, h)

# Cell
def auto_arima(X: np.ndarray, h: int, future_xreg=None, season_length: int = 1,
               approximation: bool = False, level: Optional[Tuple[int]] = None) -> np.ndarray:
    y = X[:, 0] if X.ndim == 2 else X
    xreg = X[:, 1:] if (X.ndim == 2 and X.shape[1] > 1) else None
    mod = auto_arima_f(
        y,
        xreg=xreg,
        period=season_length,
        approximation=approximation,
        allowmean=False, allowdrift=False #not implemented yet
    )
    fcst = forecast_arima(mod, h, xreg=future_xreg, level=level)
    if level is None:
        return fcst['mean']
    return {
        'mean': fcst['mean'],
        **{f'lo-{l}': fcst['lower'][f'{l}%'] for l in reversed(level)},
        **{f'hi-{l}': fcst['upper'][f'{l}%'] for l in level},
    }