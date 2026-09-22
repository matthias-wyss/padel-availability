import re
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from typing import Any, Self

import pytest

from padel_availability.availability import AvailabilitySlot
from padel_availability.connectors.playtomic import PlaytomicSource, PlaytomicSourceError
from padel_availability.connectors.playtomic_browser import (
    _CHROMIUM_ARGS,
    _VISIBLE_DOM_SCRIPT,
    BrowserSlotObservation,
    PlaytomicBrowserConnector,
    PlaytomicBrowserError,
    _payload_is_ready,
    extract_browser_observations,
    parse_browser_observations,
    parse_visible_dom,
)
from padel_availability.models import ModelError

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "playtomic" / "dom"
FIXTURE_NAMES = (
    "padel-station",
    "gva-palexpo",
    "padel-parc-etoy",
    "padel-parc-preverenges",
    "vaudoise-arena",
)


def _fixture_payload(name: str) -> dict[str, Any]:
    html = (FIXTURE_ROOT / f"{name}.html").read_text(encoding="utf-8")
    date_value = re.search(r'<input type="date" value="([^"]+)"', html)
    court = re.search(r'class="truncate">([^<]+)', html)
    slot = re.search(
        r'data-tracking-property-time="([^"]+)"\s+'
        r'data-tracking-property-duration="([^"]+)"\s+'
        r'data-slot-id="([^"]+)"\s+class="([^"]+)"',
        html,
    )
    assert date_value and court and slot
    return {
        "view": "booking",
        "date": date_value.group(1),
        "court": court.group(1),
        "slots": [
            {
                "external_id": slot.group(3),
                "time": slot.group(1),
                "duration": slot.group(2),
                "class": slot.group(4),
                "court": court.group(1),
                "disabled": False,
            }
        ],
        "visible_text": html,
    }


