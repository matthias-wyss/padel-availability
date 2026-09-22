import os
import re
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from typing import Any, Self, cast

import pytest

from padel_availability.availability import AvailabilitySlot
from padel_availability.connectors.playtomic import PlaytomicSource, PlaytomicSourceError
from padel_availability.connectors.playtomic_browser import (
    _CHROMIUM_ARGS,  # pyright: ignore[reportPrivateUsage]
    _VISIBLE_DOM_SCRIPT,  # pyright: ignore[reportPrivateUsage]
    BrowserSlotObservation,
    PlaytomicBrowserConnector,
    PlaytomicBrowserError,
    _payload_is_ready,  # pyright: ignore[reportPrivateUsage]
    _select_date,  # pyright: ignore[reportPrivateUsage]
    extract_browser_observations,
    parse_browser_observations,
    parse_visible_dom,
)
from padel_availability.models import ModelError

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "playtomic" / "dom"
FONTCONFIG_FILE = Path(__file__).parent / "fixtures" / "fontconfig.conf"
FIXTURE_NAMES = (
    "padel-station",
    "gva-palexpo",
    "padel-parc-etoy",
    "padel-parc-preverenges",
    "vaudoise-arena",
)


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
        os.environ["FONTCONFIG_FILE"] = str(FONTCONFIG_FILE)
    playwright = sync_playwright().start()
    browser = None
    try:
        try:
            browser = playwright.chromium.launch(headless=True, args=list(_CHROMIUM_ARGS))
        except PlaywrightError as error:
            pytest.fail(
                "Playwright is installed but Chromium failed to launch. "
                "Install Chromium's shared libraries or set LD_LIBRARY_PATH for the "
                f"browser runtime. Original error: {error}"
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


def _fixture_payload(name: str, browser: Any) -> dict[str, Any]:
    html = (FIXTURE_ROOT / f"{name}.html").read_text(encoding="utf-8")
    context = browser.new_context()
    page = context.new_page()
    try:
        page.set_content(html)
        page.add_style_tag(
            content="[data-slot-id] { display: block; width: 100px; height: 20px; }"
        )
        payload = page.evaluate(_VISIBLE_DOM_SCRIPT)
        assert isinstance(payload, dict)
        return cast(dict[str, Any], payload)
    finally:
        page.close()
        context.close()


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

    def evaluate(self, expression: str, arg: object = None) -> object:
        self.calls.append((expression, arg))
        if arg is not None and isinstance(arg, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", arg):
            self.payload["date"] = arg
            return True
        return dict(self.payload)

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
def test_observed_fixture_returns_a_visible_slot(fixture_name: str, fixture_browser: Any) -> None:
    observations = parse_visible_dom(
        _fixture_payload(fixture_name, fixture_browser), date(2026, 9, 22)
    )

    assert len(observations) == 1
    assert observations[0].court_label
    assert observations[0].external_id
    assert observations[0].status == "available"


def test_page_extractor_reads_only_the_visible_dom_payload(fixture_browser: Any) -> None:
    page = _FakePage(_fixture_payload("padel-station", fixture_browser))

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


def test_old_date_slots_do_not_make_the_requested_date_ready() -> None:
    assert not _payload_is_ready(
        {
            "view": "booking",
            "date": "2026-09-23",
            "dates": ["2026-09-23"],
            "slots": [
                {
                    "external_id": "slot-2026-09-22T13-30Z-90",
                    "time": "3:30 PM",
                    "duration": "90",
                    "class": "bg-white",
                    "disabled": False,
                }
            ],
            "visible_text": "Available courts",
        },
        date(2026, 9, 23),
    )


def test_changed_date_stale_no_slots_state_does_not_make_the_requested_date_ready() -> None:
    previous_payload = {
        "view": "booking",
        "date": "2026-09-22",
        "dates": ["2026-09-22"],
        "slots": [
            {
                "external_id": "slot-2026-09-22T13-30Z-90",
                "time": "3:30 PM",
                "duration": "90",
                "class": "bg-white",
                "disabled": False,
            }
        ],
        "visible_text": "Available courts No available courts",
    }
    stale_payload = {
        **previous_payload,
        "date": "2026-09-23",
        "dates": ["2026-09-23"],
    }

    assert not _payload_is_ready(stale_payload, date(2026, 9, 23), previous_payload)


def test_first_date_no_slots_marker_is_ready_when_date_was_already_selected() -> None:
    payload = {
        "view": "booking",
        "date": "2026-09-22",
        "dates": ["2026-09-22"],
        "slots": [],
        "visible_text": "Available courts No available courts",
    }

    assert _payload_is_ready(payload, date(2026, 9, 22), payload)


def test_utc_slot_id_is_compared_as_a_zurich_local_date() -> None:
    payload = {
        "view": "booking",
        "date": "2026-09-22",
        "dates": ["2026-09-22"],
        "slots": [
            {
                "external_id": "boundary-2026-09-21T22-30Z-60",
                "time": "12:30 AM",
                "duration": "60",
                "class": "bg-white",
                "court": "Padel 1",
                "disabled": False,
            }
        ],
        "visible_text": "Available courts",
    }

    observation = parse_visible_dom(payload, date(2026, 9, 22))[0]

    assert observation.starts_at == "2026-09-22T00:30:00+02:00"


def test_explicit_no_slots_marker_returns_empty_tuple() -> None:
    payload = {
        "view": "booking",
        "date": "2026-09-22",
        "dates": ["2026-09-22"],
        "slots": [],
        "visible_text": "Available courts No available courts",
    }

    assert parse_visible_dom(payload, date(2026, 9, 22)) == ()


def test_disabled_slot_is_not_reported_as_available() -> None:
    payload = {
        "view": "booking",
        "date": "2026-09-22",
        "dates": ["2026-09-22"],
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
        "dates": ["2026-09-22"],
        "slots": [],
        "visible_text": marker,
    }

    with pytest.raises(PlaytomicBrowserError, match="blocked"):
        parse_visible_dom(payload, date(2026, 9, 22))


def test_missing_visible_contract_is_an_error() -> None:
    with pytest.raises(PlaytomicBrowserError, match="booking view"):
        parse_visible_dom(
            {
                "view": "unknown",
                "date": "2026-09-22",
                "dates": ["2026-09-22"],
                "slots": [],
                "visible_text": "",
            },
            date(2026, 9, 22),
        )


def test_divergent_visible_date_controls_are_an_error() -> None:
    with pytest.raises(PlaytomicBrowserError, match="divergent"):
        parse_visible_dom(
            {
                "view": "booking",
                "date": "",
                "dates": ["2026-09-22", "2026-09-23"],
                "slots": [],
                "visible_text": "Available courts No available courts",
            },
            date(2026, 9, 22),
        )


def test_selection_script_rejects_divergent_visible_date_controls(fixture_browser: Any) -> None:
    context = fixture_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            '<input type="date" value="2026-09-22" style="display:block">'
            '<input type="date" value="2026-09-23" style="display:block">'
        )
        with pytest.raises(PlaytomicBrowserError, match="divergent"):
            _select_date(page, date(2026, 9, 24))
    finally:
        page.close()
        context.close()


def test_ambiguous_local_time_is_an_error() -> None:
    payload = {
        "view": "booking",
        "date": "2026-10-25",
        "dates": ["2026-10-25"],
        "slots": [
            {
                "external_id": "ambiguous-2026-10-25T00-30Z-60",
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


def test_spring_forward_adds_duration_in_elapsed_time() -> None:
    payload = {
        "view": "booking",
        "date": "2026-03-29",
        "dates": ["2026-03-29"],
        "slots": [
            {
                "external_id": "spring-2026-03-29T00-30Z-120",
                "time": "1:30 AM",
                "duration": "120",
                "class": "bg-white",
                "court": "Padel 1",
                "disabled": False,
            }
        ],
        "visible_text": "Available courts",
    }

    observation = parse_visible_dom(payload, date(2026, 3, 29))[0]

    assert observation.starts_at == "2026-03-29T01:30:00+01:00"
    assert observation.ends_at == "2026-03-29T04:30:00+02:00"


def test_fall_back_adds_duration_in_elapsed_time() -> None:
    payload = {
        "view": "booking",
        "date": "2026-10-25",
        "dates": ["2026-10-25"],
        "slots": [
            {
                "external_id": "fall-2026-10-25T00-30Z-120",
                "time": "1:30 AM",
                "duration": "120",
                "class": "bg-white",
                "court": "Padel 1",
                "disabled": False,
            }
        ],
        "visible_text": "Available courts",
    }

    observation = parse_visible_dom(payload, date(2026, 10, 25))[0]

    assert observation.starts_at == "2026-10-25T01:30:00+02:00"
    assert observation.ends_at == "2026-10-25T02:30:00+01:00"


def test_browser_connector_maps_success_and_closes_everything(fixture_browser: Any) -> None:
    events: list[str] = []
    page = _FakePage(_fixture_payload("gva-palexpo", fixture_browser))
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
