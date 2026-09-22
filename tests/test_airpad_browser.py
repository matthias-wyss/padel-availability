from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast

import pytest

from padel_availability.connectors.airpad_browser import (
    _AIRPAD_VISIBLE_DOM_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    AirpadBrowserError,
    parse_airpad_dom,
    parse_airpad_observations,
)

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
