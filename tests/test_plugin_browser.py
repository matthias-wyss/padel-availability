from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Self, cast

import pytest

from padel_availability.connectors.playtomic_browser import BrowserFactory
from padel_availability.connectors.plugin import PluginSource
from padel_availability.connectors.plugin_browser import (
    _PLUGIN_COOKIE_CONTROL_SCRIPT,
    _PLUGIN_NEXT_CONTROL_SCRIPT,
    _PLUGIN_VISIBLE_DOM_SCRIPT,
    PluginBrowserConnector,
    PluginBrowserError,
    parse_plugin_dom,
)
from padel_availability.inventory import load_locations

FIXTURE = Path(__file__).parent / "fixtures" / "plugin" / "dom" / "plugin-diary.html"
WEEKLY_FIXTURE = Path(__file__).parent / "fixtures" / "plugin" / "dom" / "plugin-weekly-diary.html"
REQUESTED_DATE = date(2026, 9, 26)
ROOT = Path(__file__).parents[1]
SOURCE = PluginSource(
    "cologny", "https://reservation.cs-cologny.ch/diary", "2026-09-26T00:00:00Z", "public"
)
LOCATION = next(
    location
    for location in load_locations(ROOT / "data/verified_locations.json")
    if location.location_id == SOURCE.location_id
)


def _payload() -> dict[str, Any]:
    return {
        "view": "booking",
        "date": "2026-09-26",
        "activity": "Padel",
        "courts": ["Court 1", "Court 2"],
        "slots": [
            {"court": "Court 1", "start": "09:00", "end": "10:30", "state": "available"},
            {"court": "Court 2", "start": "09:00", "end": "10:30", "state": "booked"},
        ],
        "loading": False,
        "authentication_visible": False,
        "empty_grid": False,
    }


class _FakePluginLocator:
    def __init__(self, page: _FakePluginPage, selector: str) -> None:
        self.page = page
        self.selector = selector

    def count(self) -> int:
        if "next" in self.selector.casefold():
            return 1
        if "decline" in self.selector.casefold() or "refuser" in self.selector.casefold():
            return int(self.page.cookie_visible)
        return 0

    def is_visible(self) -> bool:
        return self.count() == 1

    def click(self) -> None:
        self.page.clicks.append(self.selector)
        if "next" in self.selector.casefold():
            self.page.current_date += timedelta(days=1)
        elif "decline" in self.selector.casefold() or "refuser" in self.selector.casefold():
            self.page.cookie_visible = False


class _FakePluginPage:
    def __init__(self, start: date = REQUESTED_DATE) -> None:
        self.current_date = start
        self.url = ""
        self.closed = False
        self.cookie_visible = False
        self.cookie_control_count = 0
        self.clicks: list[str] = []
        self.goto_args: list[tuple[str, str, int]] = []

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.url = url
        self.goto_args.append((url, wait_until, timeout))

    def evaluate(self, script: str, _arg: object = None) -> Any:
        if ".header_date button" in script:
            return 'button[aria-label="Next day"]'
        if "input[type=\"button\"]" in script:
            if self.cookie_control_count > 1:
                return "!ambiguous"
            return 'button[aria-label="Decline"]' if self.cookie_visible else ""
        payload = _payload()
        payload["date"] = self.current_date.isoformat()
        return payload

    def locator(self, selector: str) -> _FakePluginLocator:
        return _FakePluginLocator(self, selector)

    def wait_for_timeout(self, _timeout: int) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _FakePluginContext:
    def __init__(self, page: _FakePluginPage) -> None:
        self.page = page
        self.closed = False

    def new_page(self) -> _FakePluginPage:
        return self.page

    def close(self) -> None:
        self.closed = True


class _FakePluginBrowser:
    def __init__(self, context: _FakePluginContext) -> None:
        self.context = context
        self.exited = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.exited = True

    def new_context(self) -> _FakePluginContext:
        return self.context


def _connector(page: _FakePluginPage) -> tuple[PluginBrowserConnector, _FakePluginContext, _FakePluginBrowser]:
    context = _FakePluginContext(page)
    browser = _FakePluginBrowser(context)
    connector = PluginBrowserConnector(
        (SOURCE,), browser_factory=cast(BrowserFactory, lambda: browser)
    )
    return connector, context, browser


def _collect(connector: PluginBrowserConnector, *, end: date) -> Any:
    return connector.collect(
        LOCATION,
        run_id="run-plugin",
        window_start=REQUESTED_DATE,
        window_end=end,
        collected_at="2026-09-26T00:00:00Z",
    )


