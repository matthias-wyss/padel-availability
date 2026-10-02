# UI Vertical Spacing Adjustment

## Status

Proposed after user approved the targeted-spacing approach on 2026-10-01; awaiting review of this specification.

## Goal

Improve the vertical rhythm around the page introduction and availability results, as shown in the user's screenshot.

## Design

- Keep the current desktop sidebar/results layout, mobile stacking, typography, and content unchanged.
- Adjust only major section gaps in `src/padel_availability/static/app.css`:
  - `.intro` bottom margin: 38px to 32px on desktop, and 25px to 20px on mobile.
  - `.results-heading` bottom margin: 23px to 16px.
  - `.result-section` bottom margin: 30px to 24px.
- Leave filter fieldset padding, control spacing, and 44px control targets unchanged so forms do not become cramped.

## Validation

- Add a browser assertion for the maximum intended intro-to-search vertical gap at desktop and mobile widths.
- Run the web UI test and the repository's required test, Ruff, formatting, and Pyright checks.
- Preserve the existing no-horizontal-overflow checks at 375, 768, 1024, and 1440 pixels.
