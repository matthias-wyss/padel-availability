# Plugin date navigation and Pyright environment

## Status

Approved design for the follow-up diagnosed on 2026-09-28.

## Context

The eight Plugin pages expose the selected date in the visible `#multi-language-date`
control. After selecting Padel, they do not expose a next-day button. Clicking the
visible date opens a jQuery UI datepicker; its visible month/year controls and
day cells can select later dates. A read-only browser check selected 2026-10-01
from 2026-09-28 and observed the refreshed Padel grid.

The full Pyright check reports unresolved `playwright` imports when it analyzes
with its default interpreter. Verbose output shows Pyright assumes Python 3.11,
while the project requires Python 3.12 or newer. Running the same check with
`.venv/bin/python` as `--pythonpath`, or with Python version 3.12 plus the
configured venv, reports zero diagnostics. The issue is interpreter selection,
not missing runtime packages or source types.

## Design

- Navigate each requested date through the visible date control and calendar.
- Match the requested year, month, and day exactly; select only a visible
  datepicker control/cell, never a reservation cell.
- Wait for a stable visible grid whose date and activity match the request
  before parsing. Preserve existing fail-closed validation and cleanup.
- Set Pyright `pythonVersion` to `3.12` and `venvPath`/`venv` to the repository's
  `.venv` so the normal project check resolves the correct interpreter version
  and installed dependencies.
- Add regressions for a month-boundary date selection and verify bare project
  Pyright and the full test suite.
- Do not bypass disabled datepicker days. On 2026-09-28 the public pages exposed
  selectable dates through 2026-10-04 on six sites, 2026-09-30 on Crans, and at
  least 14 days on Gland; persist the longest visible window for each route.

## Boundaries

The collector remains public and read-only: no login, booking, private API,
hidden DOM, or participant data. No dependencies or production behavior outside
Plugin date navigation and Pyright environment resolution are changed.
