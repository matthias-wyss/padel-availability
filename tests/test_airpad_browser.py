from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Self, cast

import pytest

from padel_availability.connectors.airpad import AirpadSource
from padel_availability.connectors.airpad_browser import (
    _AIRPAD_VISIBLE_DOM_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    AirpadBrowserConnector,
    AirpadBrowserError,
    AirpadSourceError,
    parse_airpad_dom,
    parse_airpad_observations,
)
from padel_availability.models import LocationRecord

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "airpad" / "dom"


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
            pytest.skip(
                f"Playwright is installed but Chromium could not launch. Original error: {error}"
            )
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
            content="[data-slot-id], .date-slot, .playground-slot { display:block; width:100px; height:20px; }"
        )
        payload = page.evaluate(_AIRPAD_VISIBLE_DOM_SCRIPT)
        assert isinstance(payload, dict)
        return cast(dict[str, object], payload)
    finally:
        page.close()
        context.close()


@dataclass
class _Element:
    tag: str
    attributes: dict[str, str]
    children: list[_Element | str] = field(default_factory=lambda: list[_Element | str]())

    def text(self) -> str:
        return "".join(child if isinstance(child, str) else child.text() for child in self.children)

    def descendants(self) -> list[_Element]:
        result: list[_Element] = []
        for child in self.children:
            if isinstance(child, _Element):
                result.append(child)
                result.extend(child.descendants())
        return result

    def with_class(self, name: str) -> list[_Element]:
        return [
            element
            for element in self.descendants()
            if name in element.attributes.get("class", "").split()
        ]


