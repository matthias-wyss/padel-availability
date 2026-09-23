from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Self, cast

import pytest

from padel_availability.connectors import everness_browser
from padel_availability.connectors.everness import EvernessSource, EvernessSourceError
from padel_availability.connectors.everness_browser import (
    _EVERNESS_VISIBLE_DOM_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    EvernessBrowserConnector,
    EvernessBrowserError,
    _datepicker_month,  # pyright: ignore[reportPrivateUsage]
    _parse_date_label,  # pyright: ignore[reportPrivateUsage]
    parse_everness_dom,
    parse_everness_observations,
)
from padel_availability.connectors.playtomic import PlaytomicSourceError
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
    return _browser_payload_html(browser, (FIXTURE_ROOT / f"{name}.html").read_text(encoding="utf-8"))


def _browser_payload_html(browser: Any, html: str) -> dict[str, object]:
    context = browser.new_context()
    page = context.new_page()
    try:
        page.set_content(html)
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


def test_everness_expands_visible_colspan_rows(fixture_browser: Any) -> None:
    payload = _browser_payload(fixture_browser, "booking-colspan")

    rows = cast(list[dict[str, object]], payload["rows"])
    assert [
        [cast(dict[str, object], cell)["colspan"] for cell in cast(list[object], row["cells"])]
        for row in rows
    ] == [[None, "2"], [None, "2"]]

    observations = parse_everness_dom(payload, REQUESTED_DATE)

    assert len(observations) == 6
    assert [observation.court_label for observation in observations] == [
        "Court 1",
        "Court 2",
        "Court 3",
        "Court 1",
        "Court 2",
        "Court 3",
    ]
    assert [observation.status for observation in observations] == [
        "available",
        "unavailable",
        "unavailable",
        "unavailable",
        "available",
        "available",
    ]


def test_everness_synthetic_cells_without_colspan_remain_single_span() -> None:
    observations = parse_everness_dom(
        _payload([("09:00", ["cursor", "notallowed"]), ("10:30", ["cursor", "cursor"])]),
        REQUESTED_DATE,
    )

    assert len(observations) == 4


@pytest.mark.parametrize("span", ["", "0", "-1", "1.5", "two", True, 0, -1])
def test_everness_rejects_invalid_colspan(span: object) -> None:
    payload = _payload([("09:00", ["cursor", "notallowed"]), ("10:30", ["cursor", "cursor"])])
    cells = cast(list[dict[str, object]], cast(dict[str, object], cast(list[object], payload["rows"])[0])["cells"])
    cells[0]["colspan"] = span

    with pytest.raises(ValueError, match="span"):
        parse_everness_dom(payload, REQUESTED_DATE)


@pytest.mark.parametrize(
    ("cells", "courts"),
    [
        ([{"class": "cursor", "style": "", "colspan": "2"}], ["Court 1", "Court 2", "Court 3"]),
        (
            [
                {"class": "cursor", "style": "", "colspan": "2"},
                {"class": "notallowed", "style": "", "colspan": "2"},
            ],
            ["Court 1", "Court 2"],
        ),
    ],
)
def test_everness_rejects_partial_or_overfull_expanded_matrix(
    cells: list[dict[str, object]], courts: list[str]
) -> None:
    payload = _payload(
        [("09:00", ["cursor", "notallowed"]), ("10:30", ["cursor", "cursor"])],
        courts=courts,
    )
    cast(dict[str, object], cast(list[object], payload["rows"])[0])["cells"] = cells

    with pytest.raises(ValueError, match="matrix"):
        parse_everness_dom(payload, REQUESTED_DATE)


def test_everness_empty_visible_grid_returns_zero_slots() -> None:
    assert parse_everness_dom(_payload([], courts=["Court 1", "Court 2"]), REQUESTED_DATE) == ()


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("23 sept. 2026", date(2026, 9, 23)),
        ("23 sept. 2026\nMercredi", date(2026, 9, 23)),
        ("23 août 2026", date(2026, 8, 23)),
        ("23 févr. 2026", date(2026, 2, 23)),
    ],
)
def test_everness_accepts_french_date_labels(label: str, expected: date) -> None:
    assert _parse_date_label(label) == expected


