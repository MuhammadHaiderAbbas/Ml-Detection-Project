"""Distribution-comparison statistics for drift detection."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from .config import DriftConfig

EPS = 1e-4


def quantile_edges(reference: np.ndarray, n_bins: int) -> np.ndarray:
    """Interior bin edges from reference quantiles (duplicates collapsed for discrete features)."""
    qs = np.quantile(reference, np.linspace(0, 1, n_bins + 1)[1:-1])
    return np.unique(qs)


def binned_proportions(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Proportions per bin: (-inf, e0], (e0, e1], ..., (e_k, inf)."""
    idx = np.searchsorted(edges, values, side="left")
    counts = np.bincount(idx, minlength=len(edges) + 1).astype(float)
    return counts / max(counts.sum(), 1.0)


def psi(ref_props: np.ndarray, cur_props: np.ndarray) -> float:
    """Population stability index with epsilon smoothing for empty bins."""
    r = np.clip(ref_props, EPS, None)
    c = np.clip(cur_props, EPS, None)
    r, c = r / r.sum(), c / c.sum()
    return float(np.sum((c - r) * np.log(c / r)))


def classify(effect: float | None, p_adj: float | None, n_ref: int, n_cur: int, cfg: DriftConfig) -> str:
    if n_ref < cfg.min_window_events or n_cur < cfg.min_window_events or effect is None:
        return "insufficient_data"
    significant = p_adj is not None and p_adj < cfg.alpha
    if significant and effect >= cfg.psi_major:
        return "major"
    if significant and effect >= cfg.psi_moderate:
        return "moderate"
    return "none"


def numeric_drift(reference: pd.Series, current: pd.Series, cfg: DriftConfig, *, keep_bins: bool = False) -> dict[str, Any]:
    ref = reference.to_numpy(dtype="float64")
    cur = current.to_numpy(dtype="float64")
    ref_ok, cur_ok = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    out: dict[str, Any] = {
        "n_ref": int(ref_ok.size), "n_cur": int(cur_ok.size),
        "n_missing_ref": int(ref.size - ref_ok.size), "n_missing_cur": int(cur.size - cur_ok.size),
    }
    if ref_ok.size == 0 or cur_ok.size == 0:
        out.update(psi=None, ks_d=None, ks_p=None)
        return out
    edges = quantile_edges(ref_ok, cfg.psi_bins)
    rp, cp = binned_proportions(ref_ok, edges), binned_proportions(cur_ok, edges)
    ks = stats.ks_2samp(ref_ok, cur_ok, method="asymp")
    out.update(
        psi=psi(rp, cp), ks_d=float(ks.statistic), ks_p=float(ks.pvalue),
        ref_mean=float(ref_ok.mean()), cur_mean=float(cur_ok.mean()),
        ref_median=float(np.median(ref_ok)), cur_median=float(np.median(cur_ok)),
    )
    if keep_bins:
        out["bins"] = {"edges": edges.tolist(), "ref": rp.tolist(), "cur": cp.tolist()}
    return out


def categorical_drift(reference: Sequence[Any], current: Sequence[Any], cfg: DriftConfig) -> dict[str, Any]:
    ref = pd.Series(reference, dtype=object).dropna().astype(str)
    cur = pd.Series(current, dtype=object).dropna().astype(str)
    cats = sorted(set(ref) | set(cur))
    rc = ref.value_counts().reindex(cats, fill_value=0).to_numpy(dtype=float)
    cc = cur.value_counts().reindex(cats, fill_value=0).to_numpy(dtype=float)
    out: dict[str, Any] = {"n_ref": int(rc.sum()), "n_cur": int(cc.sum()), "categories": cats}
    if rc.sum() == 0 or cc.sum() == 0:
        out.update(psi=None, chi2_p=None, js_distance=None)
        return out
    rp, cp = rc / rc.sum(), cc / cc.sum()
    table = np.vstack([rc, cc])
    table = table[:, table.sum(axis=0) > 0]
    chi2_p = float(stats.chi2_contingency(table)[1]) if table.shape[1] > 1 else 1.0
    from scipy.spatial.distance import jensenshannon

    out.update(psi=psi(rp, cp), chi2_p=chi2_p, js_distance=float(jensenshannon(rp, cp, base=2)),
               ref_props=rp.tolist(), cur_props=cp.tolist())
    return out


def bonferroni(pvalues: list[float | None]) -> list[float | None]:
    m = sum(p is not None for p in pvalues) or 1
    return [None if p is None else min(1.0, p * m) for p in pvalues]