class _FixtureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Element("#document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = _Element(tag, {name: value or "" for name, value in attrs})
        self.stack[-1].children.append(element)
        if tag not in {"area", "br", "input", "meta"}:
            self.stack.append(element)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _fixture_payload(name: str) -> dict[str, object]:
    parser = _FixtureParser()
    parser.feed((FIXTURE_ROOT / f"{name}.html").read_text(encoding="utf-8"))
    root = parser.root
    calendars = root.with_class("calendar-block")
    dates = root.with_class("date-slot")
    slots: list[dict[str, object]] = []
    empty_rows: list[str] = []
    invalid_rows = False
    for playground in root.with_class("playground-slot"):
        titles = playground.with_class("section-title")
        court = titles[0].text().strip() if titles else None
        if court is None:
            invalid_rows = True
        for card in playground.with_class("duration-card"):
            text = " ".join(card.text().split())
            time_match = re.search(r"Start\s+([0-9]{1,2}:[0-9]{2})", text)
            duration_match = re.search(r"[0-9]{1,2}:[0-9]{2}\s*([0-9]+\s*min)", text)
            slots.append(
                {
                    "external_id": card.attributes.get("data-slot-id") or None,
                    "court": court,
                    "time": time_match.group(1) if time_match else None,
                    "duration": duration_match.group(1) if duration_match else None,
                    "class": card.attributes.get("class", ""),
                    "disabled": "disabled" in card.attributes
                    or card.attributes.get("aria-disabled") == "true",
                }
            )
        if not playground.with_class("duration-card") and court is not None:
            empty_rows.append(court)
    active_dates = [
        button
        for button in dates
        if "active" in button.attributes.get("class", "").split()
        or button.attributes.get("aria-current") == "date"
    ]
    date_value = active_dates[0].attributes.get("aria-label", "") if active_dates else ""
    if date_value:
        month, day, year = date_value.replace(",", "").split()
        parsed_date = date(
            int(year),
            {
                "January": 1,
                "February": 2,
                "March": 3,
                "April": 4,
                "May": 5,
                "June": 6,
                "July": 7,
                "August": 8,
                "September": 9,
                "October": 10,
                "November": 11,
                "December": 12,
            }[month],
            int(day),
        ).isoformat()
    else:
        parsed_date = ""
    visible_text = " ".join(root.text().split())
    return {
        "view": "booking" if calendars and dates else "unknown",
        "date": parsed_date,
        "slots": slots,
        "empty_grid": bool(root.with_class("playground-slot")) and not slots,
        "empty_rows": empty_rows,
        "invalid_rows": invalid_rows,
        "visible_text": visible_text,
    }


def test_airpad_available_dom_extracts_each_duration() -> None:
    observations = parse_airpad_dom(_fixture_payload("booking-available"), date(2026, 9, 22))

    assert len(observations) == 3
    assert [observation.court_label for observation in observations] == [
        "Terrain 1",
        "Terrain 1",
        "Terrain 2",
    ]
    assert [observation.ends_at for observation in observations] == [
        "2026-09-22T10:00:00+02:00",
        "2026-09-22T11:30:00+02:00",
        "2026-09-22T22:30:00+02:00",
    ]


def test_airpad_visible_script_extracts_fixture_and_filters_hidden_content(
    fixture_browser: Any,
) -> None:
    payload = _browser_payload(fixture_browser, "booking-available")

    assert set(payload) >= {"view", "date", "slots", "empty_grid", "visible_text"}
    assert payload["view"] == "booking"
    assert payload["date"] == "2026-09-22"
    slots = cast(list[dict[str, object]], payload["slots"])
    assert len(slots) == 3
    assert all(
        {"external_id", "court", "time", "duration", "class", "disabled"} <= set(slot)
        for slot in slots
    )
    assert len(parse_airpad_dom(payload, date(2026, 9, 22))) == 3


def test_airpad_visible_script_preserves_states_and_captcha_error(
    fixture_browser: Any,
) -> None:
    payload = _browser_payload(fixture_browser, "booking-states")
    observations = parse_airpad_dom(payload, date(2026, 9, 22))

    assert [observation.status for observation in observations] == [
        "available",
        "unavailable",
        "unknown",
        "unavailable",
    ]
    blocked = _browser_payload(fixture_browser, "booking-blocked")
    with pytest.raises(AirpadBrowserError, match="blocked"):
        parse_airpad_dom(blocked, date(2026, 9, 22))


def test_airpad_visible_script_rejects_no_active_date(fixture_browser: Any) -> None:
    context = fixture_browser.new_context()
    page = context.new_page()
    try:
        page.set_content((FIXTURE_ROOT / "booking-available.html").read_text(encoding="utf-8"))
        page.add_style_tag(content=".date-slot { display:block; width:100px; height:20px; }")
        page.evaluate(
            """() => document.querySelectorAll('.date-slot').forEach(element => {
              element.classList.remove('active');
              element.removeAttribute('aria-current');
            })"""
        )
        payload = page.evaluate(_AIRPAD_VISIBLE_DOM_SCRIPT)
        assert isinstance(payload, dict)
        payload = cast(dict[str, object], payload)
        assert payload["date"] == ""
        with pytest.raises(AirpadBrowserError, match="date"):
            parse_airpad_dom(payload, date(2026, 9, 22))
    finally:
        page.close()
        context.close()


def test_airpad_visible_script_rejects_ambiguous_active_date(fixture_browser: Any) -> None:
    context = fixture_browser.new_context()
    page = context.new_page()
    try:
        page.set_content((FIXTURE_ROOT / "booking-available.html").read_text(encoding="utf-8"))
        page.add_style_tag(content=".date-slot { display:block; width:100px; height:20px; }")
        page.evaluate(
            """() => document.querySelectorAll('.date-slot').forEach(element => {
              element.classList.add('active');
              element.setAttribute('aria-current', 'date');
            })"""
        )
        payload = page.evaluate(_AIRPAD_VISIBLE_DOM_SCRIPT)
        assert isinstance(payload, dict)
        payload = cast(dict[str, object], payload)
        assert payload["date"] == ""
        with pytest.raises(AirpadBrowserError, match="date"):
            parse_airpad_dom(payload, date(2026, 9, 22))
    finally:
        page.close()
        context.close()


def test_airpad_incomplete_empty_grid_is_a_bounded_error(fixture_browser: Any) -> None:
    payload = _browser_payload(fixture_browser, "booking-incomplete")

    assert payload["empty_grid"] is False
    with pytest.raises(AirpadBrowserError, match="court"):
        parse_airpad_dom(payload, date(2026, 9, 22))


def test_airpad_labeled_empty_grid_without_empty_marker_is_zero_slots(
    fixture_browser: Any,
) -> None:
    payload = _browser_payload(fixture_browser, "booking-empty-labeled")

    assert payload["empty_grid"] is True
    assert payload["empty_rows"] == []
    assert payload["invalid_rows"] is False
    assert parse_airpad_dom(payload, date(2026, 9, 22)) == ()


def test_airpad_empty_playground_is_zero_slots() -> None:
    assert parse_airpad_dom(_fixture_payload("booking-empty"), date(2026, 9, 22)) == ()


def test_airpad_blocked_dom_is_bounded_error() -> None:
    with pytest.raises(AirpadBrowserError, match="blocked"):
        parse_airpad_dom(_fixture_payload("booking-blocked"), date(2026, 9, 22))


def test_airpad_unknown_booking_dom_is_error() -> None:
    with pytest.raises(AirpadBrowserError, match="booking view"):
        parse_airpad_dom(_fixture_payload("home"), date(2026, 9, 22))


def test_airpad_missing_id_uses_existing_hash() -> None:
    observations = parse_airpad_dom(_fixture_payload("booking-available"), date(2026, 9, 22))

    slots = parse_airpad_observations(
        observations,
        location_id="airpad-la-praille",
        run_id="run-airpad",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 23),
    )

    assert observations[1].external_id is None
    assert len(slots[1].slot_key) == 64
    assert slots[1].external_id is None


