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
  - Fieldset top padding: 17px to 9px, and `legend` top padding: 8px to 16px. This increases the border-to-heading inset while preserving the first field label's vertical position.
- Leave input spacing and 44px control targets unchanged so forms do not become cramped.

## Validation

- Add a browser assertion for the maximum intended intro-to-search vertical gap at desktop and mobile widths.
- Add a browser assertion that legend text sits at least 16px below its fieldset top border, the first date label stays within 58px of the border, and the gap to that label is at most 24px at desktop and mobile widths.
- Run the web UI test and the repository's required test, Ruff, formatting, and Pyright checks.
- Preserve the existing no-horizontal-overflow checks at 375, 768, 1024, and 1440 pixels.