def test_plugin_connector_uses_public_diary_and_visible_next_day_navigation() -> None:
    page = _FakePluginPage()
    connector, context, browser = _connector(page)

    result = _collect(connector, end=date(2026, 9, 28))
    connector.close()

    assert page.goto_args == [(SOURCE.booking_url, "commit", 15_000)]
    assert len([click for click in page.clicks if "next" in click.casefold()]) == 1
    assert all("booking" not in click.casefold() and "slot" not in click.casefold() for click in page.clicks)
    assert page.closed and context.closed and browser.exited
    assert len(result.slots) == 4


def test_plugin_connector_rejects_authentication_and_closes_resources() -> None:
    page = _FakePluginPage()
    original_evaluate = page.evaluate

    def evaluate(script: str, arg: object = None) -> Any:
        payload = original_evaluate(script, arg)
        if isinstance(payload, dict):
            payload["authentication_visible"] = True
        return payload

    page.evaluate = evaluate  # type: ignore[method-assign]
    connector, context, browser = _connector(page)

    with pytest.raises(PluginBrowserError, match="authentication"):
        _collect(connector, end=date(2026, 9, 27))
    connector.close()

    assert page.closed and context.closed and browser.exited


def test_plugin_connector_rejects_wrong_activity_and_closes_resources() -> None:
    page = _FakePluginPage()
    original_evaluate = page.evaluate

    def evaluate(script: str, arg: object = None) -> Any:
        payload = original_evaluate(script, arg)
        if isinstance(payload, dict):
            payload["activity"] = "Tennis"
        return payload

    page.evaluate = evaluate  # type: ignore[method-assign]
    connector, context, browser = _connector(page)

    with pytest.raises(PluginBrowserError, match="activity"):
        _collect(connector, end=date(2026, 9, 27))
    connector.close()

    assert page.closed and context.closed and browser.exited


def test_plugin_connector_declines_optional_cookies_only_when_visible() -> None:
    page = _FakePluginPage()
    page.cookie_visible = True
    connector, _context, _browser = _connector(page)

    _collect(connector, end=date(2026, 9, 27))
    connector.close()

    assert len([click for click in page.clicks if "decline" in click.casefold()]) == 1


def test_plugin_connector_persists_variable_dates_and_slot_states() -> None:
    page = _FakePluginPage()
    connector, _context, _browser = _connector(page)

    result = _collect(connector, end=date(2026, 9, 28))
    connector.close()

    assert [(slot.starts_at, slot.ends_at, slot.status) for slot in result.slots] == [
        ("2026-09-26T07:00:00Z", "2026-09-26T08:30:00Z", "available"),
        ("2026-09-26T07:00:00Z", "2026-09-26T08:30:00Z", "unavailable"),
        ("2026-09-27T07:00:00Z", "2026-09-27T08:30:00Z", "available"),
        ("2026-09-27T07:00:00Z", "2026-09-27T08:30:00Z", "unavailable"),
    ]


def test_plugin_connector_skips_unavailable_source_without_starting_browser() -> None:
    unavailable_source = PluginSource(
        SOURCE.location_id, SOURCE.booking_url, SOURCE.checked_at, "unavailable"
    )
    factory_calls = 0

    def browser_factory() -> Any:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("unavailable source must not start a browser")

    connector = PluginBrowserConnector(
        (unavailable_source,), browser_factory=cast(BrowserFactory, browser_factory)
    )

    result = _collect(connector, end=date(2026, 9, 27))

    assert result.run.status == "unavailable"
    assert result.run.source_url == SOURCE.booking_url
    assert result.slots == ()
    assert factory_calls == 0


def test_plugin_connector_waits_for_two_stable_visible_date_payloads() -> None:
    page = _FakePluginPage()
    payloads = [_payload(), _payload(), _payload()]
    payloads[0]["slots"][0]["state"] = "available"
    payloads[1]["slots"][0]["state"] = "booked"
    payloads[2]["slots"][0]["state"] = "booked"
    original_evaluate = page.evaluate
    visible_evaluations = 0

    def evaluate(script: str, arg: object = None) -> Any:
        nonlocal visible_evaluations
        if script == _PLUGIN_VISIBLE_DOM_SCRIPT:
            payload = payloads[min(visible_evaluations, len(payloads) - 1)]
            visible_evaluations += 1
            payload["date"] = REQUESTED_DATE.isoformat()
            return payload
        return original_evaluate(script, arg)

    page.evaluate = evaluate  # type: ignore[method-assign]
    connector, _context, _browser = _connector(page)

    result = _collect(connector, end=date(2026, 9, 27))

    assert visible_evaluations == 3
    assert [slot.status for slot in result.slots] == ["unavailable", "unavailable"]