def test_airpad_24_hour_times_use_zurich_and_utc() -> None:
    observations = parse_airpad_dom(_fixture_payload("booking-available"), date(2026, 9, 22))

    slots = parse_airpad_observations(
        (observations[2],),
        location_id="airpad-la-praille",
        run_id="run-airpad",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 23),
    )

    assert observations[2].starts_at == "2026-09-22T21:30:00+02:00"
    assert slots[0].starts_at == "2026-09-22T19:30:00Z"
    assert slots[0].ends_at == "2026-09-22T20:30:00Z"


def test_airpad_changed_date_rejects_unchanged_dom() -> None:
    with pytest.raises(AirpadBrowserError, match="requested date"):
        parse_airpad_dom(_fixture_payload("booking-available"), date(2026, 9, 23))


def test_airpad_malformed_duration_is_an_error() -> None:
    with pytest.raises(AirpadBrowserError, match="duration"):
        parse_airpad_dom(_fixture_payload("booking-malformed"), date(2026, 9, 22))


class _FakeAirpadLocator:
    def __init__(
        self,
        frame: _FakeAirpadFrame,
        selector: str,
        text: str | None = None,
        index: int | None = None,
    ) -> None:
        self.frame = frame
        self.selector = selector
        self.text = text
        self.index = index

    def filter(self, *, has_text: str) -> _FakeAirpadLocator:
        return _FakeAirpadLocator(self.frame, self.selector, has_text, self.index)

    def nth(self, index: int) -> _FakeAirpadLocator:
        return _FakeAirpadLocator(self.frame, self.selector, self.text, index)

    def count(self) -> int:
        return self.frame.has_locator(self.selector, self.text, self.index)

    def is_visible(self) -> bool:
        return self.count() == 1

    def click(self) -> None:
        self.frame.click(self.selector, self.text, self.index)

    def all_inner_texts(self) -> list[str]:
        return self.frame.inner_texts(self.selector)

    def inner_text(self) -> str:
        return self.frame.inner_text(self.selector, self.index)

    def get_attribute(self, name: str) -> str | None:
        return self.frame.get_attribute(self.selector, self.index, name)


