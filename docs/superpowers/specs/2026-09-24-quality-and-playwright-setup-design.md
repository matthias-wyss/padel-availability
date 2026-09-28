# Repository Quality and Playwright Setup Design

## Goal

Make the repository's documented quality checks pass without exclusions, and
make the optional Playwright browser setup reproducible for developers. Preserve
application behavior except for corrections required to satisfy already intended
validation and type contracts.

## Current State

- `ruff check .` reports 21 violations, mostly in code and tests predating the
  Padel First integration.
- `pyright` in strict mode reports 77 errors across existing modules and tests.
- `ruff format --check .` reports formatting drift across existing files and
  some files in the uncommitted Padel First work.
- Playwright is an optional dependency group. Setup guidance installs Chromium
  but does not install or explain Linux browser libraries consistently.
- Browser test fixtures contain a Fontconfig configuration tied to
  `/tmp/opencode/playwright-libs`, a workspace-specific location.
- Padel First changes are already present as uncommitted work and must be
  preserved while carrying out repository-wide checks.

These counts describe the checks observed during design exploration; the plan
will rerun all checks before remediation to establish the exact baseline.

## Approved Design

### 1. Repository-wide Ruff and Pyright cleanup

- Keep the configured Ruff and Pyright checks repository-wide; do not add
  exclusions, relax strict mode, or suppress diagnostics just to reach a green
  result.
- Use Ruff formatting and safe import fixes first, reviewing the resulting diff
  before proceeding.
- Resolve remaining Ruff findings and Pyright diagnostics in small file-oriented
  batches. Preserve runtime validation at trust boundaries and existing error
  handling.
- Add or adjust a focused test if a correction changes behavior or fixes a
  demonstrable defect. Avoid tests that merely duplicate unchanged behavior.
- Do not intentionally refactor architecture or alter product behavior as part
  of lint/type cleanup.

### 2. Reproducible Playwright setup

- Document the optional browser group and Chromium setup using project commands:

  ```bash
  uv sync --dev --group browser
  uv run playwright install --with-deps chromium
  ```

- Explain that Linux system dependency installation may require administrator
  privileges; setup must not run automatically from application startup.
- Update CLI setup guidance to give the same complete install commands.
- Remove user-facing reliance on `/tmp/opencode` paths. Browser tests should use
  the installed system browser libraries and fonts, and should not set a
  workspace-specific `FONTCONFIG_FILE`.
- Keep Playwright optional for non-browser users; do not add a new dependency or
  an automatic bootstrap mechanism.

## Verification

The work is complete when all of the following pass from the repository root:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run --group browser --group dev pytest -q
git diff --check
```

Also run the documented Padel First two-day CLI smoke against a disposable
SQLite database after installing the documented Playwright runtime. Confirm a
successful `vernier` outcome and inspect its persisted run and slots through the
application database API.

## Boundaries

- No package additions are planned.
- No automated browser or operating-system installation is planned.
- No Padel First business behavior changes are planned beyond fixing defects
  found and covered during verification.
- Do not discard or overwrite the current uncommitted Padel First work.
- This document and the implementation remain subject to review before the
  implementation plan is written.
