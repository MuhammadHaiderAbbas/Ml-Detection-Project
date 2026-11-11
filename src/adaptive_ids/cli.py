"""Command-line entry point: ``adaptive-ids <command>`` (or ``python -m adaptive_ids``)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .provenance import sha256_file


def _cmd_inventory(a: argparse.Namespace) -> int:
    from .research import build_inventory, render_inventory_markdown

    limit = None if a.hash_max_mb is None else int(a.hash_max_mb * 1024**2)
    inv = build_inventory(a.project_dir, hash_max_bytes=limit)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(json.dumps(inv, indent=2), encoding="utf-8")
    (out / "inventory.md").write_text(render_inventory_markdown(inv), encoding="utf-8")
    print(f"Inventoried {len(inv['files'])} files -> {out / 'inventory.md'}")
    print(f"Counts: {inv['counts_by_category']}")
    return 0


def _cmd_backup(a: argparse.Namespace) -> int:
    from .research import create_backup, verify_backup

    if a.verify:
        res = verify_backup(a.destination)
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    if not a.source:
        print("error: --source is required to create a backup", file=sys.stderr)
        return 2
    m = create_backup(a.source, a.destination, read_only=not a.writable)
    print(f"Backed up {m['file_count']} files ({m['total_bytes'] / 1024**2:.1f} MB) to {m['destination']}; all hashes verified.")
    return 0


def _cmd_hash(a: argparse.Namespace) -> int:
    for p in a.files:
        print(f"{sha256_file(p)}  {p}")
    return 0


def _cmd_synthetic(a: argparse.Namespace) -> int:
    from .research import write_synthetic_dataset

    meta = write_synthetic_dataset(
        a.out, n_rows=a.rows, seed=a.seed, drift_after_fraction=a.drift_after,
    )
    print(f"Wrote {meta['rows']} SYNTHETIC rows to {a.out} (sha256 {meta['sha256']})")
    return 0


def _cmd_preview(a: argparse.Namespace) -> int:
    from .ingestion import preview_csv
    from .schema import FeatureSchema

    mapping = json.loads(Path(a.mapping).read_text(encoding="utf-8")) if a.mapping else None
    res = preview_csv(a.csv, FeatureSchema.load(a.schema), column_mapping=mapping, n_rows=a.rows)
    print(json.dumps(res["compatibility"], indent=2))
    for row in res["rows"]:
        print(row)
    return 0 if not res["compatibility"]["missing"] else 1


def _cmd_run(a: argparse.Namespace) -> int:
    from .experiments import run_experiment

    res = run_experiment(a.config)
    test = res["metrics"]["test"]
    print(f"[{res['provenance_banner']}]")
    print(f"Run directory: {res['run_dir']}")
    if test:
        print(f"Test accuracy {test['accuracy']:.4f}; macro F1 {test['averages']['macro']['f1']:.4f}")
    for w in res["warnings"]:
        print(f"warning: {w}")
    return 0


def _settings():
    from .settings import Settings

    return Settings.from_env()


def _cmd_db_upgrade(a: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    if not ini.is_file():
        print(f"error: alembic.ini not found at {ini}; run from a source checkout", file=sys.stderr)
        return 2
    cfg = Config(str(ini))
    cfg.attributes["database_url"] = _settings().database_url
    command.upgrade(cfg, a.revision)
    print(f"Database upgraded to {a.revision}.")
    return 0


def _cmd_create_user(a: argparse.Namespace) -> int:
    import getpass
    import os

    from .db import make_engine, make_session_factory, session_scope
    from .services import auth
    from .services.errors import ServiceError

    password = os.environ.get("ADAPTIVE_IDS_NEW_USER_PASSWORD") or getpass.getpass("Password (min 12 chars): ")
    factory = make_session_factory(make_engine(_settings().database_url))
    try:
        with session_scope(factory) as db:
            u = auth.create_user(db, a.username, password, a.role)
            print(f"Created {u.role} '{u.username}' (id {u.id}).")
    except ServiceError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    return 0


def _cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    # Client addresses (audit log, sign-in throttling) come from X-Forwarded-For only when the request
    # arrives from a trusted proxy address; the default trusts nothing but this machine.
    uvicorn.run("adaptive_ids.api.app:create_app", factory=True, host=a.host, port=a.port, reload=a.reload,
                proxy_headers=True, forwarded_allow_ips=a.forwarded_allow_ips, server_header=False)
    return 0


def _cmd_drift_experiment(a: argparse.Namespace) -> int:
    from .drift.experiment import run_experiment

    res = run_experiment(a.modes, repeats=a.repeats, seed=a.seed, out_dir=a.out, window_size=a.window_size)
    print(f"[{res['banner']}]")
    for mode, dets in res["aggregate"].items():
        parts = [f"{name}: rate={v['detection_rate']} delay={v['mean_delay_events']} false_alarms={v['false_alarms_total']}"
                 for name, v in dets.items() if name != "mean_us_per_event"]
        print(f"{mode}: " + " | ".join(parts))
    print(f"Report: {res['run_dir']}/report.md")
    return 0


def _cmd_msc_reproduce(a: argparse.Namespace) -> int:
    from .research.msc_reproduction import run_reproduction

    res = run_reproduction(a.test, a.train, a.out)
    print("[baseline_reproduction - retrained; the notebook's .pkl artifacts were not provided]")
    for row in res["comparison_with_reported"]:
        print(f"{row['model']:<14} {row['metric']:<10} reported={row['reported']} reproduced={row['reproduced']} diff={row['difference']}")
    for v, d in res["variants"].items():
        print(f"{v}: " + " | ".join(f"{m} acc={x['accuracy']:.4f} recall={x['recall']:.4f} fpr={x['false_positive_rate']:.4f}"
                                    for m, x in d["models"].items()))
    print(f"Result: {res['run_dir']}/result.json")
    return 0


def _cmd_prepare_nsl_kdd(a: argparse.Namespace) -> int:
    from .research.msc_reproduction import prepare_named_csv

    info = prepare_named_csv(a.src, a.dest)
    print(f"Wrote {info['rows']} rows to {info['dest']} (schema configs/schemas/nsl-kdd.json; "
          "row_order_time is synthetic ordering, not real time)")
    return 0


def _cmd_retention(a: argparse.Namespace) -> int:
    import json as _json

    from .db import make_engine, make_session_factory, session_scope
    from .services import retention

    settings = _settings()
    policy = retention.RetentionPolicy.load(a.policy or settings.retention_policy_path)
    with session_scope(make_session_factory(make_engine(settings.database_url))) as db:
        res = retention.apply(db, policy) if a.apply else retention.plan(db, policy)
    print(_json.dumps(res, indent=2, default=str))
    if not a.apply:
        print("Dry run: nothing was deleted. Re-run with --apply to delete the items above.")
    return 0


def _cmd_explain_summary(a: argparse.Namespace) -> int:
    import json as _json

    from .db import make_engine, make_session_factory, session_scope
    from .services import explanations
    from .services.scoring import ModelCache

    with session_scope(make_session_factory(make_engine(_settings().database_url))) as db:
        res = explanations.summarize(db, ModelCache(), a.import_id, a.model_id,
                                     sample_per_group=a.sample, seed=a.seed)
    text = _json.dumps(res, indent=2, default=str)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {a.out}")
    else:
        print(text)
    return 0


def _cmd_cic_study(a: argparse.Namespace) -> int:
    from .research.cic_ids2018 import run_study

    res = run_study(a.raw_dir, out_dir=a.out_dir, benign_cap=a.benign_cap, attack_cap=a.attack_cap,
                    max_train_rows=a.max_train_rows, n_estimators=a.trees, seed=a.seed,
                    drop_features=tuple(a.drop_feature or ()))
    print(f"Wrote {res['run_dir']}/report.md and result.json ({res['runtime']['total_seconds']} s)")
    return 0


def _cmd_cic_sample(a: argparse.Namespace) -> int:
    from .research.cic_ids2018 import write_sample

    res = write_sample(a.src, a.dest, benign_cap=a.benign_cap, attack_cap=a.attack_cap, seed=a.seed)
    print(f"Wrote {res['rows']:,} rows to {a.dest}: {res['labels']}")
    return 0


def _cmd_data_backup(a: argparse.Namespace) -> int:
    import json as _json

    from .services import backup

    if a.verify:
        res = backup.verify(a.path)
        print(_json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    out = backup.create(_settings(), a.path)
    print(f"Backup written to {out} ({backup.verify(out)['files']} files, hashes in manifest.json).")
    print("It contains the same sensitive data as the live system: keep it encrypted and access-controlled.")
    return 0


def _cmd_data_restore(a: argparse.Namespace) -> int:
    import json as _json

    from .services import backup

    res = backup.restore(_settings(), a.path, force=a.force)
    print(_json.dumps(res, indent=2))
    bad = [m for m in res["models"] if not m["ok"]]
    print("Restore complete. Run `adaptive-ids db-upgrade` if this backup came from an older version.")
    if bad:
        print(f"WARNING: {len(bad)} model artifact(s) could not be verified; do not activate them until fixed.")
        return 1
    return 0


def _cmd_demo(a: argparse.Namespace) -> int:
    from .demo import run_demo

    run_demo(_settings(), admin_username=a.admin)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="adaptive-ids", description="Adaptive IDS research and ML engine tools")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("inventory", help="read-only inventory of an existing research project folder")
    s.add_argument("project_dir")
    s.add_argument("--out", default="docs/inventory")
    s.add_argument("--hash-max-mb", type=float, default=None, help="skip hashing files larger than this")
    s.set_defaults(fn=_cmd_inventory)

    s = sub.add_parser("backup", help="create (or --verify) a hash-verified backup of the original project")
    s.add_argument("destination")
    s.add_argument("--source")
    s.add_argument("--verify", action="store_true")
    s.add_argument("--writable", action="store_true", help="do not mark copied files read-only")
    s.set_defaults(fn=_cmd_backup)

    s = sub.add_parser("hash", help="print SHA-256 of files (for manifests and dataset configs)")
    s.add_argument("files", nargs="+")
    s.set_defaults(fn=_cmd_hash)

    s = sub.add_parser("make-synthetic", help="write a clearly labelled SYNTHETIC demo dataset")
    s.add_argument("--out", default="data/sample/flows_SYNTHETIC_demo.csv")
    s.add_argument("--rows", type=int, default=5000)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--drift-after", type=float, default=None, help="fraction of rows after which benign traffic shifts")
    s.set_defaults(fn=_cmd_synthetic)

    s = sub.add_parser("preview", help="check a CSV against a feature schema and show its first rows")
    s.add_argument("csv")
    s.add_argument("--schema", required=True)
    s.add_argument("--mapping", help="JSON file mapping source column names to schema names")
    s.add_argument("--rows", type=int, default=5)
    s.set_defaults(fn=_cmd_preview)

    s = sub.add_parser("run", help="run an experiment config and write a reproducibility report")
    s.add_argument("config")
    s.set_defaults(fn=_cmd_run)

    s = sub.add_parser("db-upgrade", help="apply database migrations (ADAPTIVE_IDS_DATABASE_URL)")
    s.add_argument("--revision", default="head")
    s.set_defaults(fn=_cmd_db_upgrade)

    s = sub.add_parser("create-user", help="create an application user (password prompted)")
    s.add_argument("username")
    s.add_argument("--role", choices=["admin", "analyst", "viewer"], default="analyst")
    s.set_defaults(fn=_cmd_create_user)

    s = sub.add_parser("serve", help="run the API server")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.add_argument("--forwarded-allow-ips", default="127.0.0.1",
                   help="reverse-proxy address(es) whose X-Forwarded-For header is trusted (comma-separated)")
    s.set_defaults(fn=_cmd_serve)

    s = sub.add_parser("drift-experiment", help="controlled drift experiment on SYNTHETIC data (detection delay, false alarms, overhead)")
    s.add_argument("--modes", nargs="+", default=["none", "sudden", "gradual", "concept"], choices=["none", "sudden", "gradual", "concept"])
    s.add_argument("--repeats", type=int, default=3)
    s.add_argument("--seed", type=int, default=11)
    s.add_argument("--window-size", type=int, default=500)
    s.add_argument("--out", default="experiments/runs")
    s.set_defaults(fn=_cmd_drift_experiment)

    s = sub.add_parser("msc-reproduce", help="re-run the MSc notebook's supervised protocol on NSL-KDD and its controlled variants")
    s.add_argument("--test", required=True, help="KDDTest+.txt (the file the notebook actually loaded)")
    s.add_argument("--train", help="KDDTrain+.txt (enables the official train/test split variant)")
    s.add_argument("--out", default="experiments/runs")
    s.set_defaults(fn=_cmd_msc_reproduce)

    s = sub.add_parser("prepare-nsl-kdd", help="write an NSL-KDD .txt file as a headed CSV the importer accepts")
    s.add_argument("src", help="KDDTrain+.txt or KDDTest+.txt")
    s.add_argument("dest", help="output CSV path (keep it under data/, which is git-ignored)")
    s.set_defaults(fn=_cmd_prepare_nsl_kdd)

    s = sub.add_parser("retention", help="report (or with --apply, delete) data past the retention policy")
    s.add_argument("--apply", action="store_true", help="delete; without it this is a dry run")
    s.add_argument("--policy", help="policy file (default ADAPTIVE_IDS_RETENTION_POLICY or configs/retention.json)")
    s.set_defaults(fn=_cmd_retention)

    s = sub.add_parser("explain-summary", help="mean SHAP contribution per feature over a seeded sample of scored events")
    s.add_argument("--import-id", type=int, required=True, help="a scored import")
    s.add_argument("--model-id", type=int, required=True, help="the model version that scored it")
    s.add_argument("--sample", type=int, default=200, help="events per group (default 200)")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", help="write JSON here instead of printing it")
    s.set_defaults(fn=_cmd_explain_summary)

    s = sub.add_parser("cic-ids2018-study", help="chronological static vs adaptive study on CSE-CIC-IDS2018 day CSVs")
    s.add_argument("raw_dir", help="folder with the processed day CSVs (e.g. Wednesday-14-02-2018.csv)")
    s.add_argument("--out-dir", default="experiments/runs")
    s.add_argument("--benign-cap", type=int, default=60_000, help="benign rows sampled per day")
    s.add_argument("--attack-cap", type=int, default=20_000, help="rows sampled per attack class per day")
    s.add_argument("--max-train-rows", type=int, default=400_000)
    s.add_argument("--trees", type=int, default=100)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--drop-feature", action="append", help="exclude a feature (repeatable), e.g. 'Dst Port'")
    s.set_defaults(fn=_cmd_cic_study)

    s = sub.add_parser("cic-ids2018-sample", help="write a seeded per-class sample of one CSE-CIC-IDS2018 day CSV")
    s.add_argument("src"), s.add_argument("dest")
    s.add_argument("--benign-cap", type=int, default=60_000)
    s.add_argument("--attack-cap", type=int, default=20_000)
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(fn=_cmd_cic_sample)

    s = sub.add_parser("data-backup", help="back up the database, uploads, runs/models and configs with a hash manifest")
    s.add_argument("path", help="destination folder (or, with --verify, a backup folder to check)")
    s.add_argument("--verify", action="store_true", help="re-check an existing backup against its manifest")
    s.set_defaults(fn=_cmd_data_backup)

    s = sub.add_parser("data-restore", help="restore a verified backup into the configured database and folders")
    s.add_argument("path", help="backup folder written by data-backup")
    s.add_argument("--force", action="store_true", help="replace existing data")
    s.set_defaults(fn=_cmd_data_restore)

    s = sub.add_parser("demo", help="load the repeatable, clearly labelled SYNTHETIC demonstration into the database")
    s.add_argument("--admin", required=True, help="existing admin username recorded as the actor")
    s.set_defaults(fn=_cmd_demo)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