class _FakeAirpadFrame:
    def __init__(
        self,
        url: str,
        dates: dict[date, list[tuple[str, dict[str, object]]]],
        initial_date: date,
        events: list[str],
        *,
        programming_error: bool = False,
        activity_labels: list[str] | None = None,
        control_delay: int = 0,
        arrow_disabled: bool = False,
        arrow_stuck: bool = False,
        stale_payloads: dict[date, list[dict[str, object]]] | None = None,
        activity_sequences: list[list[str]] | None = None,
    ) -> None:
        self.url = url
        self.dates = dates
        self.current_date = initial_date
        self.range_index = 0
        self.events = events
        self.programming_error = programming_error
        self.activity_labels = activity_labels or ["LA PRAILLE"]
        self.control_delay = control_delay
        self.arrow_disabled = arrow_disabled
        self.arrow_stuck = arrow_stuck
        self.stale_payloads = stale_payloads or {}
        self.selected_activity: str | None = None
        self.wait_ticks = 0
        self._stale_reads = 0
        self.activity_sequences = activity_sequences or []
        self._activity_sequence_index = 0

    @property
    def current_range(self) -> tuple[str, dict[str, object]]:
        return self.dates[self.current_date][self.range_index]

    def locator(self, selector: str) -> _FakeAirpadLocator:
        return _FakeAirpadLocator(self, selector)

    def evaluate(self, expression: str, arg: object = None) -> object:
        if expression == _AIRPAD_VISIBLE_DOM_SCRIPT:
            if self._stale_reads:
                self._stale_reads -= 1
                return dict(self.stale_payloads[self.current_date][self._stale_reads])
            return dict(self.current_range[1])
        raise AssertionError(f"unexpected frame evaluation: {expression!r} {arg!r}")

    def has_locator(
        self, selector: str, text: str | None, index: int | None = None
    ) -> int:
        if selector == ".item-title":
            values = ["1.Terrains"]
        elif selector == ".activity-card":
            values = self.activity_labels
        elif selector in {".btn-date-calendar", ".select-time-range"}:
            values = [""] if self.wait_ticks >= self.control_delay else []
        elif selector.startswith("button.days-btn"):
            values = [""]
        elif selector == ".btn-arrow-right":
            values = [""] if self.arrow_disabled or self.range_index + 1 < len(
                self.dates[self.current_date]
            ) else []
        else:
            values = []
        if index is not None:
            if index >= len(values):
                return 0
            return int(text is None or text in values[index])
        if text is None:
            return len(values)
        return sum(text in value for value in values)

    def click(self, selector: str, text: str | None, index: int | None = None) -> None:
        self.events.append(f"click:{selector}:{text or ''}")
        if self.programming_error:
            raise TypeError("test programming error")
        if selector == ".item-title":
            return
        if selector == ".activity-card":
            self.selected_activity = next(
                label
                for label in self.activity_labels
                if (index is None or label == self.activity_labels[index])
                and (text is None or text in label)
            )
            return
        if selector.startswith("button.days-btn"):
            label = selector.split('aria-label="', 1)[1].split('"', 1)[0]
            month, day, year = label.replace(",", "").split()
            self.current_date = date(
                int(year),
                {
                    "January": 1,
                    "February": 2,
                    "March": 3,
                    "April": 4,
                    "May": 5,
                    "June": 6,
                    "July": 7,
                    "August": 8,
                    "September": 9,
                    "October": 10,
                    "November": 11,
                    "December": 12,
                }[month],
                int(day),
            )
            self.range_index = 0
            self._stale_reads = len(self.stale_payloads.get(self.current_date, []))
        elif selector == ".btn-arrow-right":
            if not self.arrow_stuck and not self.arrow_disabled:
                self.range_index += 1

    def inner_texts(self, selector: str) -> list[str]:
        if selector == ".select-time-range":
            return [self.current_range[0]]
        return []

    def inner_text(self, selector: str, index: int | None) -> str:
        if selector == ".item-title":
            return "1.Terrains"
        if selector == ".activity-card" and index is not None:
            return self.activity_labels[index]
        return ""

    def get_attribute(self, selector: str, index: int | None, name: str) -> str | None:
        if selector == ".activity-card" and index is not None:
            if name == "aria-selected":
                return "true" if self.activity_labels[index] == self.selected_activity else "false"
            if name == "class" and self.activity_labels[index] == self.selected_activity:
                return "activity-card active"
        if selector == ".btn-arrow-right" and name == "aria-disabled" and self.arrow_disabled:
            return "true"
        return None

    def wait(self) -> None:
        self.wait_ticks += 1
        if self._activity_sequence_index + 1 < len(self.activity_sequences):
            self._activity_sequence_index += 1
            self.activity_labels = self.activity_sequences[self._activity_sequence_index]


class _FakeAirpadPage:
    def __init__(self, frames: list[_FakeAirpadFrame], events: list[str]) -> None:
        self.frames = frames
        self.events = events
        self.closed = False
        self.wait_until: str | None = None

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        del timeout
        self.wait_until = wait_until
        self.events.append(f"goto:{url}")

    def wait_for_timeout(self, timeout: int) -> None:
        for frame in self.frames:
            frame.wait()
        self.events.append(f"wait:{timeout}")

    def evaluate(self, expression: str, arg: object = None) -> object:
        del expression, arg
        raise AssertionError("page evaluation was not expected")

    def close(self) -> None:
        self.closed = True
        self.events.append("page_close")


