"""ADWIN change detection on bounded event streams (River implementation).

ADWIN assumes a stream of independent observations bounded in a known range;
it is applied here only to 0/1 indicators (suspicious prediction, prediction
error) taken in event-time order. Values outside [0, 1] are rejected rather
than silently clipped.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np


def adwin_changes(values: Sequence[float], delta: float, *, max_events: int = 50) -> list[dict[str, Any]]:
    from river import drift

    arr = np.asarray(values, dtype="float64")
    if arr.size and (not np.isfinite(arr).all() or arr.min() < 0 or arr.max() > 1):
        raise ValueError("ADWIN is only applied to bounded signals in [0, 1]")
    detector = drift.ADWIN(delta=delta)
    changes: list[dict[str, Any]] = []
    last = 0
    for i, v in enumerate(arr):
        detector.update(float(v))
        if detector.drift_detected:
            # ADWIN keeps only the post-change sub-window; its width (bucket-granular, so approximate)
            # locates where the change began.
            kept = int(detector.width)
            split = max(last, i + 1 - kept)
            before = float(arr[last:split].mean()) if split > last else None
            after = float(arr[split:i + 1].mean()) if i + 1 > split else None
            changes.append({
                "position": i, "approx_change_start": split, "mean_before": before, "mean_after": after,
                "direction": None if before is None or after is None else ("increase" if after > before else "decrease"),
            })
            last = split
            if len(changes) >= max_events:
                break
    return changes
