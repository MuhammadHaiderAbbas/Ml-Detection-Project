"""Capture the hardware/software environment for experiment records."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

TRACKED_PACKAGES = ("numpy", "pandas", "scikit-learn", "scipy", "joblib", "imbalanced-learn", "shap", "river")


def _package_versions() -> dict[str, str | None]:
    out = {}
    for name in TRACKED_PACKAGES:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def _total_ram_gb() -> float | None:
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 1)
    except (AttributeError, ValueError, OSError):
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
            return round(stat.ullTotalPhys / 1024**3, 1)
        except Exception:
            return None
    return None


def _gpu() -> dict[str, Any]:
    """GPU is optional; absence is recorded, never an error."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {"available": False, "detail": "nvidia-smi not found"}
    try:
        res = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        return {"available": bool(lines), "devices": lines}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "detail": f"nvidia-smi failed: {exc}"}


def _git_commit(repo_dir: Path) -> str | None:
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        res = subprocess.run(
            [exe, "-C", str(repo_dir), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
        )
        commit = res.stdout.strip() or None
        if commit:
            dirty = subprocess.run(
                [exe, "-C", str(repo_dir), "status", "--porcelain"], capture_output=True, text=True, timeout=10, check=False
            ).stdout.strip()
            return commit + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def capture_environment() -> dict[str, Any]:
    from .. import __version__

    return {
        "adaptive_ids_version": __version__,
        "code_commit": _git_commit(Path(__file__).resolve().parents[3]),
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
        "total_ram_gb": _total_ram_gb(),
        "gpu": _gpu(),
        "packages": _package_versions(),
    }
