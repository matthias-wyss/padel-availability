# Task 3 report — Plugin browser connector

## Implementation

- Added `PluginBrowserConnector`, its factory alias, and browser/session protocols in `plugin_browser.py`.
- The connector opens the exact `PluginSource.booking_url`, handles only visible optional-cookie decline controls, waits for a complete visible court/slot matrix, and navigates requested days by clicking a uniquely discovered visible next-day control inside `.header_date`.
- Each date goes through `parse_plugin_dom`; observations go directly to `parse_browser_observations`, with `PlaytomicSourceError` translated to `PluginBrowserError`.
- Page, context, and browser session close after successful collection and on browser/parser failures. Explicit empty diaries return a successful empty result.
- No booking-cell, submit, login, or private-endpoint interactions were added.

## TDD and verification evidence

- **Red:** `.venv/bin/python -m pytest -q tests/test_plugin_browser.py -k connector` failed during collection with `ImportError: cannot import name 'PluginBrowserConnector'`, as expected before implementation.
- **Green:** `.venv/bin/python -m pytest -q tests/test_plugin_browser.py` — `31 passed`.
- `.venv/bin/ruff check src/padel_availability/connectors/plugin_browser.py tests/test_plugin_browser.py` — all checks passed.
- `.venv/bin/pyright src/padel_availability/connectors/plugin_browser.py` — `0 errors, 0 warnings, 0 informations`.
- `git diff --check` on the two Task 3 code files — clean.

## Selector decision / concern

The diary date script already recognizes `.header_date` as its visible date label. The connector scopes next-day candidates to visible buttons, links, and role-buttons inside that element; it accepts explicit next/following labels (including common French labels and right-arrow glyphs), and fails closed if the control is absent or ambiguous. Cookie decline searches visible button-like controls labeled decline/reject/refuser/refuse and does nothing when none is visible. Selector behavior is verified with fake-page lifecycle tests and the sanitized DOM fixture; no live booking page was opened, so real-site selector variation remains unverified.