@pytest.mark.parametrize(
    "label",
    [
        "31 avr. 2026",
        "23 sept. 2026x",
        "23 septfoobar 2026",
        "23 sept.. 2026",
        "23 jamais 2026",
        "23 sept. 2026\nNotaday",
        "23 sept. 2026\nMercredis",
    ],
)
def test_everness_rejects_invalid_french_date_labels(label: str) -> None:
    with pytest.raises(EvernessBrowserError, match="invalid date label"):
        _parse_date_label(label)


@pytest.mark.parametrize(
    ("label", "expected"),
    [("septembre 2026", (9, 2026)), ("sept. 2026", (9, 2026)), ("février 2026", (2, 2026))],
)
def test_everness_accepts_french_datepicker_month_labels(
    label: str, expected: tuple[int, int]
) -> None:
    assert _datepicker_month(label) == expected


@pytest.mark.parametrize("label", ["September 0000", "September 10000", "September nope"])
def test_everness_rejects_invalid_datepicker_month_year(label: str) -> None:
    with pytest.raises(EvernessBrowserError, match="invalid month label"):
        _datepicker_month(label)


def test_everness_loading_page_is_not_final_data() -> None:
    with pytest.raises(ValueError, match="loading"):
        parse_everness_dom(_payload([], loading=True), REQUESTED_DATE)


@pytest.mark.parametrize(
    "marker",
    [
        "Log in to continue",
        "CAPTCHA verification required",
        "Sign-in required",
        "Authenticate to continue",
        "Authentication required",
        "Connexion requise",
        "Se connecter pour continuer",
        "Accès refusé",
    ],
)
def test_everness_login_or_captcha_is_bounded_error(marker: str) -> None:
    with pytest.raises(ValueError, match="blocked"):
        parse_everness_dom(_payload([], visible_text=marker), REQUESTED_DATE)


def test_everness_public_generic_login_link_is_not_blocked() -> None:
    requested = date(2026, 9, 23)

    assert parse_everness_dom(
        _payload(
            [],
            date_label="23 sept. 2026\nMercredi",
            visible_text="Everness booking\nSE CONNECTER\nConnexion",
        ),
        requested,
    ) == ()


@pytest.mark.parametrize(
    "marker",
    [
        "Club is temporarily unavailable",
        "Service temporarily unavailable",
        "Ce club est temporairement indisponible",
    ],
)
def test_everness_unavailable_marker_is_bounded_error(marker: str) -> None:
    with pytest.raises(EvernessBrowserError, match="unavailable"):
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
        "authentication_visible",
        "visible_text",
    }
    assert payload["view"] == "booking"
    assert payload["date_label"] == "22 Sep 2026"
    assert payload["courts"] == ["Court 1", "Court 2"]
    assert payload["loading"] is False
    assert payload["authentication_visible"] is False
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


def test_everness_visible_script_returns_not_ready_payload_without_body(fixture_browser: Any) -> None:
    context = fixture_browser.new_context()
    page = context.new_page()
    try:
        page.goto("about:blank", wait_until="commit")
        page.evaluate("document.body.remove()")
        assert page.evaluate("document.body === null") is True

        payload = page.evaluate(_EVERNESS_VISIBLE_DOM_SCRIPT)
    finally:
        page.close()
        context.close()

    assert payload == {
        "view": "unknown",
        "date_label": "",
        "courts": [],
        "rows": [],
        "grid_fingerprint": "",
        "loading": True,
        "authentication_visible": False,
        "visible_text": "",
    }


def test_everness_visible_script_accepts_live_french_date_and_public_login_link(
    fixture_browser: Any,
) -> None:
    html = (FIXTURE_ROOT / "booking-available.html").read_text(encoding="utf-8")
    html = html.replace(
        "22 Sep 2026",
        "23 sept. 2026<br>Mercredi",
    ).replace("</main>", "<nav><a>SE CONNECTER</a><a>Connexion</a></nav></main>")

    payload = _browser_payload_html(fixture_browser, html)

    assert payload["date_label"] == "23 sept. 2026\nMercredi"
    assert payload["authentication_visible"] is False
    assert parse_everness_dom(payload, date(2026, 9, 23))


