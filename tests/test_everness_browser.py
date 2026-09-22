from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Self, cast

import pytest

from padel_availability.connectors.everness import EvernessSource, EvernessSourceError
from padel_availability.connectors.everness_browser import (
    _EVERNESS_VISIBLE_DOM_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    EvernessBrowserConnector,
    EvernessBrowserError,
    parse_everness_dom,
    parse_everness_observations,
)
from padel_availability.models import LocationRecord

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
    repeated_payload = _browser_payload(fixture_browser, "booking-available")

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
    assert payload["loading"] is False
    fingerprint = payload["grid_fingerprint"]
    assert isinstance(fingerprint, str) and fingerprint.startswith("fnv1a-")
    assert fingerprint == repeated_payload["grid_fingerprint"]
    rows = cast(list[dict[str, object]], payload["rows"])
    assert len(rows) == 3
    assert [row["time"] for row in rows] == ["09:00", "10:30", "12:00"]
    assert [
        [cast(dict[str, object], cell)["class"] for cell in cast(list[object], row["cells"])]
        for row in rows
    ] == [
        ["terrainTxt cursor", "terrainTxt notallowed"],
        ["terrainTxt cursor", "terrainTxt pending"],
        ["terrainTxt notallowed", "terrainTxt cursor"],
    ]
    assert all("external_id" not in cell for row in rows for cell in cast(list[dict[str, object]], row["cells"]))

    observations = parse_everness_dom(payload, REQUESTED_DATE)
    assert [observation.status for observation in observations] == [
        "available",
        "unavailable",
        "available",
        "unknown",
        "unavailable",
        "available",
    ]
    assert observations[0].ends_at == "2026-09-22T10:30:00+02:00"
    assert observations[-1].ends_at == "2026-09-22T13:30:00+02:00"


def test_everness_visible_script_filters_hidden_fixture(fixture_browser: Any) -> None:
    payload = _browser_payload(fixture_browser, "booking-hidden")

    assert payload["courts"] == ["Court 1"]
    rows = cast(list[dict[str, object]], payload["rows"])
    assert [row["time"] for row in rows] == ["09:00", "10:30"]
    assert all(len(cast(list[object], row["cells"])) == 1 for row in rows)
    observations = parse_everness_dom(payload, REQUESTED_DATE)
    assert [observation.status for observation in observations] == ["available", "unavailable"]


def test_everness_body_loading_markers_are_not_final_data(fixture_browser: Any) -> None:
    payload = _browser_payload(fixture_browser, "booking-loading")

    assert payload["loading"] is True
    with pytest.raises(ValueError, match="loading"):
        parse_everness_dom(payload, REQUESTED_DATE)


class _FakeEvernessLocator:
    def __init__(self, page: _FakeEvernessPage, selector: str, index: int | None = None) -> None:
        self.page = page
        self.selector = selector
        self.index = index

    def locator(self, selector: str) -> _FakeEvernessLocator:
        return _FakeEvernessLocator(self.page, f"{self.selector} {selector}")

    def nth(self, index: int) -> _FakeEvernessLocator:
        return _FakeEvernessLocator(self.page, self.selector, index)

    def count(self) -> int:
        return self.page.locator_count(self.selector)

    def is_visible(self) -> bool:
        return self.count() > (self.index or 0)

    def inner_text(self) -> str:
        return self.page.locator_text(self.selector, self.index)

    def get_attribute(self, name: str) -> str | None:
        return self.page.locator_attribute(self.selector, self.index, name)

    def click(self) -> None:
        self.page.click(self.selector, self.index)


