"""Backup and recovery of the application's own data (spec §17).

A backup is a folder ``<dest>/adaptive-ids-backup-<UTC timestamp>/`` with:

* ``database.sqlite`` (SQLite online-backup API, consistent while the app runs) or
  ``database.dump`` (PostgreSQL ``pg_dump --format=custom``);
* ``storage/`` - stored uploads; ``runs/`` - experiment runs incl. model artifacts;
  ``configs/`` - schemas, protocol, retention and severity rules;
* ``manifest.json`` - SHA-256 and size of every file, the schema revision and app version.

``verify`` recomputes every hash. ``restore`` verifies first, refuses to overwrite
anything unless ``force`` is given, restores into the configured locations, and then
re-checks every approved or active model artifact (``governance.verify_restorable``).

Backups contain the same sensitive data as the live system: keep them on encrypted,
access-controlled storage and never in a public repository.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess  # pg_dump/pg_restore by absolute path, argument list, no shell  # nosec B404
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from .. import __version__
from ..db import make_engine, make_session_factory, session_scope
from ..provenance import sha256_file
from ..settings import Settings

MANIFEST = "manifest.json"
FORMAT_VERSION = 1


class BackupError(RuntimeError):
    pass


def _db_kind(url: str) -> str:
    if url.startswith("sqlite"):
        return "sqlite"
    if url.startswith("postgresql"):
        return "postgresql"
    raise BackupError(f"unsupported database for backup: {make_url(url).drivername}")


def _sqlite_path(url: str) -> Path:
    db = make_url(url).database
    if not db or db == ":memory:":
        raise BackupError("in-memory SQLite databases cannot be backed up")
    return Path(db)


def _pg_env_args(url: str) -> tuple[dict[str, str], list[str]]:
    u = make_url(url)
    env = {**os.environ}
    if u.password:
        env["PGPASSWORD"] = str(u.password)  # via the environment, never on the command line
    args = ["--host", u.host or "localhost", "--port", str(u.port or 5432), "--username", u.username or "postgres",
            "--dbname", u.database or ""]
    return env, args


def _schema_revision(url: str) -> str | None:
    engine = make_engine(url)
    try:
        with engine.connect() as c:
            return c.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001 - a missing table just means "unknown"
        return None
    finally:
        engine.dispose()


def _copy_tree(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=False)


def create(settings: Settings, dest: str | Path, *, configs_dir: str | Path = "configs") -> Path:
    kind = _db_kind(settings.database_url)
    out = Path(dest) / f"adaptive-ids-backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    if out.exists():
        raise BackupError(f"{out} already exists")
    out.mkdir(parents=True)
    try:
        if kind == "sqlite":
            src = sqlite3.connect(_sqlite_path(settings.database_url))
            dst = sqlite3.connect(out / "database.sqlite")
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
        else:
            exe = shutil.which("pg_dump")
            if not exe:
                raise BackupError("pg_dump not found on PATH; install the PostgreSQL client tools")
            env, args = _pg_env_args(settings.database_url)
            cmd = [exe, "--format=custom", "--no-owner", "--file", str(out / "database.dump"), *args]
            # absolute path, argument list, no shell; the password travels in the environment
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)  # nosec B603
            if r.returncode != 0:
                raise BackupError(f"pg_dump failed: {r.stderr.strip()[:500]}")
        _copy_tree(Path(settings.storage_dir), out / "storage")
        _copy_tree(Path(settings.runs_dir), out / "runs")
        _copy_tree(Path(configs_dir), out / "configs")
        files = sorted(p for p in out.rglob("*") if p.is_file())
        manifest = {
            "format_version": FORMAT_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
            "app_version": __version__, "database": kind, "schema_revision": _schema_revision(settings.database_url),
            "files": [{"path": p.relative_to(out).as_posix(), "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in files],
        }
        (out / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except Exception:
        shutil.rmtree(out, ignore_errors=True)  # never leave a half-written backup that looks complete
        raise
    return out


def verify(backup_dir: str | Path) -> dict[str, Any]:
    root = Path(backup_dir)
    try:
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError(f"no readable manifest in {root}: {exc}") from exc
    problems: list[str] = []
    listed = set()
    for f in manifest["files"]:
        p = root / f["path"]
        listed.add(f["path"])
        if not p.is_file():
            problems.append(f"missing: {f['path']}")
        elif p.stat().st_size != f["bytes"] or sha256_file(p) != f["sha256"]:
            problems.append(f"changed: {f['path']}")
    extra = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    problems += [f"not in manifest: {e}" for e in extra if e not in listed and e != MANIFEST]
    return {"ok": not problems, "problems": problems, "files": len(manifest["files"]), "database": manifest["database"],
            "schema_revision": manifest.get("schema_revision"), "created_at": manifest["created_at"]}


def _restore_dir(src: Path, dst: Path, force: bool) -> None:
    if not src.is_dir():
        return
    if dst.exists() and any(dst.iterdir()):
        if not force:
            raise BackupError(f"{dst} is not empty; pass --force to replace it")
        shutil.rmtree(dst)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def restore(settings: Settings, backup_dir: str | Path, *, force: bool = False) -> dict[str, Any]:
    root = Path(backup_dir)
    check = verify(root)
    if not check["ok"]:
        raise BackupError("backup failed verification, nothing was restored: " + "; ".join(check["problems"][:5]))
    kind = _db_kind(settings.database_url)
    if kind != check["database"]:
        raise BackupError(f"backup holds a {check['database']} database but the target is {kind}")
    if kind == "sqlite":
        target = _sqlite_path(settings.database_url)
        if target.exists() and not force:
            raise BackupError(f"{target.name} already exists; pass --force to replace it")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".restoring")
        shutil.copyfile(root / "database.sqlite", tmp)
        os.replace(tmp, target)
    else:
        if not force:
            raise BackupError("restoring PostgreSQL replaces the current database contents; pass --force")
        exe = shutil.which("pg_restore")
        if not exe:
            raise BackupError("pg_restore not found on PATH; install the PostgreSQL client tools")
        env, args = _pg_env_args(settings.database_url)
        cmd = [exe, "--clean", "--if-exists", "--no-owner", "--single-transaction", *args, str(root / "database.dump")]
        # absolute path, argument list, no shell; the password travels in the environment
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)  # nosec B603
        if r.returncode != 0:
            raise BackupError(f"pg_restore failed: {r.stderr.strip()[:500]}")
    _restore_dir(root / "storage", Path(settings.storage_dir), force)
    _restore_dir(root / "runs", Path(settings.runs_dir), force)
    return {"restored_from": root.name, "schema_revision": check["schema_revision"], "models": check_models(settings)}


def check_models(settings: Settings) -> list[dict[str, Any]]:
    """Re-verify every approved, active or archived model after a restore."""
    from ..db.models import ModelVersion
    from . import governance

    engine = make_engine(settings.database_url)
    out = []
    try:
        with session_scope(make_session_factory(engine)) as db:
            for mv in db.scalars(select(ModelVersion).where(ModelVersion.status.in_(("approved", "active", "archived")))):
                r = governance.verify_restorable(mv)
                out.append({"version_id": mv.version_id, "status": mv.status, "ok": r["ok"], "partial": r["partial"],
                            "failed": [c["detail"] for c in r["checks"] if c["passed"] is False]})
    finally:
        engine.dispose()
    return out
