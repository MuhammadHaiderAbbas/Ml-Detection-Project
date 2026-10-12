"""Create a hash-verified, separate backup of the original research project."""

from __future__ import annotations

import json
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..provenance import sha256_file

MANIFEST_NAME = "BACKUP_MANIFEST.json"


class BackupError(Exception):
    pass


def create_backup(source: str | Path, destination: str | Path, *, read_only: bool = True) -> dict[str, Any]:
    """Copy ``source`` to a new ``destination`` and verify every file by SHA-256.

    The destination must not already exist, so an existing backup is never
    overwritten. The source is only read.
    """
    src = Path(source).resolve()
    dst = Path(destination).resolve()
    if not src.is_dir():
        raise BackupError(f"source folder not found: {src}")
    if dst.exists():
        raise BackupError(f"destination already exists, refusing to overwrite: {dst}")
    if dst == src or src in dst.parents:
        raise BackupError("destination must be outside the source folder")

    files = []
    dst.mkdir(parents=True)
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_symlink():
            files.append({"path": rel.as_posix(), "skipped": "symlink"})
            continue
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        before = sha256_file(path)
        shutil.copy2(path, target)
        after = sha256_file(target)
        if before != after:
            raise BackupError(f"hash mismatch after copying {rel}")
        files.append({"path": rel.as_posix(), "bytes": path.stat().st_size, "sha256": before})

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(src),
        "destination": str(dst),
        "file_count": sum(1 for f in files if "sha256" in f),
        "total_bytes": sum(f.get("bytes", 0) for f in files),
        "read_only": read_only,
        "files": files,
    }
    (dst / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if read_only:
        for f in files:
            if "sha256" in f:
                p = dst / f["path"]
                os.chmod(p, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    return manifest


def verify_backup(destination: str | Path) -> dict[str, Any]:
    """Re-hash every file listed in the backup manifest."""
    dst = Path(destination)
    manifest = json.loads((dst / MANIFEST_NAME).read_text(encoding="utf-8"))
    problems = []
    for f in manifest["files"]:
        if "sha256" not in f:
            continue
        p = dst / f["path"]
        if not p.is_file():
            problems.append({"path": f["path"], "problem": "missing"})
        elif sha256_file(p) != f["sha256"]:
            problems.append({"path": f["path"], "problem": "hash mismatch"})
    return {"verified_files": manifest["file_count"], "problems": problems, "ok": not problems}
