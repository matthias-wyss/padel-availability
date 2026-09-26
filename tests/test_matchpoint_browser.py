from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Self, cast

import pytest
from playwright.sync_api import Browser, sync_playwright

from padel_availability.availability import AvailabilitySlot
from padel_availability.connectors.matchpoint import load_matchpoint_sources
from padel_availability.connectors.matchpoint_browser import (
    _MATCHPOINT_VISIBLE_DOM_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    MatchpointBrowserConnector,
    parse_matchpoint_dom,
    parse_matchpoint_observations,
)
from padel_availability.connectors.playtomic_browser import BrowserFactory, BrowserSlotObservation
from padel_availability.inventory import load_locations

REQUESTED_DATE = date(2026, 9, 25)
ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/matchpoint/dom"


def _payload(
    slots: list[dict[str, object]],
    *,
    view: str = "booking",
    date_value: str = "2026-09-25",
    center: str = "Bernex",
    courts: list[str] | None = None,
    loading: bool = False,
    authentication_visible: bool = False,
    empty_grid: bool = False,
) -> dict[str, object]:
    return {
        "view": view,
        "date": date_value,
        "center": center,
        "courts": courts if courts is not None else ["Court 1"],
        "slots": slots,
        "loading": loading,
        "authentication_visible": authentication_visible,
        "empty_grid": empty_grid,
    }


def _parse(
    payload: object,
    requested_date: date,
    *,
    expected_center: str | None = None,
) -> tuple[BrowserSlotObservation, ...]:
    return parse_matchpoint_dom(payload, requested_date, expected_center=expected_center)


def _normalize(
    observations: tuple[BrowserSlotObservation, ...],
    *,
    window_start: date,
    window_end: date,
) -> tuple[AvailabilitySlot, ...]:
    return parse_matchpoint_observations(
        observations,
        location_id="urban-padel-lausanne",
        run_id="run-matchpoint",
        window_start=window_start,
        window_end=window_end,
    )


def fixture_browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--disable-dev-shm-usage"],
        )
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    yield from fixture_browser()


def _visible_dom_script() -> str:
    return _MATCHPOINT_VISIBLE_DOM_SCRIPT


