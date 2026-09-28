from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Self, cast

import pytest

from padel_availability.connectors.padelfirst import PadelFirstSource
from padel_availability.connectors.padelfirst_browser import (
    _PADEL_FIRST_VISIBLE_DOM_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    PadelFirstBrowserConnector,
    PadelFirstBrowserError,
    parse_padelfirst_dom,
    parse_padelfirst_observations,
)
from padel_availability.connectors.playtomic_browser import BrowserFactory
from padel_availability.inventory import load_locations
from padel_availability.models import LocationRecord

REQUESTED_DATE = date(2026, 9, 24)
ROOT = Path(__file__).parents[1]


def _payload(
    rows: list[tuple[str, list[str]]],
    *,
    date_value: str = "2026-09-24",
    courts: list[str] | None = None,
    visible_text: str = "Vernier disponible",
    loading: bool = False,
    authentication_visible: bool = False,
) -> dict[str, object]:
    court_labels = courts or ["Court 1", "Court 2"]
    return {
        "view": "scheduler",
        "date": date_value,
        "courts": court_labels,
        "rows": [
            {
                "time": row_time,
                "cells": [
                    {
                        "external_id": f"{index + 5}_{row_time.replace(':', '')}",
                        "class": state,
                        "checkin": date_value,
                        "hour": row_time,
                        "court_id": str(index + 5),
                    }
                    for index, state in enumerate(states)
                ],
            }
            for row_time, states in rows
        ],
        "calendar_available_dates": [date_value],
        "loading": loading,
        "authentication_visible": authentication_visible,
        "visible_text": visible_text,
    }


def test_padelfirst_available_scheduler_extracts_visible_cells() -> None:
    observations = parse_padelfirst_dom(
        _payload(
            [
                ("09:00", ["status available", "status unavailable"]),
                ("10:30", ["match-block status approved", "status booked"]),
            ]
        ),
        REQUESTED_DATE,
    )

    assert len(observations) == 4
    assert [observation.status for observation in observations] == [
        "available",
        "unavailable",
        "unavailable",
        "unavailable",
    ]
    assert [observation.court_label for observation in observations] == [
        "Court 1",
        "Court 2",
        "Court 1",
        "Court 2",
    ]
    assert observations[0].external_id == "5_0900"
    assert observations[0].starts_at == "2026-09-24T09:00:00+02:00"
    assert observations[0].ends_at == "2026-09-24T10:30:00+02:00"


def test_padelfirst_scheduler_accepts_public_login_navigation_text() -> None:
    observations = parse_padelfirst_dom(
        _payload(
            [("09:00", ["status available", "status available"])],
            visible_text="Connexion S’identifier S’inscrire Vernier disponible",
        ),
        REQUESTED_DATE,
    )

    assert len(observations) == 2


@pytest.mark.parametrize(
    "payload,match",
    [
        (_payload([], loading=True), "loading"),
        (_payload([], authentication_visible=True), "authentication"),
        (_payload([], visible_text="CAPTCHA verify you are human"), "login or CAPTCHA"),
        ({**_payload([]), "view": "booking"}, "scheduler"),
        ({**_payload([]), "date": "2026-09-25"}, "date"),
    ],
)
def test_padelfirst_rejects_non_final_scheduler_states(
    payload: dict[str, object], match: str
) -> None:
    with pytest.raises(PadelFirstBrowserError, match=match):
        parse_padelfirst_dom(payload, REQUESTED_DATE)


def test_padelfirst_rejects_partial_visible_matrix() -> None:
    payload = _payload([("09:00", ["status available"])])

    with pytest.raises(PadelFirstBrowserError, match="matrix"):
        parse_padelfirst_dom(payload, REQUESTED_DATE)


def test_padelfirst_rejects_invalid_visible_time() -> None:
    payload = _payload([("9:00", ["status available", "status available"])])

    with pytest.raises(PadelFirstBrowserError, match="time"):
        parse_padelfirst_dom(payload, REQUESTED_DATE)


def test_padelfirst_empty_scheduler_returns_zero_observations() -> None:
    assert parse_padelfirst_dom(_payload([]), REQUESTED_DATE) == ()


def test_padelfirst_observations_normalize_to_utc_and_window() -> None:
    observations = parse_padelfirst_dom(
        _payload([("09:00", ["status available", "status available"])]),
        REQUESTED_DATE,
    )

    slots = parse_padelfirst_observations(
        observations,
        location_id="vernier",
        run_id="run-vernier",
        window_start=REQUESTED_DATE,
        window_end=date(2026, 9, 25),
    )

    assert len(slots) == 2
    assert slots[0].starts_at == "2026-09-24T07:00:00Z"
    assert slots[0].ends_at == "2026-09-24T08:30:00Z"
    assert all(slot.timezone == "Europe/Zurich" for slot in slots)