def test_plugin_connector_rejects_ambiguous_visible_cookie_controls() -> None:
    page = _FakePluginPage()
    page.cookie_visible = True
    page.cookie_control_count = 2
    connector, context, browser = _connector(page)

    with pytest.raises(PluginBrowserError, match="cookie.*ambiguous"):
        _collect(connector, end=date(2026, 9, 27))

    assert page.clicks == []
    assert page.closed and context.closed and browser.exited


def test_parse_maps_states_and_keeps_variable_local_durations() -> None:
    payload = _payload()
    payload["slots"] = [
        {"court": "Court 1", "start": "09:00", "end": "10:30", "state": "available"},
        {"court": "Court 2", "start": "09:00", "end": "10:30", "state": "booked"},
        {"court": "Court 1", "start": "11:00", "end": "11:45", "state": "unknown"},
        {"court": "Court 2", "start": "11:00", "end": "11:45", "state": "available"},
    ]

    observations = parse_plugin_dom(payload, REQUESTED_DATE)

    assert [(slot.status, slot.starts_at, slot.ends_at) for slot in observations] == [
        ("available", "2026-09-26T09:00:00+02:00", "2026-09-26T10:30:00+02:00"),
        ("unavailable", "2026-09-26T09:00:00+02:00", "2026-09-26T10:30:00+02:00"),
        ("unknown", "2026-09-26T11:00:00+02:00", "2026-09-26T11:45:00+02:00"),
        ("available", "2026-09-26T11:00:00+02:00", "2026-09-26T11:45:00+02:00"),
    ]


def test_explicit_empty_grid_returns_no_observations() -> None:
    payload = _payload()
    payload.update(slots=[], empty_grid=True)

    assert parse_plugin_dom(payload, REQUESTED_DATE) == ()


def test_ambiguous_zurich_fallback_time_is_rejected() -> None:
    payload = _payload()
    payload["date"] = "2026-10-25"
    payload["slots"] = [
        {"court": "Court 1", "start": "02:30", "end": "03:30", "state": "available"},
        {"court": "Court 2", "start": "02:30", "end": "03:30", "state": "available"},
    ]

    with pytest.raises(PluginBrowserError, match="ambiguous"):
        parse_plugin_dom(payload, date(2026, 10, 25))


def test_partial_matrix_is_rejected_even_when_every_court_appears_elsewhere() -> None:
    payload = _payload()
    payload["slots"].append(
        {"court": "Court 1", "start": "11:00", "end": "12:00", "state": "available"}
    )

    with pytest.raises(PluginBrowserError, match="matrix"):
        parse_plugin_dom(payload, REQUESTED_DATE)


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda p: p.update(loading=True), "loading"),
        (lambda p: p.update(authentication_visible=True), "authentication"),
        (lambda p: p.update(activity="CAPTCHA verification"), "CAPTCHA"),
        (lambda p: p.update(view="login"), "booking"),
        (lambda p: p.update(date="2026-09-27"), "date"),
        (lambda p: p.update(activity="Tennis"), "activity"),
        (lambda p: p.update(courts=[]), "court"),
        (lambda p: p.update(slots=p["slots"][:1]), "court"),
        (lambda p: p["slots"].append(dict(p["slots"][0])), "duplicate"),
        (lambda p: p["slots"][0].update(start="9:00"), "time"),
        (lambda p: p["slots"][0].update(end="08:00"), "duration"),
        (lambda p: p["slots"][0].update(participant="Alice"), "fields"),
        (lambda p: p.update(empty_grid=True), "empty"),
        (lambda p: p["slots"][0].update(state="maybe"), "state"),
        (lambda p: p["slots"][0].pop("state"), "state"),
    ],
)
def test_rejects_untrusted_or_incomplete_visible_payload(change: Any, match: str) -> None:
    payload = _payload()
    change(payload)

    with pytest.raises(PluginBrowserError, match=match):
        parse_plugin_dom(payload, REQUESTED_DATE)


