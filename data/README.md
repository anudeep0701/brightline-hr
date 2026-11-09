# Synthetic data

The canonical generator is `scripts/generate_synthetic_data.py`. It supports multiple tenants, seven providers, ten explicit operational scenarios, fixed seeds and a fixed default UTC start.

See [synthetic/README.md](synthetic/README.md) for CLI arguments, scenario definitions, event schema, exact sample regeneration and demo instructions. The generated, committed sample lives in `synthetic/sample/`; ad hoc default output under `synthetic/generated/` is ignored by Git.

The demo seeder imports the same generator and anchors it to a recent interval. Existing local demo databases are preserved; use a separate ignored database file for a fresh run. No external API is called.

The official 60-record input is preserved at `provided/integration_logs.json`; use `scripts/replay_official_data.py` for the shared-pipeline replay. Its mapping and sparse-sample assumptions are in `docs/OFFICIAL_DATA_REPLAY.md`. Generated bulk JSONL is intentionally omitted from the focused assessment ZIP.