class _FakeAirpadContext:
    def __init__(self, page: _FakeAirpadPage, events: list[str]) -> None:
        self.page = page
        self.events = events
        self.closed = False

    def new_page(self) -> _FakeAirpadPage:
        self.events.append("new_page")
        return self.page

    def close(self) -> None:
        self.closed = True
        self.events.append("context_close")


class _FakeAirpadBrowser:
    def __init__(self, contexts: list[_FakeAirpadContext], events: list[str]) -> None:
        self.contexts = contexts
        self.events = events

    def __enter__(self) -> Self:
        self.events.append("browser_enter")
        return self

    def __exit__(self, *_args: object) -> None:
        self.events.append("browser_exit")

    def new_context(self) -> _FakeAirpadContext:
        self.events.append("new_context")
        return self.contexts.pop(0)


def _airpad_location(location_id: str = "airpad-la-praille") -> LocationRecord:
    return LocationRecord(
        location_id,
        "AIRPAD La Praille",
        "Plan-les-Ouates",
        (location_id,),
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
        brand="AIRPAD",
        booking_url="https://www.airpad.ch/reserve",
        booking_platform="doinsport",
    )


def _airpad_payload(
    requested_date: date,
    *,
    slots: list[dict[str, object]],
    visible_text: str = "AIRPAD booking",
) -> dict[str, object]:
    return {
        "view": "booking",
        "date": requested_date.isoformat(),
        "slots": slots,
        "empty_grid": not slots,
        "empty_rows": [] if slots else ["Terrain 1"],
        "invalid_rows": False,
        "visible_text": visible_text,
    }


def _airpad_slot(external_id: str, start: str = "09:00") -> dict[str, object]:
    return {
        "external_id": external_id,
        "court": "Terrain 1",
        "time": start,
        "duration": "60 min",
        "class": "available",
        "disabled": False,
    }


def _airpad_connector(
    frame: _FakeAirpadFrame,
    events: list[str],
    *,
    timeout_ms: int = 15_000,
) -> tuple[AirpadBrowserConnector, _FakeAirpadPage, _FakeAirpadContext]:
    page = _FakeAirpadPage([frame], events)
    context = _FakeAirpadContext(page, events)
    browser = _FakeAirpadBrowser([context], events)
    source = AirpadSource(
        "airpad-la-praille",
        "https://www.airpad.ch/reserve",
        "2026-09-22T00:00:00Z",
        "public",
    )
    return (
        AirpadBrowserConnector((source,), browser_factory=lambda: browser, timeout_ms=timeout_ms),
        page,
        context,
    )


