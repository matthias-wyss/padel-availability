# UI Vertical Spacing Adjustment

## Status

Approved by the user; a follow-up legend inset was added from the screenshot feedback on 2026-10-02.

## Goal

Improve the vertical rhythm around the page introduction and availability results, as shown in the user's screenshot.

## Design

- Keep the current desktop sidebar/results layout, mobile stacking, typography, and content unchanged.
- Adjust only major section gaps in `src/padel_availability/static/app.css`:
  - `.intro` bottom margin: 38px to 32px on desktop, and 25px to 20px on mobile.
  - `.results-heading` bottom margin: 23px to 16px.
  - `.result-section` bottom margin: 30px to 24px.
  - `legend` top padding: 0 to 8px so the legend text clears the native fieldset border.
- Leave fieldset padding, input spacing, and 44px control targets unchanged so forms do not become cramped.

## Validation

- Add a browser assertion for the maximum intended intro-to-search vertical gap at desktop and mobile widths.
- Add a browser assertion that legend text sits at least 8px below its fieldset top border at desktop and mobile widths.
- Run the web UI test and the repository's required test, Ruff, formatting, and Pyright checks.
- Preserve the existing no-horizontal-overflow checks at 375, 768, 1024, and 1440 pixels.