class _FakePage:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, object | None]] = []
        self.closed = False
        self.wait_until: str | None = None

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.wait_until = wait_until
        self.calls.append(("goto", url))

    def wait_for_timeout(self, timeout: int) -> None:
        self.calls.append(("wait", timeout))

    def evaluate(self, script: str, arg: object = None) -> object:
        self.calls.append((script, arg))
        if arg is not None and isinstance(arg, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", arg):
            self.payload["date"] = arg
        return self.payload

    def close(self) -> None:
        self.closed = True


class _FakeContext:
    def __init__(self, page: _FakePage, events: list[str]) -> None:
        self.page = page
        self.events = events

    def new_page(self) -> _FakePage:
        self.events.append("new_page")
        return self.page

    def close(self) -> None:
        self.events.append("context_close")


class _FakeBrowser:
    def __init__(self, context: _FakeContext, events: list[str]) -> None:
        self.context = context
        self.events = events

    def __enter__(self) -> Self:
        self.events.append("browser_enter")
        return self

    def __exit__(self, *_: object) -> None:
        self.events.append("browser_exit")

    def new_context(self) -> _FakeContext:
        self.events.append("new_context")
        return self.context


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_observed_fixture_returns_a_visible_slot(fixture_name: str) -> None:
    observations = parse_visible_dom(_fixture_payload(fixture_name), date(2026, 9, 22))

    assert len(observations) == 1
    assert observations[0].court_label
    assert observations[0].external_id
    assert observations[0].status == "available"


def test_page_extractor_reads_only_the_visible_dom_payload() -> None:
    page = _FakePage(_fixture_payload("padel-station"))

    observations = extract_browser_observations(page, date(2026, 9, 22))

    assert observations[0].external_id == (
        "0225f259-c27d-412c-a0e2-6025e2c90a5d-2026-09-22T13-30Z-90"
    )
    assert observations[0].court_label == "Padel A"
    assert observations[0].starts_at == "2026-09-22T15:30:00+02:00"
    assert observations[0].ends_at == "2026-09-22T17:00:00+02:00"
    assert all(call[0] != "page.content" for call in page.calls)


def test_visible_dom_script_reads_the_page_body_itself() -> None:
    assert _VISIBLE_DOM_SCRIPT.lstrip().startswith("() =>")


def test_visible_dom_script_allows_visible_slots_with_zero_height_ancestors() -> None:
    assert "(current !== document.body && (rect.width === 0 || rect.height === 0))" not in (
        _VISIBLE_DOM_SCRIPT
    )


def test_chromium_launch_disables_the_unavailable_gpu_font_path() -> None:
    assert "--disable-gpu" in _CHROMIUM_ARGS


def test_booking_shell_without_slots_is_not_ready() -> None:
    assert not _payload_is_ready(
        {
            "view": "booking",
            "date": "2026-09-22",
            "slots": [],
            "visible_text": "Available courts",
        },
        date(2026, 9, 22),
    )


def test_explicit_no_slots_marker_returns_empty_tuple() -> None:
    payload = {
        "view": "booking",
        "date": "2026-09-22",
        "slots": [],
        "visible_text": "Available courts No available courts",
    }

    assert parse_visible_dom(payload, date(2026, 9, 22)) == ()


def test_disabled_slot_is_not_reported_as_available() -> None:
    payload = {
        "view": "booking",
        "date": "2026-09-22",
        "slots": [
            {
                "external_id": "disabled-slot",
                "time": "3:30 PM",
                "duration": "90",
                "class": "bg-primary-40",
                "disabled": True,
            }
        ],
        "visible_text": "Available courts No available courts",
    }

    assert parse_visible_dom(payload, date(2026, 9, 22)) == ()


@pytest.mark.parametrize("marker", ["Log in to continue", "CAPTCHA verification required"])
def test_login_or_captcha_marker_is_a_bounded_error(marker: str) -> None:
    payload = {
        "view": "booking",
        "date": "2026-09-22",
        "slots": [],
        "visible_text": marker,
    }

    with pytest.raises(PlaytomicBrowserError, match="blocked"):
        parse_visible_dom(payload, date(2026, 9, 22))


def test_missing_visible_contract_is_an_error() -> None:
    with pytest.raises(PlaytomicBrowserError, match="booking view"):
        parse_visible_dom(
            {"view": "unknown", "date": "2026-09-22", "slots": [], "visible_text": ""},
            date(2026, 9, 22),
        )


def test_ambiguous_local_time_is_an_error() -> None:
    payload = {
        "view": "booking",
        "date": "2026-10-25",
        "slots": [
            {
                "external_id": "ambiguous-slot",
                "time": "2:30 AM",
                "duration": "60",
                "class": "bg-white",
                "court": "Padel 1",
                "disabled": False,
            }
        ],
        "visible_text": "Available courts",
    }

    with pytest.raises(PlaytomicBrowserError, match="ambiguous"):
        parse_visible_dom(payload, date(2026, 10, 25))


def test_browser_connector_maps_success_and_closes_everything() -> None:
    events: list[str] = []
    page = _FakePage(_fixture_payload("gva-palexpo"))
    browser = _FakeBrowser(_FakeContext(page, events), events)
    source = PlaytomicSource(
        "gva-palexpo",
        "https://playtomic.com/clubs/gva-padel-mp-sports-sa",
        "browser_dom",
        None,
        "2026-09-22T00:00:00Z",
        "public",
    )
    from padel_availability.inventory import load_locations

    location = next(
        item
        for item in load_locations(Path(__file__).parents[1] / "data" / "verified_locations.json")
        if item.location_id == "gva-palexpo"
    )
    connector = PlaytomicBrowserConnector((source,), browser_factory=lambda: browser)

    result = connector.collect(
        location,
        run_id="run-browser",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )

    assert result.run.status == "success"
    assert len(result.slots) == 1
    assert result.slots[0].court_label == "Pista EL TONY MATÉ"
    assert page.closed
    assert page.wait_until == "commit"
    assert events == ["browser_enter", "new_context", "new_page", "context_close", "browser_exit"]


def test_browser_connector_converts_dom_failure_to_source_error_and_closes() -> None:
    events: list[str] = []
    page = _FakePage({"view": "unknown", "date": "2026-09-22", "slots": [], "visible_text": ""})
    browser = _FakeBrowser(_FakeContext(page, events), events)
    source = PlaytomicSource(
        "padel-station",
        "https://playtomic.com/fr/clubs/padel-station1",
        "browser_dom",
        None,
        "2026-09-22T00:00:00Z",
        "public",
    )
    from padel_availability.inventory import load_locations

    location = next(
        item
        for item in load_locations(Path(__file__).parents[1] / "data" / "verified_locations.json")
        if item.location_id == "padel-station"
    )
    connector = PlaytomicBrowserConnector((source,), browser_factory=lambda: browser)

    with pytest.raises(PlaytomicSourceError, match="timed out"):
        connector.collect(
            location,
            run_id="run-browser",
            window_start=date(2026, 9, 22),
            window_end=date(2026, 9, 23),
            collected_at="2026-09-22T07:00:00Z",
        )

    assert page.closed
    assert events[-2:] == ["context_close", "browser_exit"]


def test_unavailable_source_does_not_launch_browser() -> None:
    source = PlaytomicSource(
        "padel-station",
        "https://playtomic.com/fr/clubs/padel-station1",
        "browser_dom",
        None,
        "2026-09-22T00:00:00Z",
        "unavailable",
    )
    from padel_availability.inventory import load_locations

    location = next(
        item
        for item in load_locations(Path(__file__).parents[1] / "data" / "verified_locations.json")
        if item.location_id == "padel-station"
    )
    connector = PlaytomicBrowserConnector(
        (source,), browser_factory=lambda: pytest.fail("launched")
    )

    result = connector.collect(
        location,
        run_id="run-browser",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 23),
        collected_at="2026-09-22T07:00:00Z",
    )

    assert result.run.status == "unavailable"
    assert result.slots == ()


