# Changelog

X

First release candidate. Everything before this was pre-alpha.

### Added
- **Run controls, all off by default** (`docs/CONFIGURATION.md`, "Optional run controls"):
  - a per-run estimated cost ceiling that fails closed (`max_estimated_cost_usd`, `stopped_reason: cost_ceiling`);
  - a shared stage deadline for Critic and Arbiter fallback chains;
  - reserve delegates: one bounded replacement wave when the quorum is unmet;
  - background runs (`?background=true`) with `POST /api/runs/{id}/cancel`.
- **Console:** a dashboard (7-day estimated cost, background runs), a provider table (model, credentials set or missing, prices, limits, last success and failure from the ledger, unknown shown as unknown), run options, live progress and a Cancel button for background runs, a per-run call ledger view, and a cost-ceiling stop notice.
- `GET /api/providers/status` and `GET /api/dashboard`.
- `docs/INSTALL.md` (install, first run, providers, troubleshooting, recovery), `docs/V1-RELEASE-STATUS.md`, `docs/ACCEPTANCE-2026-11-15.md` and the scripts and raw evidence behind it.
- A separate Critic model option in the judge benchmark runner (`--critic`).

### Changed
- Version is `1.0.0` in `pyproject.toml`, the package and the API; a test keeps them equal.
- The judge benchmark is complete on three judge models plus a different-Critic run; the Critic stays off by default.

### Fixed
- Benchmark and scoring scripts pass lint in CI.

### Known limits
See `docs/V1-RELEASE-STATUS.md`: billing was not reconciled against provider pages; Linux was verified by CI only; the value of a Critic and of a panel over one model is unmeasured.

## Before 1.0

Everything else (quorum of independent sources, blind judging, structured synthesis, the call ledger, retry chains, schema versions and backups, the adversarial suite and the mock benchmark) predates this candidate; see `README.md` and `docs/RELEASE_EVIDENCE.md`.