class _FakeEvernessPage:
    def __init__(
        self,
        dates: dict[date, list[dict[str, object]]],
        initial_date: date,
        events: list[str],
        *,
        programming_error: bool = False,
    ) -> None:
        self.dates = dates
        self.current_date = initial_date
        self.events = events
        self.programming_error = programming_error
        self.pending: list[dict[str, object]] = []
        self.closed = False
        self.wait_ticks = 0
        self.wait_until: str | None = None

    @property
    def payload(self) -> dict[str, object]:
        if self.pending:
            return self.pending.pop(0)
        return dict(self.dates[self.current_date][-1])

    def locator(self, selector: str) -> _FakeEvernessLocator:
        return _FakeEvernessLocator(self, selector)

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        del timeout
        self.wait_until = wait_until
        self.events.append(f"goto:{url}")

    def evaluate(self, expression: str, arg: object = None) -> object:
        del arg
        if expression != _EVERNESS_VISIBLE_DOM_SCRIPT:
            raise AssertionError(f"unexpected page evaluation: {expression!r}")
        if self.programming_error:
            raise TypeError("test programming error")
        return self.payload

    def wait_for_timeout(self, timeout: int) -> None:
        self.wait_ticks += 1
        self.events.append(f"wait:{timeout}")

    def locator_count(self, selector: str) -> int:
        if selector in {"#table_reservation", "#datepicker", "#multi-language-date"}:
            return 1
        if selector == "#datepicker .day":
            return 31
        if selector == "#datepicker .datepicker-switch":
            return 1
        if selector == "#datepicker .next" or selector == "#datepicker .prev":
            return 1
        return 0

    def locator_text(self, selector: str, index: int | None) -> str:
        if selector == "#multi-language-date":
            return str(self.dates[self.current_date][-1]["date_label"])
        if selector == "#datepicker .datepicker-switch":
            return self.current_date.strftime("%B %Y")
        if selector == "#datepicker .day" and index is not None:
            return str(index + 1)
        return ""

    def locator_attribute(self, selector: str, index: int | None, name: str) -> str | None:
        if selector == "#datepicker .day" and index is not None and name == "class":
            return "day"
        return None

    def click(self, selector: str, index: int | None) -> None:
        self.events.append(f"click:{selector}:{index if index is not None else ''}")
        if selector == "#datepicker .day" and index is not None:
            selected = date(self.current_date.year, self.current_date.month, index + 1)
            self.current_date = selected
            self.pending = [dict(payload) for payload in self.dates[selected][:-1]]
        elif selector == "#datepicker .next":
            month = self.current_date.month % 12 + 1
            year = self.current_date.year + (self.current_date.month == 12)
            self.current_date = date(year, month, 1)
        elif selector == "#datepicker .prev":
            month = self.current_date.month - 1 or 12
            year = self.current_date.year - (self.current_date.month == 1)
            self.current_date = date(year, month, 1)

    def close(self) -> None:
        self.closed = True
        self.events.append("page_close")


class _FakeEvernessContext:
    def __init__(self, page: _FakeEvernessPage, events: list[str]) -> None:
        self.page = page
        self.events = events
        self.closed = False

    def new_page(self) -> _FakeEvernessPage:
        self.events.append("new_page")
        return self.page

    def close(self) -> None:
        self.closed = True
        self.events.append("context_close")


class _FakeEvernessBrowser:
    def __init__(self, context: _FakeEvernessContext, events: list[str]) -> None:
        self.context = context
        self.events = events

    def __enter__(self) -> Self:
        self.events.append("browser_enter")
        return self

    def __exit__(self, *_args: object) -> None:
        self.events.append("browser_exit")

    def new_context(self) -> _FakeEvernessContext:
        self.events.append("new_context")
        return self.context


class _FailingEvernessBrowser:
    def __enter__(self) -> Self:
        raise OSError("browser startup failed")

    def __exit__(self, *_args: object) -> None:
        pass

    def new_context(self) -> _FakeEvernessContext:
        raise AssertionError("browser startup should fail first")


def _everness_payload(
    requested_date: date,
    *,
    fingerprint: str,
    rows: list[tuple[str, list[str]]] | None = None,
    loading: bool = False,
) -> dict[str, object]:
    rows = rows or []
    return {
        "view": "booking",
        "date_label": requested_date.strftime("%-d %b %Y"),
        "courts": ["Court 1"],
        "rows": [
            {"time": row_time, "cells": [{"class": state, "style": ""} for state in states]}
            for row_time, states in rows
        ],
        "grid_fingerprint": fingerprint,
        "loading": loading,
        "visible_text": "Everness booking" + (" loading" if loading else ""),
    }


def _everness_location() -> LocationRecord:
    return LocationRecord(
        "everness",
        "Everness",
        "Geneva",
        ("everness",),
        "public",
        "no",
        "yes",
        "unknown",
        "unknown",
        "no",
        "to_verify",
        (),
        (),
        (),
        "",
        brand="Everness",
        booking_url="https://padel.everness.ch/",
        booking_platform="everness",
    )