def _browser_payload(browser: Browser, fixture_name: str) -> dict[str, object]:
    page = browser.new_page()
    try:
        page.set_content((FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8"))
        payload = page.evaluate(_visible_dom_script())
        assert isinstance(payload, dict)
        return cast(dict[str, object], payload)
    finally:
        page.close()


def test_matchpoint_parser_preserves_variable_slot_durations_and_statuses() -> None:
    observations = _parse(
        _payload(
            [
                {
                    "court": "Court 1",
                    "start": "09:00",
                    "end": "10:30",
                    "state": "available",
                },
                {"court": "Court 1", "start": "10:30", "end": "11:30", "state": "booked"},
                {
                    "court": "Court 1",
                    "start": "11:30",
                    "end": "13:00",
                    "state": "open_match",
                },
                {
                    "court": "Court 1",
                    "start": "13:00",
                    "end": "14:00",
                    "state": "future-marker",
                },
            ]
        ),
        REQUESTED_DATE,
    )

    assert [item.status for item in observations] == [
        "available",
        "unavailable",
        "unavailable",
        "unknown",
    ]
    assert (observations[0].starts_at, observations[0].ends_at) == (
        "2026-09-25T09:00:00+02:00",
        "2026-09-25T10:30:00+02:00",
    )
    assert observations[1].ends_at == "2026-09-25T11:30:00+02:00"
    assert all(item.court_label == "Court 1" for item in observations)


def test_visible_padelconnect_grid_extracts_sanitized_public_slots(browser: Browser) -> None:
    payload = _browser_payload(browser, "padelconnect-bernex.html")

    assert payload["view"] == "booking"
    assert payload["date"] == "2026-09-25"
    assert payload["center"] == "Bernex"
    assert payload["courts"] == ["Bernex Terrain Bleu", "Bernex Terrain Vert"]
    slots = cast(list[dict[str, object]], payload["slots"])
    assert [slot["state"] for slot in slots] == ["available", "booked", "open_match"]
    assert slots[0]["start"] == "09:00"
    assert slots[0]["end"] == "10:30"
    assert "text" not in slots[0]
    assert "COMPLET" not in repr(payload)
    assert payload["authentication_visible"] is False


def test_visible_urban_matchpoint_grid_maps_cell_geometry(browser: Browser) -> None:
    payload = _browser_payload(browser, "urban-padel.html")

    assert payload["date"] == "2026-09-25"
    assert payload["center"] == "Urban Padel Sàrl"
    assert payload["courts"] == ["Terrain 1", "Terrain 2", "Terrain 3", "Terrain 4"]
    slots = cast(list[dict[str, object]], payload["slots"])
    assert [(slot["court"], slot["start"], slot["end"], slot["state"]) for slot in slots] == [
        ("Terrain 1", "09:00", "10:00", "available"),
        ("Terrain 2", "09:00", "10:30", "booked"),
        ("Terrain 3", "09:00", "10:30", "open_match"),
        ("Terrain 4", "09:00", "10:30", "available"),
    ]


@pytest.mark.parametrize(
    ("fixture_name", "center", "courts"),
    [
        ("padelconnect-evaux.html", "Parc des Evaux", ["Evaux 1", "Evaux 2"]),
        ("padelconnect-jonction.html", "Jonction", ["Jonction 1", "Jonction 2"]),
    ],
)
def test_visible_padelconnect_center_fixtures_extract_public_grid(
    browser: Browser,
    fixture_name: str,
    center: str,
    courts: list[str],
) -> None:
    payload = _browser_payload(browser, fixture_name)

    assert payload["view"] == "booking"
    assert payload["center"] == center
    assert payload["courts"] == courts
    assert payload["authentication_visible"] is False
    assert payload["slots"]


def test_matchpoint_parser_accepts_explicit_empty_grid() -> None:
    assert _parse(_payload([], empty_grid=True), REQUESTED_DATE) == ()


def test_matchpoint_parser_rejects_unexpected_visible_center() -> None:
    with pytest.raises(ValueError, match="center"):
        _parse(
            _payload([], center="Jonction", empty_grid=True),
            REQUESTED_DATE,
            expected_center="Parc des Evaux",
        )


@pytest.mark.parametrize(
    "payload,match",
    [
        (_payload([], view="login"), "booking view"),
        (_payload([], date_value="2026-09-26"), "date"),
        (_payload([], loading=True), "loading"),
        (_payload([], authentication_visible=True), "authentication"),
        (_payload([]), "availability state"),
        (
            _payload(
                [{"court": "Unknown", "start": "09:00", "end": "10:00", "state": "available"}]
            ),
            "court",
        ),
        (
            _payload([{"court": "Court 1", "start": "9:00", "end": "10:00", "state": "available"}]),
            "time",
        ),
        (
            _payload(
                [{"court": "Court 1", "start": "09:00", "end": "09:00", "state": "available"}]
            ),
            "duration",
        ),
    ],
)
def test_matchpoint_parser_rejects_non_final_or_malformed_grid(payload: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _parse(payload, REQUESTED_DATE)


def test_matchpoint_parser_rejects_duplicate_visible_slots() -> None:
    slot: dict[str, object] = {
        "court": "Court 1",
        "start": "09:00",
        "end": "10:30",
        "state": "available",
    }
    with pytest.raises(ValueError, match="duplicate"):
        _parse(_payload([slot, slot]), REQUESTED_DATE)


def test_matchpoint_parser_rejects_partial_court_matrix() -> None:
    payload = _payload(
        [{"court": "Court 1", "start": "09:00", "end": "10:00", "state": "available"}],
        courts=["Court 1", "Court 2"],
    )

    with pytest.raises(ValueError, match="matrix"):
        _parse(payload, REQUESTED_DATE)


def test_matchpoint_parser_rejects_participant_fields() -> None:
    slot: dict[str, object] = {
        "court": "Court 1",
        "start": "09:00",
        "end": "10:30",
        "state": "booked",
        "player_name": "must not be collected",
    }

    with pytest.raises(ValueError, match="fields"):
        _parse(_payload([slot]), REQUESTED_DATE)


def test_matchpoint_observations_normalize_to_utc_and_filter_window() -> None:
    observations = _parse(
        _payload(
            [
                {
                    "court": "Court 1",
                    "start": "09:00",
                    "end": "10:30",
                    "state": "available",
                }
            ]
        ),
        REQUESTED_DATE,
    )

    slots = _normalize(observations, window_start=REQUESTED_DATE, window_end=date(2026, 9, 26))

    assert len(slots) == 1
    assert slots[0].starts_at == "2026-09-25T07:00:00Z"
    assert slots[0].ends_at == "2026-09-25T08:30:00Z"
    assert slots[0].timezone == "Europe/Zurich"


def test_matchpoint_parser_rejects_ambiguous_dst_wall_time() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        _parse(
            _payload(
                [
                    {
                        "court": "Court 1",
                        "start": "02:30",
                        "end": "03:30",
                        "state": "available",
                    }
                ],
                date_value="2026-10-25",
            ),
            date(2026, 10, 25),
        )


class _FakeMatchpointLocator:
    def __init__(self, page: _FakeMatchpointPage, selector: str) -> None:
        self.page = page
        self.selector = selector

    def count(self) -> int:
        if self.selector == "button.manyana":
            return 1
        if self.selector == 'input.boton-userpreferences[value="Décliner"]:visible':
            return int(self.page.cookie_banner)
        if self.selector == 'input.boton-userpreferences[value="Decline"]:visible':
            return 0
        if self.selector == ".banner-block-screen":
            return int(self.page.cookie_banner)
        raise AssertionError(f"unexpected page control: {self.selector}")

    def is_visible(self) -> bool:
        if self.selector == "button.manyana":
            return not self.page.cookie_banner
        if self.selector in {
            'input.boton-userpreferences[value="Décliner"]:visible',
            ".banner-block-screen",
        }:
            return self.page.cookie_banner
        return False

    def click(self) -> None:
        if self.selector == 'input.boton-userpreferences[value="Décliner"]:visible':
            assert self.page.cookie_banner
            self.page.events.append("decline_optional_cookies")
            self.page.cookie_banner = False
        elif self.selector == "button.manyana":
            assert not self.page.cookie_banner
            self.page.events.append("next_day")
            self.page.current_date += timedelta(days=1)
            self.page.partial_grid_on_next_read = True
        else:
            raise AssertionError(f"unexpected page control: {self.selector}")


class _FakeMatchpointPage:
    def __init__(self, events: list[str], current_date: date) -> None:
        self.events = events
        self.current_date = current_date
        self.view = "booking"
        self.center = "Bernex"
        self.invalid_slot_time = False
        self.partial_grid_on_next_read = False
        self.cookie_banner = True
        self.closed = False
        self.url: str | None = None

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        del timeout
        self.url = url
        self.events.append(f"goto:{wait_until}")

    def locator(self, selector: str) -> _FakeMatchpointLocator:
        if selector not in {
            "button.manyana",
            'input.boton-userpreferences[value="Décliner"]:visible',
            'input.boton-userpreferences[value="Decline"]:visible',
            ".banner-block-screen",
        }:
            raise AssertionError(f"unexpected page control: {selector}")
        return _FakeMatchpointLocator(self, selector)

    def wait_for_timeout(self, _timeout: int) -> None:
        pass

    def evaluate(self, _script: str, _argument: object = None) -> object:
        if self.partial_grid_on_next_read:
            self.partial_grid_on_next_read = False
            return _payload([], date_value=self.current_date.isoformat(), courts=[])
        payload = _payload(
            [
                {
                    "court": "Bernex Terrain Bleu",
                    "start": "09:00",
                    "end": "10:30",
                    "state": "available",
                },
                {
                    "court": "Bernex Terrain Vert",
                    "start": "09:00",
                    "end": "10:30",
                    "state": "available",
                },
            ],
            date_value=self.current_date.isoformat(),
            center=self.center,
            courts=["Bernex Terrain Bleu", "Bernex Terrain Vert"],
        )
        payload["view"] = self.view
        if self.invalid_slot_time:
            cast(list[dict[str, object]], payload["slots"])[0]["start"] = "9:00"
        return payload

    def close(self) -> None:
        self.closed = True
        self.events.append("page_close")


class _FakeMatchpointContext:
    def __init__(self, page: _FakeMatchpointPage, events: list[str]) -> None:
        self.page = page
        self.events = events
        self.closed = False

    def new_page(self) -> _FakeMatchpointPage:
        self.events.append("new_page")
        return self.page

    def close(self) -> None:
        self.closed = True
        self.events.append("context_close")


class _FakeMatchpointBrowser:
    def __init__(self, context: _FakeMatchpointContext, events: list[str]) -> None:
        self.context = context
        self.events = events

    def __enter__(self) -> Self:
        self.events.append("browser_enter")
        return self

    def __exit__(self, *_args: object) -> None:
        self.events.append("browser_exit")

    def new_context(self) -> _FakeMatchpointContext:
        self.events.append("new_context")
        return self.context


def test_matchpoint_connector_uses_public_grid_and_visible_next_day_navigation() -> None:
    sources = load_matchpoint_sources(ROOT / "data/matchpoint_sources.json")
    bernex_source = next(source for source in sources if source.location_id == "bernex")
    location = next(
        location
        for location in load_locations(ROOT / "data/verified_locations.json")
        if location.location_id == "bernex"
    )
    events: list[str] = []
    page = _FakeMatchpointPage(events, REQUESTED_DATE)
    context = _FakeMatchpointContext(page, events)
    browser = _FakeMatchpointBrowser(context, events)
    connector = MatchpointBrowserConnector(
        sources,
        browser_factory=cast(BrowserFactory, lambda: browser),
    )

    result = connector.collect(
        location,
        run_id="run-bernex",
        window_start=REQUESTED_DATE,
        window_end=date(2026, 9, 27),
        collected_at="2026-09-25T00:00:00Z",
    )
    connector.close()

    assert page.url == bernex_source.booking_url
    assert events.count("decline_optional_cookies") == 1
    assert events.count("next_day") == 1
    assert events[-3:] == ["page_close", "context_close", "browser_exit"]
    assert len(result.slots) == 4
    assert [slot.starts_at for slot in result.slots] == [
        "2026-09-25T07:00:00Z",
        "2026-09-25T07:00:00Z",
        "2026-09-26T07:00:00Z",
        "2026-09-26T07:00:00Z",
    ]


def test_matchpoint_connector_closes_page_and_context_after_parser_error() -> None:
    sources = load_matchpoint_sources(ROOT / "data/matchpoint_sources.json")
    location = next(
        location
        for location in load_locations(ROOT / "data/verified_locations.json")
        if location.location_id == "bernex"
    )
    events: list[str] = []
    page = _FakeMatchpointPage(events, REQUESTED_DATE)
    page.invalid_slot_time = True
    context = _FakeMatchpointContext(page, events)
    browser = _FakeMatchpointBrowser(context, events)
    connector = MatchpointBrowserConnector(
        sources,
        browser_factory=cast(BrowserFactory, lambda: browser),
    )

    try:
        with pytest.raises(ValueError, match="time"):
            connector.collect(
                location,
                run_id="run-bernex",
                window_start=REQUESTED_DATE,
                window_end=date(2026, 9, 26),
                collected_at="2026-09-25T00:00:00Z",
            )
    finally:
        connector.close()

    assert page.closed is True
    assert context.closed is True
    assert events.count("decline_optional_cookies") == 1
    assert events[-1] == "browser_exit"


def test_matchpoint_connector_rejects_wrong_visible_center() -> None:
    sources = load_matchpoint_sources(ROOT / "data/matchpoint_sources.json")
    location = next(
        location
        for location in load_locations(ROOT / "data/verified_locations.json")
        if location.location_id == "bernex"
    )
    events: list[str] = []
    page = _FakeMatchpointPage(events, REQUESTED_DATE)
    page.center = "Jonction"
    context = _FakeMatchpointContext(page, events)
    browser = _FakeMatchpointBrowser(context, events)
    connector = MatchpointBrowserConnector(
        sources,
        browser_factory=cast(BrowserFactory, lambda: browser),
    )

    try:
        with pytest.raises(ValueError, match="center"):
            connector.collect(
                location,
                run_id="run-bernex",
                window_start=REQUESTED_DATE,
                window_end=date(2026, 9, 26),
                collected_at="2026-09-25T00:00:00Z",
            )
    finally:
        connector.close()


def test_matchpoint_connector_does_not_decline_when_no_cookie_banner() -> None:
    sources = load_matchpoint_sources(ROOT / "data/matchpoint_sources.json")
    location = next(
        location
        for location in load_locations(ROOT / "data/verified_locations.json")
        if location.location_id == "bernex"
    )
    events: list[str] = []
    page = _FakeMatchpointPage(events, REQUESTED_DATE)
    page.cookie_banner = False
    context = _FakeMatchpointContext(page, events)
    browser = _FakeMatchpointBrowser(context, events)
    connector = MatchpointBrowserConnector(
        sources,
        browser_factory=cast(BrowserFactory, lambda: browser),
    )

    try:
        result = connector.collect(
            location,
            run_id="run-bernex",
            window_start=REQUESTED_DATE,
            window_end=date(2026, 9, 26),
            collected_at="2026-09-25T00:00:00Z",
        )
    finally:
        connector.close()

    assert result.run.status == "success"
    assert "decline_optional_cookies" not in events
