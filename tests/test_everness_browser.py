from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest

from padel_availability.connectors.everness_browser import (
    _EVERNESS_VISIBLE_DOM_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    parse_everness_dom,
    parse_everness_observations,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "everness" / "dom"
REQUESTED_DATE = date(2026, 9, 22)


@pytest.fixture(scope="module")
def fixture_browser() -> Any:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        pytest.skip(f"Playwright is unavailable: {error}")

    previous_fontconfig = os.environ.get("FONTCONFIG_FILE")
    font_dir = Path("/tmp/opencode/playwright-libs/usr/share/fonts")
    if font_dir.is_dir():
        os.environ["FONTCONFIG_FILE"] = str(Path(__file__).parent / "fixtures" / "fontconfig.conf")
    playwright = sync_playwright().start()
    browser = None
    try:
        try:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-gpu", "--disable-dev-shm-usage"],
            )
        except (OSError, PlaywrightError) as error:
            pytest.skip(f"Chromium could not launch: {error}")
        yield browser
    finally:
        if browser is not None:
            browser.close()
        playwright.stop()
        if previous_fontconfig is None:
            os.environ.pop("FONTCONFIG_FILE", None)
        else:
            os.environ["FONTCONFIG_FILE"] = previous_fontconfig


def _browser_payload(browser: Any, name: str) -> dict[str, object]:
    context = browser.new_context()
    page = context.new_page()
    try:
        page.set_content((FIXTURE_ROOT / f"{name}.html").read_text(encoding="utf-8"))
        page.add_style_tag(
            content=(
                "#multi-language-date, #table_reservation, .table_header, "
                ".hour_slot, .terrainTxt { display:block; width:100px; height:20px; }"
            )
        )
        payload = page.evaluate(_EVERNESS_VISIBLE_DOM_SCRIPT)
        assert isinstance(payload, dict)
        return cast(dict[str, object], payload)
    finally:
        page.close()
        context.close()


def _payload(
    rows: list[tuple[str, list[str]]],
    *,
    courts: list[str] | None = None,
    date_label: str = "22 Sep 2026",
    visible_text: str = "Everness booking",
    loading: bool = False,
) -> dict[str, object]:
    court_labels = courts or ["Court 1", "Court 2"]
    return {
        "view": "booking",
        "date_label": date_label,
        "courts": court_labels,
        "rows": [
            {
                "time": time,
                "cells": [{"class": classes, "style": ""} for classes in states],
            }
            for time, states in rows
        ],
        "grid_fingerprint": "fixture",
        "loading": loading,
        "visible_text": visible_text,
    }


def test_everness_available_dom_extracts_visible_cells() -> None:
    observations = parse_everness_dom(
        _payload(
            [("09:00", ["cursor", "notallowed"]), ("10:30", ["cursor", "pending"]), ("12:00", ["notallowed", "cursor"])],
        ),
        REQUESTED_DATE,
    )

    assert len(observations) == 6
    assert [observation.status for observation in observations] == [
        "available",
        "unavailable",
        "available",
        "unknown",
        "unavailable",
        "available",
    ]
    assert all(observation.external_id is None for observation in observations)


def test_everness_ignores_hidden_cells() -> None:
    observations = parse_everness_dom(
        _payload([("09:00", ["cursor"]), ("10:30", ["notallowed"])], courts=["Court 1"]),
        REQUESTED_DATE,
    )

    assert len(observations) == 2
    assert all(observation.court_label == "Court 1" for observation in observations)


def test_everness_unavailable_and_unknown_states() -> None:
    observations = parse_everness_dom(
        _payload([("09:00", ["notallowed", "pending"]), ("10:30", ["pending", "cursor"])]),
        REQUESTED_DATE,
    )

    assert [observation.status for observation in observations] == [
        "unavailable",
        "unknown",
        "unknown",
        "available",
    ]


def test_everness_empty_visible_grid_returns_zero_slots() -> None:
    assert parse_everness_dom(_payload([], courts=["Court 1", "Court 2"]), REQUESTED_DATE) == ()


def test_everness_loading_page_is_not_final_data() -> None:
    with pytest.raises(ValueError, match="loading"):
        parse_everness_dom(_payload([], loading=True), REQUESTED_DATE)


@pytest.mark.parametrize("marker", ["Log in to continue", "CAPTCHA verification required"])
def test_everness_login_or_captcha_is_bounded_error(marker: str) -> None:
    with pytest.raises(ValueError, match="blocked"):
        parse_everness_dom(_payload([], visible_text=marker), REQUESTED_DATE)


def test_everness_malformed_grid_is_error() -> None:
    with pytest.raises(ValueError, match="matrix"):
        parse_everness_dom(
            _payload([("09:00", ["cursor"]), ("10:30", ["cursor", "cursor"]) ]),
            REQUESTED_DATE,
        )


def test_everness_derives_visible_ninety_minute_duration() -> None:
    observations = parse_everness_dom(
        _payload([("09:00", ["cursor", "cursor"]), ("10:30", ["cursor", "cursor"]), ("12:00", ["cursor", "cursor"])]),
        REQUESTED_DATE,
    )

    assert observations[0].ends_at == "2026-09-22T10:30:00+02:00"
    assert observations[-1].ends_at == "2026-09-22T13:30:00+02:00"


def test_everness_24_hour_times_use_zurich_and_utc() -> None:
    observations = parse_everness_dom(
        _payload(
            [("21:30", ["cursor"]), ("23:00", ["cursor"])],
            courts=["Court 1"],
        ),
        REQUESTED_DATE,
    )
    slots = parse_everness_observations(
        observations,
        location_id="everness",
        run_id="run-everness",
        window_start=REQUESTED_DATE,
        window_end=date(2026, 9, 23),
    )

    assert observations[0].starts_at == "2026-09-22T21:30:00+02:00"
    assert slots[0].starts_at == "2026-09-22T19:30:00Z"
    assert slots[0].ends_at == "2026-09-22T21:00:00Z"


def test_everness_missing_ids_use_shared_hash() -> None:
    observations = parse_everness_dom(
        _payload([("09:00", ["cursor"]), ("10:30", ["cursor"])], courts=["Court 1"]),
        REQUESTED_DATE,
    )
    slots = parse_everness_observations(
        observations,
        location_id="everness",
        run_id="run-everness",
        window_start=REQUESTED_DATE,
        window_end=date(2026, 9, 23),
    )

    assert observations[0].external_id is None
    assert len(slots[0].slot_key) == 64
    assert slots[0].external_id is None


def test_everness_visible_script_extracts_only_sanitized_visible_dom(fixture_browser: Any) -> None:
    payload = _browser_payload(fixture_browser, "booking-available")

    assert set(payload) == {
        "view",
        "date_label",
        "courts",
        "rows",
        "grid_fingerprint",
        "loading",
        "visible_text",
    }
    assert payload["view"] == "booking"
    assert payload["date_label"] == "22 Sep 2026"
    assert payload["courts"] == ["Court 1", "Court 2"]
    rows = cast(list[dict[str, object]], payload["rows"])
    assert len(rows) == 3
    assert all("external_id" not in cell for row in rows for cell in cast(list[dict[str, object]], row["cells"]))


def test_everness_visible_script_filters_hidden_fixture(fixture_browser: Any) -> None:
    payload = _browser_payload(fixture_browser, "booking-hidden")

    assert payload["courts"] == ["Court 1"]
    rows = cast(list[dict[str, object]], payload["rows"])
    assert [row["time"] for row in rows] == ["09:00", "10:30"]
    assert all(len(cast(list[object], row["cells"])) == 1 for row in rows)
