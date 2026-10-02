# UI Vertical Spacing Adjustment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten the main vertical gaps on the availability page without changing its layout or control spacing.

**Architecture:** Add a Playwright assertion against the rendered section gaps, then adjust the existing CSS margins in place. Keep the current desktop sidebar, mobile stacking, and native HTML controls.

**Tech Stack:** Python 3.12, pytest, Playwright, Flask, HTML, CSS.

## Global Constraints

- Keep the desktop sidebar/results layout and mobile stacking.
- Keep filter padding, 44px control targets, typography, colors, and content unchanged.
- Use the existing Playwright test setup; do not add dependencies.
- Run `PYTHONPATH=src uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check src tests`, and `uv run pyright` before completion.

---

### Task 1: Add a regression check for vertical section gaps

**Files:**
- Modify: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: the existing `browser_page` and `web_server` fixtures.
- Produces: a browser regression test limiting the intro, results-heading, and result-section gaps.

- [ ] **Step 1: Add the failing test**

Add this test to `tests/test_web_ui.py`:

```python
def test_vertical_spacing_stays_compact_across_viewports(
    browser_page: Page, web_server: str
) -> None:
    browser_page.goto(web_server)

    for width, intro_limit in ((1440, 32), (375, 20)):
        browser_page.set_viewport_size({"width": width, "height": 900})
        gaps = browser_page.evaluate(
            """() => ({
                intro: parseFloat(getComputedStyle(document.querySelector('.intro')).marginBottom),
                heading: parseFloat(getComputedStyle(document.querySelector('.results-heading')).marginBottom),
                section: parseFloat(getComputedStyle(document.querySelector('.result-section')).marginBottom),
            })"""
        )
        assert gaps["intro"] <= intro_limit
        assert gaps["heading"] <= 16
        assert gaps["section"] <= 24
```

- [ ] **Step 2: Run the test and confirm it fails on the current spacing**

Run: `PYTHONPATH=src uv run pytest tests/test_web_ui.py::test_vertical_spacing_stays_compact_across_viewports -q`

Expected: FAIL because the current desktop intro gap is 38px, the results heading gap is 23px, and result-section gap is 30px.

### Task 2: Apply the approved CSS spacing values

**Files:**
- Modify: `src/padel_availability/static/app.css`

**Interfaces:**
- Consumes: the regression test from Task 1.
- Produces: intro gaps of 32px desktop / 20px mobile, a 16px results-heading gap, and 24px result-section spacing.

- [ ] **Step 1: Change only the approved margins**

```css
.intro {
  margin: 0 0 32px;
}

.results-heading {
  margin-bottom: 16px;
}

.result-section {
  margin: 0 0 24px;
}

@media (max-width: 767px) {
  .intro {
    margin-bottom: 20px;
  }
}
```


- [ ] **Step 2: Run the focused test and confirm it passes**

Run: `PYTHONPATH=src uv run pytest tests/test_web_ui.py::test_vertical_spacing_stays_compact_across_viewports -q`

Expected: PASS at 1440px and 375px.

- [ ] **Step 3: Run all required project checks**

Run these commands:

```bash
PYTHONPATH=src uv run pytest -q
uv run ruff check .
uv run ruff format --check src tests
uv run pyright
```

Expected: all tests pass; Ruff, formatting, and Pyright report no issues. The existing responsive test must continue to confirm no horizontal overflow at 375, 768, 1024, and 1440px.
