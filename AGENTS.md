# Repository Guidelines

## Project Structure & Module Organization
- `scripts/` hosts Python and shell tools for account, transaction, and validator workflows; keep new utilities here and reuse the `verb_object.py` pattern.
- Outputs land in `logs/`, `data/`, and root `*.txt` artifacts such as `execution.txt`; prefer timestamped filenames and avoid committing bulky fixtures.
- Environment descriptors (`Dockerfile`, `requirements.txt`, `scripts/requirements-locust.txt`) define supported stacks; update them together when dependencies change.
- `experiments/`, `validator_keys/`, and `secrets.env` are developer stashes—remove sensitive content before sharing branches.

## Build, Test, and Development Commands
- Run scripts without pre-installation using `uv run scripts/<name>.py --help`; `uv` resolves dependencies declared in `pyproject.toml`.
- For a reusable local environment execute `uv sync` (creates `.venv`) or, if `uv` is unavailable, fall back to `python3 -m venv .venv && pip install -r requirements.txt`.
- Install optional Locust tooling only when needed via `uv pip install -r scripts/requirements-locust.txt`.
- Shell helpers continue to run with `bash scripts/check_multiple_nodes.sh`; prefer `uv run python scripts/...` for Python tooling.
- Build the reproducible image using `docker build -t ethereum-testing-tools .`; the image ships with `uv` preinstalled for consistent runs.

## Coding Style & Naming Conventions
- Default to PEP 8, four-space indentation, explicit imports, and handle argument parsing in a `parse_args()` helper.
- CLI flags stay snake_case; describe defaults in `argparse` help text and surface user messages with `print()` as the current scripts do.
- Shell scripts should start with `#!/usr/bin/env bash` plus `set -euo pipefail`; keep filenames descriptive (`check_multiple_nodes.sh`).

## Testing Guidelines
- After editing transaction flows, rerun `uv run scripts/send_transactions.py --log --rpc-url <devnet>` and capture results in `logs/`.
- For validator operations, validate against a public testnet or local beacon node and store the log (e.g., `uv run scripts/consolidation.py --log-file logs/consolidation_$(date +%Y%m%d).log`).
- Introduce pure utility code with lightweight `pytest` cases under a new `tests/` directory and wire them into `uv run pytest -q`.

## Commit & Pull Request Guidelines
- Follow history: concise, Title Case imperative subjects (`Add Blob Transaction Runner`) with optional detail in the body.
- PRs include a summary, verification steps, linked issues or experiments, and sanitized logs or screenshots when behavior shifts.
- Request review from a maintainer familiar with the touched scripts and flag required environment variables or secrets.

## Security & Configuration Tips
- Keep RPC URLs, private keys, and passwords in environment variables or `.env`; never commit sensitive data.
- Exercise changes on a devnet or forked mainnet before touching production endpoints.