def test_everness_visible_script_filters_hidden_fixture(fixture_browser: Any) -> None:
    payload = _browser_payload(fixture_browser, "booking-hidden")

    assert payload["courts"] == ["Court 1"]
    rows = cast(list[dict[str, object]], payload["rows"])
    assert [row["time"] for row in rows] == ["09:00", "10:30"]
    assert all(len(cast(list[object], row["cells"])) == 1 for row in rows)
    observations = parse_everness_dom(payload, REQUESTED_DATE)
    assert [observation.status for observation in observations] == ["available", "unavailable"]


def test_everness_visible_script_ignores_hidden_descendant_text(fixture_browser: Any) -> None:
    payload = _browser_payload(fixture_browser, "booking-hidden-descendants")

    assert payload["date_label"] == "22 Sep 2026"
    assert payload["courts"] == ["Court 1", ""]
    rows = cast(list[dict[str, object]], payload["rows"])
    assert [row["time"] for row in rows] == ["09:00", ""]
    assert [row["cells"] for row in rows] == [
        [
            {"class": "terrainTxt cursor", "style": "", "colspan": None},
            {"class": "terrainTxt notallowed", "style": "", "colspan": None},
        ],
        [
            {"class": "terrainTxt notallowed", "style": "", "colspan": None},
            {"class": "terrainTxt cursor", "style": "", "colspan": None},
        ],
    ]
    assert "Hidden" not in repr(payload)
    with pytest.raises(EvernessBrowserError, match="missing court labels"):
        parse_everness_dom(payload, REQUESTED_DATE)


def test_everness_visible_script_detects_auth_overlay(fixture_browser: Any) -> None:
    payload = _browser_payload(fixture_browser, "booking-auth")

    assert payload["authentication_visible"] is True
    with pytest.raises(ValueError, match="blocked"):
        parse_everness_dom(payload, REQUESTED_DATE)


def test_everness_parser_rejects_authentication_payload_flag() -> None:
    payload = _payload([], visible_text="Everness booking")
    payload["authentication_visible"] = True

    with pytest.raises(ValueError, match="blocked"):
        parse_everness_dom(payload, REQUESTED_DATE)


def test_everness_visible_script_ignores_hidden_auth_controls(fixture_browser: Any) -> None:
    html = (FIXTURE_ROOT / "booking-available.html").read_text(encoding="utf-8")
    payload = _browser_payload_html(
        fixture_browser,
        html.replace("</main>", '<input type="password" hidden></main>'),
    )

    assert payload["authentication_visible"] is False


def test_everness_visible_fingerprint_ignores_date_label(fixture_browser: Any) -> None:
    html = (FIXTURE_ROOT / "booking-available.html").read_text(encoding="utf-8")
    first = _browser_payload_html(fixture_browser, html)
    second = _browser_payload_html(fixture_browser, html.replace("22 Sep 2026", "23 Sep 2026"))

    assert first["date_label"] == "22 Sep 2026"
    assert second["date_label"] == "23 Sep 2026"
    assert first["grid_fingerprint"] == second["grid_fingerprint"]