def test_fixture_is_a_sanitized_visible_diary_and_extracts_required_payload() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(FIXTURE.read_text(encoding="utf-8"))
        payload = page.evaluate(_PLUGIN_VISIBLE_DOM_SCRIPT)
        assert page.evaluate(_PLUGIN_NEXT_CONTROL_SCRIPT) == 'button[aria-label="Next day"]'
        assert page.evaluate(_PLUGIN_COOKIE_CONTROL_SCRIPT) == ""
        browser.close()

    assert set(payload) == {
        "view",
        "date",
        "activity",
        "courts",
        "slots",
        "loading",
        "authentication_visible",
        "empty_grid",
    }
    observations = parse_plugin_dom(payload, REQUESTED_DATE)
    assert [item.status for item in observations] == [
        "available",
        "unavailable",
        "unknown",
        "available",
    ]


def test_unrecognized_table_cell_label_is_not_guessed_as_booked() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(FIXTURE.read_text(encoding="utf-8"))
        page.locator(".reservation tbody tr:first-child td:nth-child(2)").evaluate(
            "element => element.textContent = 'maintenance'"
        )
        payload = page.evaluate(_PLUGIN_VISIBLE_DOM_SCRIPT)
        browser.close()

    assert payload["slots"][0]["state"] == "unrecognized"
    with pytest.raises(PluginBrowserError, match="state"):
        parse_plugin_dom(payload, REQUESTED_DATE)


def test_blank_table_cell_fails_closed_instead_of_becoming_available() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(FIXTURE.read_text(encoding="utf-8"))
        page.locator(".reservation tbody tr:first-child td:nth-child(2)").evaluate(
            "element => element.textContent = ''"
        )
        payload = page.evaluate(_PLUGIN_VISIBLE_DOM_SCRIPT)
        browser.close()

    assert payload["slots"][0]["state"] == ""
    with pytest.raises(PluginBrowserError, match="state"):
        parse_plugin_dom(payload, REQUESTED_DATE)


def test_time_only_terrain_cell_fails_closed_instead_of_becoming_unavailable() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(FIXTURE.read_text(encoding="utf-8"))
        page.locator(".terrainTxt").first.evaluate(
            "element => element.innerHTML = '<div class=event-time><span class=start>09:00</span></div>'"
        )
        payload = page.evaluate(_PLUGIN_VISIBLE_DOM_SCRIPT)
        browser.close()

    assert payload["slots"][0]["state"] == "unrecognized"
    with pytest.raises(PluginBrowserError, match="state"):
        parse_plugin_dom(payload, REQUESTED_DATE)


def test_weekly_fixture_extracts_only_explicit_visible_cell_states() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(WEEKLY_FIXTURE.read_text(encoding="utf-8"))
        payload = page.evaluate(_PLUGIN_VISIBLE_DOM_SCRIPT)
        browser.close()

    observations = parse_plugin_dom(payload, REQUESTED_DATE)
    assert sorted(
        (slot.court_label, slot.starts_at[11:16], slot.status) for slot in observations
    ) == [
        ("Court 1", "09:00", "available"),
        ("Court 1", "10:00", "unknown"),
        ("Court 2", "09:00", "unavailable"),
        ("Court 2", "10:00", "available"),
    ]


def test_weekly_cell_with_unrecognized_visible_state_fails_closed() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(WEEKLY_FIXTURE.read_text(encoding="utf-8"))
        page.locator(".dhx_cal_event").first.evaluate(
            "element => { element.textContent = 'maintenance'; element.setAttribute('aria-label', element.getAttribute('aria-label').replace('available', 'maintenance')); }"
        )
        payload = page.evaluate(_PLUGIN_VISIBLE_DOM_SCRIPT)
        browser.close()

    assert payload["slots"][0]["state"] == "unrecognized"
    with pytest.raises(PluginBrowserError, match="state"):
        parse_plugin_dom(payload, REQUESTED_DATE)


def test_weekly_cell_without_visible_state_fails_closed() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(WEEKLY_FIXTURE.read_text(encoding="utf-8"))
        page.locator(".dhx_cal_event").first.evaluate(
            "element => element.setAttribute('aria-label', element.getAttribute('aria-label').replace('; available', ''))"
        )
        payload = page.evaluate(_PLUGIN_VISIBLE_DOM_SCRIPT)
        browser.close()

    assert payload["slots"][0]["state"] == ""
    with pytest.raises(PluginBrowserError, match="state"):
        parse_plugin_dom(payload, REQUESTED_DATE)
