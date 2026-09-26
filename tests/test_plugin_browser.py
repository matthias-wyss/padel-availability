from datetime import date
from pathlib import Path
from typing import Any

import pytest

from padel_availability.connectors.plugin_browser import (
    _PLUGIN_VISIBLE_DOM_SCRIPT,
    PluginBrowserError,
    parse_plugin_dom,
)

FIXTURE = Path(__file__).parent / "fixtures" / "plugin" / "dom" / "plugin-diary.html"
REQUESTED_DATE = date(2026, 9, 26)


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


def test_parse_maps_states_and_keeps_variable_local_durations() -> None:
    payload = _payload()
    payload["slots"] = [
        {"court": "Court 1", "start": "09:00", "end": "10:30", "state": "available"},
        {"court": "Court 2", "start": "09:00", "end": "10:00", "state": "booked"},
        {"court": "Court 1", "start": "11:00", "end": "11:45", "state": "unknown"},
        {"court": "Court 2", "start": "11:00", "end": "11:45", "state": "available"},
    ]

    observations = parse_plugin_dom(payload, REQUESTED_DATE)

    assert [(slot.status, slot.starts_at, slot.ends_at) for slot in observations] == [
        ("available", "2026-09-26T09:00:00+02:00", "2026-09-26T10:30:00+02:00"),
        ("unavailable", "2026-09-26T09:00:00+02:00", "2026-09-26T10:00:00+02:00"),
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