def test_everness_visible_fingerprint_includes_colspan(fixture_browser: Any) -> None:
    html = (FIXTURE_ROOT / "booking-available.html").read_text(encoding="utf-8")
    first = _browser_payload_html(fixture_browser, html)
    second = _browser_payload_html(
        fixture_browser,
        html.replace('class="terrainTxt cursor"', 'class="terrainTxt cursor" colspan="2"', 1),
    )

    assert first["grid_fingerprint"] != second["grid_fingerprint"]


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
        return self.page.locator_visible(self.selector, self.index)

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
        programming_error: type[Exception] | None = None,
        transition_error: Exception | None = None,
        french_datepicker: bool = False,
        jquery_ui_datepicker: bool = False,
        datepicker_hidden: bool = False,
        initial_payloads: list[dict[str, object]] | None = None,
        jquery_month_value: str | None = None,
        jquery_year_value: str | None = None,
        bootstrap_month_label: str | None = None,
    ) -> None:
        self.dates = dates
        self.current_date = initial_date
        self.events = events
        self.programming_error = programming_error
        self.transition_error = transition_error
        self.transition_error_raised = False
        self.date_transition_started = False
        self.french_datepicker = french_datepicker
        self.jquery_ui_datepicker = jquery_ui_datepicker
        self.datepicker_visible = not datepicker_hidden
        self.pending = list(initial_payloads or [])
        self.jquery_month_value = jquery_month_value
        self.jquery_year_value = jquery_year_value
        self.bootstrap_month_label = bootstrap_month_label
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
        if self.programming_error is not None:
            raise self.programming_error("test programming error")
        if self.date_transition_started and self.transition_error is not None and not self.transition_error_raised:
            self.transition_error_raised = True
            raise self.transition_error
        return self.payload

    def wait_for_timeout(self, timeout: int) -> None:
        self.wait_ticks += 1
        self.events.append(f"wait:{timeout}")

    def locator_count(self, selector: str) -> int:
        if selector in {"#table_reservation", "#datepicker", "#multi-language-date"}:
            return 1
        if self.jquery_ui_datepicker and selector in {
            "#datepicker .ui-datepicker-title",
            "#datepicker .ui-datepicker-month",
            "#datepicker .ui-datepicker-year",
            "#datepicker .ui-datepicker-month option:checked",
            "#datepicker .ui-datepicker-year option:checked",
            '#datepicker td[data-handler="selectDay"]',
            "#datepicker .ui-datepicker-next",
            "#datepicker .ui-datepicker-prev",
        }:
            return 31 if "selectDay" in selector else 1
        if selector == "#datepicker .day":
            return 31
        if selector == "#datepicker .datepicker-switch":
            return 1
        if selector == "#datepicker .next" or selector == "#datepicker .prev":
            return 1
        return 0

    def locator_visible(self, selector: str, index: int | None) -> bool:
        if selector == "#datepicker" or selector.startswith("#datepicker "):
            return self.datepicker_visible and self.locator_count(selector) > (index or 0)
        return self.locator_count(selector) > (index or 0)

    def locator_text(self, selector: str, index: int | None) -> str:
        if selector == "#multi-language-date":
            return str(self.dates[self.current_date][-1]["date_label"])
        if selector == "#datepicker .ui-datepicker-title":
            return self.current_date.strftime("%B %Y")
        if selector == '#datepicker td[data-handler="selectDay"]' and index is not None:
            return str(index + 1)
        if selector == "#datepicker .datepicker-switch":
            if self.bootstrap_month_label is not None:
                return self.bootstrap_month_label
            if self.french_datepicker:
                return ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")[self.current_date.month - 1] + f" {self.current_date.year}"
            return self.current_date.strftime("%B %Y")
        if selector == "#datepicker .day" and index is not None:
            return str(index + 1)
        return ""

    def locator_attribute(self, selector: str, index: int | None, name: str) -> str | None:
        if self.jquery_ui_datepicker and name == "value":
            if selector == "#datepicker .ui-datepicker-month option:checked":
                return self.jquery_month_value or str(self.current_date.month - 1)
            if selector == "#datepicker .ui-datepicker-year option:checked":
                return self.jquery_year_value or str(self.current_date.year)
        if self.jquery_ui_datepicker and selector == '#datepicker td[data-handler="selectDay"]':
            if name == "data-month":
                return str(self.current_date.month - 1)
            if name == "data-year":
                return str(self.current_date.year)
        if selector == "#datepicker .day" and index is not None and name == "class":
            return "day"
        return None

    def click(self, selector: str, index: int | None) -> None:
        self.events.append(f"click:{selector}:{index if index is not None else ''}")
        if selector == "#multi-language-date":
            self.datepicker_visible = True
            return
        if selector == '#datepicker td[data-handler="selectDay"]' and index is not None:
            selected = date(self.current_date.year, self.current_date.month, index + 1)
            self.current_date = selected
            self.date_transition_started = True
            self.pending = [dict(payload) for payload in self.dates[selected][:-1]]
        if selector == "#datepicker .day" and index is not None:
            selected = date(self.current_date.year, self.current_date.month, index + 1)
            self.current_date = selected
            self.date_transition_started = True
            self.pending = [dict(payload) for payload in self.dates[selected][:-1]]
        elif selector == "#datepicker .next":
            month = self.current_date.month % 12 + 1
            year = self.current_date.year + (self.current_date.month == 12)
            self.current_date = date(year, month, 1)
        elif selector == "#datepicker .prev":
            month = self.current_date.month - 1 or 12
            year = self.current_date.year - (self.current_date.month == 1)
            self.current_date = date(year, month, 1)
        elif selector == "#datepicker .ui-datepicker-next":
            month = self.current_date.month % 12 + 1
            year = self.current_date.year + (self.current_date.month == 12)
            self.current_date = date(year, month, 1)
        elif selector == "#datepicker .ui-datepicker-prev":
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
    programming_error: type[Exception] | None = None,
    transition_error: Exception | None = None,
    timeout_ms: int = 15_000,
    french_datepicker: bool = False,
    jquery_ui_datepicker: bool = False,
    datepicker_hidden: bool = False,
    initial_payloads: list[dict[str, object]] | None = None,
    jquery_month_value: str | None = None,
    jquery_year_value: str | None = None,
    bootstrap_month_label: str | None = None,
) -> tuple[EvernessBrowserConnector, _FakeEvernessPage, _FakeEvernessContext]:
    page = _FakeEvernessPage(
        dates,
        initial_date,
        events,
        programming_error=programming_error,
        transition_error=transition_error,
        french_datepicker=french_datepicker,
        jquery_ui_datepicker=jquery_ui_datepicker,
        datepicker_hidden=datepicker_hidden,
        initial_payloads=initial_payloads,
        jquery_month_value=jquery_month_value,
        jquery_year_value=jquery_year_value,
        bootstrap_month_label=bootstrap_month_label,
    )
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

    assert "click:#datepicker .day:21" not in events
    assert "click:#datepicker .day:22" in events
    assert not any("terrainTxt" in event or "submit" in event.lower() for event in events)


