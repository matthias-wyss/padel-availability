# Project instructions

These rules supplement the workspace and cluster `AGENTS.md` files; they never
override them.

## Development

- Use Python 3.12 or newer. Sync tools with `uv sync --dev --group browser --group web`.
- Before completion, run `PYTHONPATH=src uv run pytest -q`,
  `uv run ruff check .`, `uv run ruff format --check src tests`, and `uv run pyright`.
- Keep the Flask page server-rendered and use native HTML/CSS/JavaScript unless
  the product requirements change.
- Use a git worktree for isolated feature work; do not include `.venv`, local
  SQLite files, browser state, or credentials in commits.

## Collection and availability semantics

- Collect only visible, public booking-page availability. Do not use login,
  private APIs, booking/payment actions, CAPTCHA bypasses, or player data.
- Preserve the distinction between `available`, `unknown`, `stale`, missing,
  unavailable, and out-of-window data. Never infer a free slot or extend a
  source's published date window.
- Page GETs read cached snapshots only. The refresh endpoint may enqueue only
  the fixed all-source job; never accept a URL, source path, or command from a
  request.
- Never commit `var/*.sqlite3`, persistent production data, browser profiles,
  or secrets.

## Infrastructure changes

- Before changing CT103/CT100, read the applicable docs under
  `/home/agentops/workspace/infra/` and inspect live state.
- Show each server write command before running it, then verify the change.
- After a real server change, update the corresponding infra documentation,
  date it, and commit/push the infra repo as required by the cluster rules.