def test_airpad_connector_selects_visible_site_and_closes_context() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    hidden = _FakeAirpadFrame(
        "https://www.airpad.ch/reserve",
        {requested: [("09:00", _airpad_payload(requested, slots=[]))]},
        requested,
        events,
    )
    visible = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {requested: [("09:00", _airpad_payload(requested, slots=[_airpad_slot("slot-1")]))]},
        requested,
        events,
    )
    page = _FakeAirpadPage([hidden, visible], events)
    context = _FakeAirpadContext(page, events)
    browser = _FakeAirpadBrowser([context], events)
    connector = AirpadBrowserConnector(
        (AirpadSource("airpad-la-praille", "https://www.airpad.ch/reserve", "2026-09-22T00:00:00Z", "public"),),
        browser_factory=lambda: browser,
    )

    result = connector.collect(
        _airpad_location(),
        run_id="run-airpad",
        window_start=requested,
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert result.run.status == "success"
    assert len(result.slots) == 1
    assert page.closed and context.closed
    assert events.count("browser_enter") == 1
    assert events.count("browser_exit") == 1
    assert events.count("new_context") == 1
    assert events.count("new_page") == 1
    assert events[-3:] == ["page_close", "context_close", "browser_exit"]
    assert visible.selected_activity == "LA PRAILLE"


def test_airpad_connector_collects_all_time_ranges_without_duplicates() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {
            requested: [
                ("09:00-10:00", _airpad_payload(requested, slots=[_airpad_slot("slot-1")])),
                (
                    "10:00-11:00",
                    _airpad_payload(
                        requested,
                        slots=[_airpad_slot("slot-1"), _airpad_slot("slot-2", "10:00")],
                    ),
                ),
            ]
        },
        requested,
        events,
    )
    connector, page, _context = _airpad_connector(frame, events)

    result = connector.collect(
        _airpad_location(),
        run_id="run-airpad",
        window_start=requested,
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert len(result.slots) == 2
    assert events.count("click:.btn-arrow-right:") == 1
    assert page.closed


def test_airpad_connector_accepts_loaded_empty_playground() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {requested: [("09:00", _airpad_payload(requested, slots=[]))]},
        requested,
        events,
    )
    connector, _page, _context = _airpad_connector(frame, events)

    result = connector.collect(
        _airpad_location(),
        run_id="run-airpad",
        window_start=requested,
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert result.run.status == "success"
    assert result.slots == ()


def test_airpad_connector_continues_after_date_refresh() -> None:
    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {
            first: [("09:00", _airpad_payload(first, slots=[_airpad_slot("slot-1")]))],
            second: [("09:00", _airpad_payload(second, slots=[_airpad_slot("slot-2")]))],
        },
        first,
        events,
    )
    connector, _page, _context = _airpad_connector(frame, events)

    result = connector.collect(
        _airpad_location(),
        run_id="run-airpad",
        window_start=first,
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert result.run.status == "success"
    assert len(result.slots) == 2
    assert events.count('click:button.days-btn[aria-label="September 22, 2026"]:') == 1
    assert events.count('click:button.days-btn[aria-label="September 23, 2026"]:') == 1


def test_airpad_programming_errors_propagate_and_cleanup() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {requested: [("09:00", _airpad_payload(requested, slots=[]))]},
        requested,
        events,
        programming_error=True,
    )
    connector, page, context = _airpad_connector(frame, events)

    with pytest.raises(TypeError, match="programming"):
        connector.collect(
            _airpad_location(),
            run_id="run-airpad",
            window_start=requested,
            window_end=date(2026, 9, 23),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()

    assert page.closed and context.closed
    assert events[-3:] == ["page_close", "context_close", "browser_exit"]


def test_airpad_activity_card_requires_exact_visible_label() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {requested: [("09:00", _airpad_payload(requested, slots=[]))]},
        requested,
        events,
        activity_labels=["LA PRAILLE EXTENDED"],
    )
    connector, page, _context = _airpad_connector(frame, events, timeout_ms=100)

    with pytest.raises(AirpadBrowserError, match="location"):
        connector.collect(
            _airpad_location(),
            run_id="run-airpad",
            window_start=requested,
            window_end=date(2026, 9, 23),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()

    assert page.closed


def test_airpad_connector_waits_for_refreshed_grid_after_date_change() -> None:
    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    stale = _airpad_payload(second, slots=[_airpad_slot("slot-1")])
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {
            first: [("09:00", _airpad_payload(first, slots=[_airpad_slot("slot-1")]))],
            second: [("09:00", _airpad_payload(second, slots=[_airpad_slot("slot-2")]))],
        },
        first,
        events,
        stale_payloads={second: [stale]},
    )
    connector, _page, _context = _airpad_connector(frame, events)

    result = connector.collect(
        _airpad_location(),
        run_id="run-airpad",
        window_start=first,
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert {slot.external_id for slot in result.slots} == {"slot-1", "slot-2"}


def test_airpad_connector_waits_for_new_slots_after_stale_empty_grid() -> None:
    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {
            first: [("09:00", _airpad_payload(first, slots=[]))],
            second: [("09:00", _airpad_payload(second, slots=[_airpad_slot("slot-2")]))],
        },
        first,
        events,
        stale_payloads={second: [_airpad_payload(second, slots=[])]},
    )
    connector, _page, _context = _airpad_connector(frame, events)

    result = connector.collect(
        _airpad_location(),
        run_id="run-airpad",
        window_start=first,
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert [slot.external_id for slot in result.slots] == ["slot-2"]


def test_airpad_connector_stops_on_disabled_time_range_arrow() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {requested: [("09:00", _airpad_payload(requested, slots=[_airpad_slot("slot-1")]))]},
        requested,
        events,
        arrow_disabled=True,
    )
    connector, _page, _context = _airpad_connector(frame, events, timeout_ms=100)

    result = connector.collect(
        _airpad_location(),
        run_id="run-airpad",
        window_start=requested,
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert len(result.slots) == 1


def test_airpad_connector_stops_when_time_range_label_does_not_change() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {
            requested: [
                ("09:00", _airpad_payload(requested, slots=[_airpad_slot("slot-1")])),
                ("10:00", _airpad_payload(requested, slots=[_airpad_slot("slot-2", "10:00")])),
            ]
        },
        requested,
        events,
        arrow_stuck=True,
    )
    connector, _page, _context = _airpad_connector(frame, events, timeout_ms=100)

    result = connector.collect(
        _airpad_location(),
        run_id="run-airpad",
        window_start=requested,
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert [slot.external_id for slot in result.slots] == ["slot-1"]


def test_airpad_connector_maps_normalization_errors_to_airpad_source_error() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    unavailable = _airpad_slot("slot-conflict")
    unavailable["class"] = "disabled"
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {
            requested: [
                (
                    "09:00",
                    _airpad_payload(requested, slots=[_airpad_slot("slot-conflict")]),
                ),
                ("10:00", _airpad_payload(requested, slots=[unavailable])),
            ]
        },
        requested,
        events,
    )
    connector, page, context = _airpad_connector(frame, events)

    with pytest.raises(AirpadSourceError, match="duplicate"):
        connector.collect(
            _airpad_location(),
            run_id="run-airpad",
            window_start=requested,
            window_end=date(2026, 9, 23),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()

    assert page.closed and context.closed


def test_airpad_connector_waits_for_booking_controls_after_location_click() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {requested: [("09:00", _airpad_payload(requested, slots=[]))]},
        requested,
        events,
        control_delay=2,
    )
    connector, _page, _context = _airpad_connector(frame, events)

    result = connector.collect(
        _airpad_location(),
        run_id="run-airpad",
        window_start=requested,
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert result.slots == ()
    assert "wait:100" in events


def test_airpad_connector_accepts_consecutive_valid_empty_grids_after_refresh() -> None:
    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {
            first: [("09:00", _airpad_payload(first, slots=[]))],
            second: [("09:00", _airpad_payload(second, slots=[]))],
        },
        first,
        events,
        stale_payloads={second: [_airpad_payload(second, slots=[], visible_text="loading")]},
    )
    connector, _page, _context = _airpad_connector(frame, events, timeout_ms=300)

    result = connector.collect(
        _airpad_location(),
        run_id="run-airpad",
        window_start=first,
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert result.slots == ()


def test_airpad_connector_rejects_unchanged_empty_grid_without_refresh() -> None:
    events: list[str] = []
    first = date(2026, 9, 22)
    second = date(2026, 9, 23)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {
            first: [("09:00", _airpad_payload(first, slots=[]))],
            second: [("09:00", _airpad_payload(second, slots=[]))],
        },
        first,
        events,
    )
    connector, _page, _context = _airpad_connector(frame, events, timeout_ms=100)

    with pytest.raises(AirpadBrowserError, match="timed out"):
        connector.collect(
            _airpad_location(),
            run_id="run-airpad",
            window_start=first,
            window_end=date(2026, 9, 24),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()


def test_airpad_connector_waits_for_requested_card_after_other_card() -> None:
    events: list[str] = []
    requested = date(2026, 9, 22)
    frame = _FakeAirpadFrame(
        "https://airpad.doinsport.club/booking",
        {requested: [("09:00", _airpad_payload(requested, slots=[]))]},
        requested,
        events,
        activity_labels=["MEYRIN"],
        activity_sequences=[["MEYRIN"], ["MEYRIN", "LA PRAILLE"]],
    )
    connector, _page, _context = _airpad_connector(frame, events)

    result = connector.collect(
        _airpad_location(),
        run_id="run-airpad",
        window_start=requested,
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert result.slots == ()
    assert frame.selected_activity == "LA PRAILLE"