def test_everness_connector_opens_hidden_datepicker_after_date_label_click() -> None:
    events: list[str] = []
    initial = date(2026, 9, 22)
    requested = date(2026, 9, 23)
    dates = {
        initial: [_everness_payload(initial, fingerprint="grid-1", rows=[])],
        requested: [_everness_payload(requested, fingerprint="grid-2", rows=[])],
    }
    connector, _page, _context = _everness_connector(
        dates,
        events,
        initial_date=initial,
        datepicker_hidden=True,
    )

    connector.collect(
        _everness_location(),
        run_id="run-everness",
        window_start=requested,
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    date_label_click = "click:#multi-language-date:"
    day_click = "click:#datepicker .day:22"
    assert date_label_click in events
    assert day_click in events
    assert events.index(date_label_click) < events.index(day_click)


def test_everness_connector_accepts_french_visible_dates_and_datepicker() -> None:
    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    dates = {
        first: [_everness_payload(first, fingerprint="grid-1", rows=[])],
        second: [
            {
                **_everness_payload(second, fingerprint="grid-2", rows=[]),
                "date_label": "23 sept. 2026",
            }
        ],
    }
    dates[first][0]["date_label"] = "22 sept. 2026"
    connector, _page, _context = _everness_connector(
        dates, events, initial_date=first, french_datepicker=True
    )

    connector.collect(
        _everness_location(),
        run_id="run-everness",
        window_start=first,
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert "click:#datepicker .day:22" in events


def test_everness_connector_supports_jquery_ui_datepicker() -> None:
    events: list[str] = []
    initial = date(2026, 8, 1)
    requested = date(2026, 9, 22)
    dates = {
        initial: [_everness_payload(initial, fingerprint="initial", rows=[])],
        requested: [_everness_payload(requested, fingerprint="requested", rows=[])],
    }
    connector, _page, _context = _everness_connector(
        dates,
        events,
        initial_date=initial,
        jquery_ui_datepicker=True,
    )

    connector.collect(
        _everness_location(),
        run_id="run-everness",
        window_start=requested,
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert "click:#datepicker .ui-datepicker-next:" in events
    assert 'click:#datepicker td[data-handler="selectDay"]:21' in events
    assert not any("terrainTxt" in event or "submit" in event.lower() for event in events)


@pytest.mark.parametrize(
    ("jquery_month_value", "jquery_year_value"),
    [("foo", "2026"), ("8", "0000"), ("8", "10000")],
)
def test_everness_connector_rejects_invalid_jquery_ui_selected_month_or_year(
    jquery_month_value: str, jquery_year_value: str
) -> None:
    events: list[str] = []
    initial = date(2026, 8, 1)
    requested = date(2026, 9, 22)
    payload = _everness_payload(initial, fingerprint="initial", rows=[])
    connector, page, context = _everness_connector(
        {initial: [payload], requested: [_everness_payload(requested, fingerprint="requested", rows=[])]},
        events,
        initial_date=initial,
        jquery_ui_datepicker=True,
        jquery_month_value=jquery_month_value,
        jquery_year_value=jquery_year_value,
    )

    with pytest.raises(EvernessBrowserError, match="invalid selected month or year"):
        connector.collect(
            _everness_location(),
            run_id="run-everness",
            window_start=requested,
            window_end=date(2026, 9, 23),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()

    assert page.closed and context.closed


def test_everness_connector_rejects_invalid_bootstrap_month_year_before_date() -> None:
    events: list[str] = []
    initial = date(2026, 8, 1)
    requested = date(2026, 9, 22)
    connector, page, context = _everness_connector(
        {initial: [_everness_payload(initial, fingerprint="initial", rows=[])]},
        events,
        initial_date=initial,
        bootstrap_month_label="September 0000",
    )

    with pytest.raises(EvernessBrowserError, match="invalid month label"):
        connector.collect(
            _everness_location(),
            run_id="run-everness",
            window_start=requested,
            window_end=date(2026, 9, 23),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()

    assert page.closed and context.closed


def test_everness_connector_retries_playwright_error_during_date_transition() -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError as error:
        pytest.skip(f"Playwright is unavailable: {error}")

    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    dates = {
        first: [_everness_payload(first, fingerprint="grid-1", rows=[])],
        second: [
            _everness_payload(
                second,
                fingerprint="grid-2",
                rows=[("09:00", ["cursor"]), ("10:30", ["notallowed"])],
            )
        ],
    }
    connector, page, _context = _everness_connector(
        dates,
        events,
        initial_date=first,
        transition_error=PlaywrightError(
            "Execution context was destroyed, most likely because of a navigation"
        ),
    )

    result = connector.collect(
        _everness_location(),
        run_id="run-everness",
        window_start=second,
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert result.run.status == "success"
    assert [slot.status for slot in result.slots] == ["available", "unavailable"]
    assert page.transition_error_raised


def test_everness_connector_does_not_retry_generic_playwright_error() -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError as error:
        pytest.skip(f"Playwright is unavailable: {error}")

    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    dates = {
        first: [_everness_payload(first, fingerprint="grid-1", rows=[])],
        second: [_everness_payload(second, fingerprint="grid-2", rows=[])],
    }
    connector, page, _context = _everness_connector(
        dates,
        events,
        initial_date=first,
        transition_error=PlaywrightError("Target page, context or browser has been closed"),
    )

    with pytest.raises(EvernessSourceError, match="browser navigation or extraction failed"):
        connector.collect(
            _everness_location(),
            run_id="run-everness",
            window_start=second,
            window_end=date(2026, 9, 24),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()

    assert page.transition_error_raised
    assert page.wait_ticks == 0


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


def test_everness_connector_rejects_stale_real_script_grid(
    fixture_browser: Any,
) -> None:
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    html = (FIXTURE_ROOT / "booking-available.html").read_text(encoding="utf-8")
    first_payload = _browser_payload_html(fixture_browser, html)
    second_payload = _browser_payload_html(
        fixture_browser, html.replace("22 Sep 2026", "23 Sep 2026")
    )
    assert first_payload["date_label"] == "22 Sep 2026"
    assert second_payload["date_label"] == "23 Sep 2026"
    assert first_payload["grid_fingerprint"] == second_payload["grid_fingerprint"]

    events: list[str] = []
    connector, page, context = _everness_connector(
        {first: [first_payload], second: [second_payload]},
        events,
        initial_date=first,
        timeout_ms=200,
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
    assert "click:#datepicker .day:21" not in events
    assert "click:#datepicker .day:22" in events


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


def test_everness_connector_waits_for_final_stable_grid_after_transient_valid_grid() -> None:
    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    dates = {
        first: [_everness_payload(first, fingerprint="grid-1", rows=[])],
        second: [
            _everness_payload(
                second,
                fingerprint="transient",
                rows=[("09:00", ["cursor"]), ("10:30", ["cursor"])],
            ),
            _everness_payload(
                second,
                fingerprint="final",
                rows=[("09:00", ["notallowed"]), ("10:30", ["cursor"])],
            ),
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

    assert len(result.slots) == 2
    assert [slot.status for slot in result.slots] == ["unavailable", "available"]


def test_everness_connector_waits_for_initial_final_stable_grid() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    baseline = _everness_payload(requested, fingerprint="initial", rows=[])
    transient = _everness_payload(
        requested,
        fingerprint="transient",
        rows=[("09:00", ["cursor"]), ("10:30", ["cursor"])],
    )
    final = _everness_payload(
        requested,
        fingerprint="final",
        rows=[("09:00", ["notallowed"]), ("10:30", ["cursor"])],
    )
    connector, _page, _context = _everness_connector(
        {requested: [final]},
        events,
        initial_date=requested,
        initial_payloads=[baseline, baseline, transient, final],
    )

    result = connector.collect(
        _everness_location(),
        run_id="run-everness",
        window_start=requested,
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert [slot.status for slot in result.slots] == ["unavailable", "available"]


def test_everness_connector_resets_stability_after_non_requested_payload() -> None:
    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    other = date(2026, 9, 24)
    dates = {
        first: [_everness_payload(first, fingerprint="old", rows=[])],
        second: [
            _everness_payload(second, fingerprint="grid-1", rows=[]),
            _everness_payload(other, fingerprint="grid-1", rows=[]),
            _everness_payload(second, fingerprint="grid-1", rows=[]),
        ],
    }
    connector, page, context = _everness_connector(
        dates, events, initial_date=first, timeout_ms=300
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

    assert page.wait_ticks == 4
    assert page.closed and context.closed


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
        dates, events, initial_date=REQUESTED_DATE, programming_error=TypeError
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


def test_everness_runtime_errors_propagate_and_cleanup() -> None:
    events: list[str] = []
    dates = {REQUESTED_DATE: [_everness_payload(REQUESTED_DATE, fingerprint="grid-1", rows=[])]}
    connector, page, context = _everness_connector(
        dates, events, initial_date=REQUESTED_DATE, programming_error=RuntimeError
    )

    with pytest.raises(RuntimeError, match="programming"):
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


def test_everness_connector_maps_normalization_error(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    dates = {REQUESTED_DATE: [_everness_payload(REQUESTED_DATE, fingerprint="grid-1", rows=[])]}
    connector, page, context = _everness_connector(
        dates, events, initial_date=REQUESTED_DATE
    )

    def fail_normalization(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        raise PlaytomicSourceError("conflicting duplicate slot hash")

    monkeypatch.setattr(everness_browser, "parse_everness_observations", fail_normalization)

    with pytest.raises(EvernessSourceError, match="duplicate"):
        connector.collect(
            _everness_location(),
            run_id="run-everness",
            window_start=REQUESTED_DATE,
            window_end=date(2026, 9, 23),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()

    assert page.closed and context.closed