def _everness_connector(
    dates: dict[date, list[dict[str, object]]],
    events: list[str],
    *,
    initial_date: date,
    programming_error: bool = False,
    timeout_ms: int = 15_000,
) -> tuple[EvernessBrowserConnector, _FakeEvernessPage, _FakeEvernessContext]:
    page = _FakeEvernessPage(dates, initial_date, events, programming_error=programming_error)
    context = _FakeEvernessContext(page, events)
    browser = _FakeEvernessBrowser(context, events)
    source = EvernessSource(
        "everness",
        "https://padel.everness.ch/",
        "2026-09-22T00:00:00Z",
        "public",
    )
    return (
        EvernessBrowserConnector((source,), browser_factory=lambda: browser, timeout_ms=timeout_ms),
        page,
        context,
    )


def test_everness_connector_collects_grid_and_closes_context() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    frame_dates = {
        requested: [
            _everness_payload(
                requested,
                fingerprint="grid-1",
                rows=[("09:00", ["cursor"]), ("10:30", ["notallowed"])],
            )
        ]
    }
    connector, page, context = _everness_connector(frame_dates, events, initial_date=requested)

    result = connector.collect(
        _everness_location(),
        run_id="run-everness",
        window_start=requested,
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert result.run.status == "success"
    assert len(result.slots) == 2
    assert page.wait_until == "commit"
    assert page.closed and context.closed
    assert events.count("browser_enter") == 1
    assert events.count("browser_exit") == 1
    assert events.count("new_context") == 1
    assert events.count("new_page") == 1
    assert events[-3:] == ["page_close", "context_close", "browser_exit"]
    assert not any("terrainTxt" in event or "submit" in event.lower() for event in events)


def test_everness_connector_selects_each_requested_date() -> None:
    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    dates = {
        first: [_everness_payload(first, fingerprint="grid-1", rows=[])],
        second: [_everness_payload(second, fingerprint="grid-2", rows=[])],
    }
    connector, _page, _context = _everness_connector(dates, events, initial_date=first)

    connector.collect(
        _everness_location(),
        run_id="run-everness",
        window_start=first,
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert "click:#datepicker .day:21" in events
    assert "click:#datepicker .day:22" in events
    assert not any("terrainTxt" in event or "submit" in event.lower() for event in events)


def test_everness_connector_rejects_stale_grid_without_refresh() -> None:
    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    dates = {
        first: [_everness_payload(first, fingerprint="grid-1", rows=[])],
        second: [_everness_payload(second, fingerprint="grid-1", rows=[])],
    }
    connector, page, context = _everness_connector(
        dates, events, initial_date=first, timeout_ms=100
    )

    with pytest.raises(EvernessBrowserError, match="requested date"):
        connector.collect(
            _everness_location(),
            run_id="run-everness",
            window_start=first,
            window_end=date(2026, 9, 24),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()

    assert page.closed and context.closed


def test_everness_connector_accepts_empty_grid_after_loading() -> None:
    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    dates = {
        first: [_everness_payload(first, fingerprint="grid-1", rows=[])],
        second: [
            _everness_payload(second, fingerprint="grid-1", rows=[], loading=True),
            _everness_payload(second, fingerprint="grid-2", rows=[]),
        ],
    }
    connector, _page, _context = _everness_connector(dates, events, initial_date=first)

    result = connector.collect(
        _everness_location(),
        run_id="run-everness",
        window_start=first,
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert result.slots == ()


def test_everness_connector_maps_startup_browser_error() -> None:
    source = EvernessSource(
        "everness",
        "https://padel.everness.ch/",
        "2026-09-22T00:00:00Z",
        "public",
    )
    connector = EvernessBrowserConnector((source,), browser_factory=lambda: _FailingEvernessBrowser())

    with pytest.raises(EvernessSourceError, match="browser"):
        connector.collect(
            _everness_location(),
            run_id="run-everness",
            window_start=REQUESTED_DATE,
            window_end=date(2026, 9, 23),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()


def test_everness_programming_errors_propagate_and_cleanup() -> None:
    events: list[str] = []
    dates = {REQUESTED_DATE: [_everness_payload(REQUESTED_DATE, fingerprint="grid-1", rows=[])]}
    connector, page, context = _everness_connector(
        dates, events, initial_date=REQUESTED_DATE, programming_error=True
    )

    with pytest.raises(TypeError, match="programming"):
        connector.collect(
            _everness_location(),
            run_id="run-everness",
            window_start=REQUESTED_DATE,
            window_end=date(2026, 9, 23),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()

    assert page.closed and context.closed
    assert events[-3:] == ["page_close", "context_close", "browser_exit"]
