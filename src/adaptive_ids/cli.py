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

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
