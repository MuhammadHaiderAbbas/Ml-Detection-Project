"""Documented inference benchmark: latency, throughput and Python memory use.

Method: run ``predict_fn`` on fixed-size batches after warm-up runs, timing
each call with ``time.perf_counter``. Memory is the peak Python-heap
allocation measured by ``tracemalloc`` during one batch; native allocations
made inside compiled libraries are not fully captured, so treat it as a lower
bound. Results describe the machine they ran on and are not targets.
"""

from __future__ import annotations

import time
import tracemalloc
from typing import Any, Callable

import numpy as np
import pandas as pd


def benchmark_inference(
    predict_fn: Callable[[pd.DataFrame], Any],
    data: pd.DataFrame,
    *,
    batch_size: int = 1000,
    repeats: int = 5,
    warmup: int = 1,
) -> dict[str, Any]:
    if len(data) == 0:
        raise ValueError("benchmark requires at least one row")
    batch = data.iloc[: min(batch_size, len(data))]
    for _ in range(warmup):
        predict_fn(batch)
    timings = []
    errors = 0
    for _ in range(repeats):
        start = time.perf_counter()
        try:
            predict_fn(batch)
        except Exception:
            errors += 1
        timings.append(time.perf_counter() - start)
    tracemalloc.start()
    predict_fn(batch)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    t = np.asarray(timings)
    n = len(batch)
    return {
        "method": "perf_counter over repeated fixed batches; tracemalloc peak (Python heap only)",
        "batch_rows": n,
        "repeats": repeats,
        "warmup": warmup,
        "batch_latency_ms": {
            "mean": float(t.mean() * 1e3),
            "p50": float(np.percentile(t, 50) * 1e3),
            "p95": float(np.percentile(t, 95) * 1e3),
            "max": float(t.max() * 1e3),
        },
        "per_row_latency_us_mean": float(t.mean() / n * 1e6),
        "throughput_rows_per_s": float(n / t.mean()) if t.mean() > 0 else None,
        "peak_python_heap_mb": peak / 1024**2,
        "error_count": errors,
    }