def test_padelfirst_parser_accepts_unknown_visible_state() -> None:
    observations = parse_padelfirst_dom(
        _payload([("09:00", ["status pending", "status available"])]),
        REQUESTED_DATE,
    )

    assert [observation.status for observation in observations] == ["unknown", "available"]


def test_padelfirst_missing_external_id_uses_shared_hash() -> None:
    payload = _payload([("09:00", ["status available", "status available"])])
    cells = cast(
        list[object], cast(dict[str, object], cast(list[object], payload["rows"])[0])["cells"]
    )
    cast(dict[str, object], cells[0])["external_id"] = None

    observations = parse_padelfirst_dom(payload, REQUESTED_DATE)
    slots = parse_padelfirst_observations(
        observations,
        location_id="vernier",
        run_id="run-vernier",
        window_start=REQUESTED_DATE,
        window_end=date(2026, 9, 25),
    )

    assert slots[0].external_id is None
    assert slots[0].slot_key


def _scheduler_payload(requested_date: date) -> dict[str, object]:
    return _payload(
        [("09:00", ["status available", "status unavailable"])],
        date_value=requested_date.isoformat(),
    )


class _FakePadelFirstLocator:
    def __init__(self, page: _FakePadelFirstPage, selector: str, index: int = 0) -> None:
        self.page = page
        self.selector = selector
        self.index = index

    def count(self) -> int:
        if self.selector == "#calendar":
            return 1
        if self.selector == "#calendar .fc-event.available":
            return len(self.page.event_dates) if self.page.mode == "calendar" else 0
        if self.selector in {"#calendar .fc-next-button", "#calendar .fc-prev-button"}:
            return 1
        if self.selector == "#scheduler .close-modal":
            return 1 if self.page.mode == "scheduler" else 0
        return 0

    def nth(self, index: int) -> _FakePadelFirstLocator:
        return _FakePadelFirstLocator(self.page, self.selector, index)

    def is_visible(self) -> bool:
        return self.count() == 1 or (
            self.selector == "#calendar .fc-event.available"
            and self.index < len(self.page.event_dates)
        )

    def inner_text(self) -> str:
        return ""

    def get_attribute(self, _name: str) -> str | None:
        return None

    def evaluate(self, _expression: str, _arg: object = None) -> object:
        if self.selector == "#calendar .fc-event.available":
            return self.page.event_dates[self.index]
        return None

    def click(self) -> None:
        if self.selector == "#calendar .fc-event.available":
            self.page.events.append(f"click:event:{self.page.event_dates[self.index]}")
            self.page.mode = "scheduler"
            self.page.scheduler_date = date.fromisoformat(self.page.event_dates[self.index])
        elif self.selector == "#scheduler .close-modal":
            self.page.events.append("click:close")
            self.page.mode = "calendar"
        elif self.selector == "#calendar .fc-next-button":
            self.page.events.append("click:calendar-next")
            self.page.month = "next"
        elif self.selector == "#calendar .fc-prev-button":
            self.page.events.append("click:calendar-prev")
            self.page.month = "previous"


class _FakePadelFirstPage:
    def __init__(
        self,
        events: list[str],
        calendar_dates: dict[str, tuple[str, ...]],
        event_dates: dict[str, tuple[str, ...]],
        schedulers: dict[date, dict[str, object]],
    ) -> None:
        self.events = events
        self.calendar_dates = calendar_dates
        self.event_dates_by_month = event_dates
        self.schedulers = schedulers
        self.month = "current"
        self.mode = "calendar"
        self.scheduler_date: date | None = None
        self.closed = False
        self.wait_until: str | None = None

    @property
    def event_dates(self) -> tuple[str, ...]:
        return self.event_dates_by_month[self.month]

    def goto(self, _url: str, *, wait_until: str, timeout: int) -> object:
        del timeout
        self.wait_until = wait_until
        self.events.append("goto")
        return None

    def locator(self, selector: str) -> _FakePadelFirstLocator:
        return _FakePadelFirstLocator(self, selector)

    def wait_for_timeout(self, _timeout: int) -> None:
        pass

    def evaluate(self, expression: str, _arg: object = None) -> object:
        if expression != _PADEL_FIRST_VISIBLE_DOM_SCRIPT:
            raise AssertionError("unexpected page evaluation")
        if self.mode == "scheduler":
            assert self.scheduler_date is not None
            return self.schedulers[self.scheduler_date]
        return {
            "view": "calendar",
            "date": "",
            "courts": [],
            "rows": [],
            "calendar_dates": list(self.calendar_dates[self.month]),
            "calendar_available_dates": list(self.event_dates),
            "loading": False,
            "authentication_visible": False,
            "visible_text": "Vernier disponible",
        }

    def close(self) -> None:
        self.closed = True
        self.events.append("page_close")


