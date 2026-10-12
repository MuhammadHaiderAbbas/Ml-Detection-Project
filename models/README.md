# Model artifacts

Model binaries are **not committed** (see `.gitignore`). This folder holds, locally:

- `trusted_artifacts.json` — the manifest of artifacts you have personally verified.
  Copy `trusted_artifacts.example.json` and fill it in. The loader
  (`adaptive_ids.detection.TrustedArtifactManifest`) refuses any artifact that is
  not listed or whose SHA-256 differs from the manifest, *before* deserialising it.
- `original/` — copies of the original MSc model files (taken from the verified
  backup, never from the internet or from other people).

Why: `.joblib`/`.pkl` files can execute arbitrary code when loaded, and
scikit-learn models are not guaranteed to load correctly across library versions.
Record the training scikit-learn version in the manifest and pin the same
version before loading.
