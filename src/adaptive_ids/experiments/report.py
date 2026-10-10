"""Render an experiment result as a Markdown report."""

from __future__ import annotations

from typing import Any


def _fmt(v: Any, digits: int = 4) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def _metrics_section(title: str, m: dict[str, Any] | None) -> list[str]:
    if not m:
        return [f"### {title}", "", "_Not evaluated (empty partition)._", ""]
    lines = [
        f"### {title}",
        "",
        f"Rows: {m['n_rows']} (scored {m['n_scored']}, rejected at inference {m['n_rejected_at_inference']})",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Accuracy | {_fmt(m['accuracy'])} |",
    ]
    for avg in ("macro", "weighted"):
        a = m["averages"][avg]
        lines += [
            f"| {avg.title()} precision | {_fmt(a['precision'])} |",
            f"| {avg.title()} recall | {_fmt(a['recall'])} |",
            f"| {avg.title()} F1 | {_fmt(a['f1'])} |",
        ]
    b = m.get("binary_attack_vs_benign")
    if b:
        lines += [
            f"| Attack precision | {_fmt(b['precision'])} |",
            f"| Attack recall (detection rate) | {_fmt(b['recall_detection_rate'])} |",
            f"| Attack F1 | {_fmt(b['f1'])} |",
            f"| False-positive rate | {_fmt(b['false_positive_rate'])} |",
            f"| False-negative rate | {_fmt(b['false_negative_rate'])} |",
        ]
    lines += ["", "Per-class:", "", "| Class | Precision | Recall | F1 | Support |", "|---|---|---|---|---|"]
    for lab, pc in m["per_class"].items():
        lines.append(f"| {lab} | {_fmt(pc['precision'])} | {_fmt(pc['recall'])} | {_fmt(pc['f1'])} | {pc['support']} |")
    cm = m["confusion_matrix"]
    labels = cm["labels"]
    lines += ["", "Confusion matrix (rows = true, columns = predicted):", "",
              "| true \\ pred | " + " | ".join(labels) + " |",
              "|---" * (len(labels) + 1) + "|"]
    for lab, row in zip(labels, cm["rows_true_cols_pred"]):
        lines.append(f"| **{lab}** | " + " | ".join(str(x) for x in row) + " |")
    lines.append("")
    return lines


def render_markdown_report(r: dict[str, Any]) -> str:
    ds, model, env = r["dataset"], r["model"], r["environment"]
    lines = [
        f"# Experiment report — {r['experiment_id']}",
        "",
        f"> **{r['provenance_banner']}**",
        "",
        f"**Objective:** {r['objective']}",
        "",
        f"- Started: {r['started_at']}  ",
        f"- Finished: {r['finished_at']} ({r['duration_s']:.1f} s)  ",
        f"- Result hash: `{r['result_sha256']}`",
        "",
        "## Dataset",
        "",
        f"- Name/version: {ds['name']} @ {ds['version']}",
        f"- File SHA-256: `{ds['file_sha256']}`",
        f"- Rows: {ds['total_rows']} total, {ds['accepted_rows']} accepted, {ds['rejected_rows']} rejected, "
        f"{ds['duplicate_rows']} duplicates ({ds['duplicates_dropped']} dropped)",
        f"- Label distribution (accepted rows): {ds['label_distribution']}",
        f"- Feature schema: {r['schema']['id']} ({r['schema']['n_features']} features, status: {r['schema']['status']})",
    ]
    if ds["rejection_reason_counts"]:
        top = list(ds["rejection_reason_counts"].items())[:10]
        lines.append("- Top rejection reasons: " + ", ".join(f"{k} ({v})" for k, v in top))
    sp = r["split"]
    lines += [
        "",
        "## Methodology",
        "",
        f"- Split: **{sp['method']}** {sp['params']} → sizes {sp['sizes']}",
        f"- Evaluated label distribution: {r['evaluated_label_distribution']}",
        f"- Preprocessing: `{r['preprocessing']['version_id']}` config={r['preprocessing']['config']} "
        f"(fitted on: {r['preprocessing']['fitted_on'] or 'not fitted — stateless'})",
        f"- Model: `{model['model_version']}` ({model['estimator_class']}), provenance: {model['provenance']}",
        f"- Decision rule: `{r['decision']['rule']}`; score kind: {r['decision']['score_kind']}",
        "- Validation metrics are for model selection only; **test metrics are the reported result**.",
        "",
        "## Results",
        "",
    ]
    lines += _metrics_section("Test partition (final)", r["metrics"]["test"])
    lines += _metrics_section("Validation partition (model selection)", r["metrics"]["validation"])

    comp = r["comparison_with_reported"]
    if comp["rows"]:
        lines += [f"## Comparison with reported results ({comp['source'] or 'source not stated'})", "",
                  "| Metric | Reported | Reproduced | Difference |", "|---|---|---|---|"]
        for row in comp["rows"]:
            lines.append(f"| {row['metric']} | {_fmt(row['reported'])} | {_fmt(row['reproduced'])} | {_fmt(row['difference'])} |")
        lines.append("")

    b = r.get("benchmark")
    if b:
        lat = b["batch_latency_ms"]
        lines += [
            "## Inference benchmark", "",
            f"- Method: {b['method']}",
            f"- Batch of {b['batch_rows']} rows × {b['repeats']} repeats: mean {lat['mean']:.2f} ms, "
            f"p95 {lat['p95']:.2f} ms; throughput {_fmt(b['throughput_rows_per_s'], 0)} rows/s; "
            f"peak Python heap {b['peak_python_heap_mb']:.1f} MB; errors {b['error_count']}",
            "",
        ]
    lines += [
        "## Environment", "",
        f"- Python {env['python']} on {env['platform']} ({env['cpu_count']} logical CPUs, RAM {env['total_ram_gb']} GB)",
        f"- GPU: {env['gpu']}",
        f"- Packages: {env['packages']}",
        f"- Code commit: {env['code_commit']}",
        "",
        "## Warnings", "",
    ]
    lines += [f"- {w}" for w in r["warnings"]] or ["- None"]
    lines += ["", "## Limitations", ""]
    lines += [f"- {l}" for l in r["limitations"]] or ["- None recorded"]
    lines += ["", "## Output artifacts", ""] + [f"- `{a}`" for a in r["artifacts"]] + [""]
    return "\n".join(lines)