class _FakePadelFirstContext:
    def __init__(self, page: _FakePadelFirstPage, events: list[str]) -> None:
        self.page = page
        self.events = events
        self.closed = False

    def new_page(self) -> _FakePadelFirstPage:
        self.events.append("new_page")
        return self.page

    def close(self) -> None:
        self.closed = True
        self.events.append("context_close")


class _FakePadelFirstBrowser:
    def __init__(self, context: _FakePadelFirstContext, events: list[str]) -> None:
        self.context = context
        self.events = events

    def __enter__(self) -> Self:
        self.events.append("browser_enter")
        return self

    def __exit__(self, *_args: object) -> None:
        self.events.append("browser_exit")

    def new_context(self) -> _FakePadelFirstContext:
        self.events.append("new_context")
        return self.context


def _padelfirst_location() -> LocationRecord:
    return next(
        location
        for location in load_locations(ROOT / "data/verified_locations.json")
        if location.location_id == "vernier"
    )


def _padelfirst_source() -> PadelFirstSource:
    return PadelFirstSource(
        "vernier",
        "https://padelfirst.ss-r.ch/court-vernier/",
        "2026-09-23T00:00:00Z",
        "public",
    )


def _padelfirst_connector(
    events: list[str],
    *,
    calendar_dates: dict[str, tuple[str, ...]] | None = None,
    event_dates: dict[str, tuple[str, ...]] | None = None,
    schedulers: dict[date, dict[str, object]] | None = None,
) -> tuple[PadelFirstBrowserConnector, _FakePadelFirstPage, _FakePadelFirstContext]:
    page = _FakePadelFirstPage(
        events,
        calendar_dates or {"current": ("2026-09-23", "2026-09-24")},
        event_dates or {"current": ("2026-09-23", "2026-09-24")},
        schedulers
        or {
            date(2026, 9, 23): _scheduler_payload(date(2026, 9, 23)),
            date(2026, 9, 24): _scheduler_payload(date(2026, 9, 24)),
        },
    )
    context = _FakePadelFirstContext(page, events)
    browser = _FakePadelFirstBrowser(context, events)
    return (
        PadelFirstBrowserConnector(
            (_padelfirst_source(),),
            browser_factory=cast(BrowserFactory, lambda: browser),
            timeout_ms=1_000,
        ),
        page,
        context,
    )


def test_padelfirst_connector_collects_visible_scheduler_and_cleans_up() -> None:
    events: list[str] = []
    connector, page, context = _padelfirst_connector(events)

    result = connector.collect(
        _padelfirst_location(),
        run_id="run-vernier",
        window_start=date(2026, 9, 23),
        window_end=date(2026, 9, 25),
        collected_at="2026-09-23T07:00:00Z",
    )
    connector.close()

    assert result.run.status == "success"
    assert len(result.slots) == 4
    assert page.wait_until == "commit"
    assert page.closed and context.closed
    assert events[-3:] == ["page_close", "context_close", "browser_exit"]
    assert events.count("browser_enter") == 1
    assert not any("cell" in event or "submit" in event for event in events)


def test_padelfirst_connector_navigates_visible_calendar_months() -> None:
    events: list[str] = []
    connector, _page, _context = _padelfirst_connector(
        events,
        calendar_dates={
            "current": ("2026-09-30",),
            "next": ("2026-10-01",),
        },
        event_dates={
            "current": ("2026-09-30",),
            "next": ("2026-10-01",),
        },
        schedulers={
            date(2026, 9, 30): _scheduler_payload(date(2026, 9, 30)),
            date(2026, 10, 1): _scheduler_payload(date(2026, 10, 1)),
        },
    )

    result = connector.collect(
        _padelfirst_location(),
        run_id="run-vernier",
        window_start=date(2026, 9, 30),
        window_end=date(2026, 10, 2),
        collected_at="2026-09-23T07:00:00Z",
    )

    assert len(result.slots) == 4
    assert "click:calendar-next" in events