def test_browser_observation_rejects_blank_times() -> None:
    with pytest.raises(ModelError, match="starts_at"):
        BrowserSlotObservation(None, "Court 1", "", "2026-09-22T19:00:00+02:00", "available")


def test_browser_observation_is_immutable() -> None:
    observation = BrowserSlotObservation(
        "slot-1", "Court 1", "2026-09-22T18:00:00+02:00", "2026-09-22T19:00:00+02:00", "available"
    )

    with pytest.raises(FrozenInstanceError):
        observation.status = "unknown"  # type: ignore[misc]


def test_browser_observations_normalize_filter_and_sort_slots() -> None:
    observations = (
        BrowserSlotObservation(
            "slot-2",
            "Court 2",
            "2026-09-22T20:00:00+02:00",
            "2026-09-22T21:00:00+02:00",
            "unavailable",
        ),
        BrowserSlotObservation(
            "slot-1",
            "Court 1",
            "2026-09-22T18:00:00+02:00",
            "2026-09-22T19:00:00+02:00",
            "available",
        ),
        BrowserSlotObservation(
            None,
            "Court 3",
            "2026-09-23T18:00:00+02:00",
            "2026-09-23T19:00:00+02:00",
            "unknown",
        ),
        BrowserSlotObservation(
            "outside",
            "Court 4",
            "2026-09-24T18:00:00+02:00",
            "2026-09-24T19:00:00+02:00",
            "available",
        ),
    )

    slots = parse_browser_observations(
        observations,
        location_id="padel-station",
        run_id="run-browser",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 24),
    )

    assert all(isinstance(slot, AvailabilitySlot) for slot in slots)
    assert [slot.external_id for slot in slots] == ["slot-1", "slot-2", None]
    assert [slot.status for slot in slots] == ["available", "unavailable", "unknown"]
    assert slots[0].starts_at == "2026-09-22T16:00:00Z"
    assert len(slots[2].slot_key) == 64
    assert all(slot.timezone == "Europe/Zurich" for slot in slots)


def test_browser_observations_deduplicate_equal_slots() -> None:
    observation = BrowserSlotObservation(
        None,
        "Court 1",
        "2026-09-22T18:00:00+02:00",
        "2026-09-22T19:00:00+02:00",
        "available",
    )

    slots = parse_browser_observations(
        (observation, observation),
        location_id="padel-station",
        run_id="run-browser",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 23),
    )

    assert len(slots) == 1


def test_browser_observations_reject_conflicting_duplicate_ids() -> None:
    with pytest.raises(PlaytomicSourceError, match="conflicting duplicate external_id"):
        parse_browser_observations(
            (
                BrowserSlotObservation(
                    "same-id",
                    "Court 1",
                    "2026-09-22T18:00:00+02:00",
                    "2026-09-22T19:00:00+02:00",
                    "available",
                ),
                BrowserSlotObservation(
                    "same-id",
                    "Court 1",
                    "2026-09-22T18:00:00+02:00",
                    "2026-09-22T19:00:00+02:00",
                    "unavailable",
                ),
            ),
            location_id="padel-station",
            run_id="run-browser",
            window_start=date(2026, 9, 22),
            window_end=date(2026, 9, 23),
        )
