import os
import re
from dataclasses import FrozenInstanceError
from datetime import date
from html.parser import HTMLParser
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
        except (OSError, PlaywrightError) as error:
            pytest.skip(
                "Playwright is installed but Chromium could not launch. Install Chromium's "
                "shared libraries or set LD_LIBRARY_PATH to the browser runtime, then retry. "
                f"Original error: {error}"
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


class _HtmlElement:
    def __init__(self, tag: str, attributes: dict[str, str], parent: "_HtmlElement | None") -> None:
        self.tag = tag
        self.attributes = attributes
        self.parent_element = parent
        self.children: list[_HtmlElement | str] = []

    def descendants(self) -> list["_HtmlElement"]:
        elements: list[_HtmlElement] = []
        for child in self.children:
            if isinstance(child, _HtmlElement):
                elements.append(child)
                elements.extend(child.descendants())
        return elements

    def query_selector_all(self, selector: str) -> list["_HtmlElement"]:
        elements = self.descendants()
        if selector == "div.shrink-0 .truncate":
            return [
                element
                for element in elements
                if element.tag == "div"
                and _has_class(element, "truncate")
                and any(
                    ancestor.tag == "div"
                    and _has_class(ancestor, "shrink-0")
                    for ancestor in _ancestors(element)
                )
            ]
        return [element for element in elements if _matches_selector(element, selector)]

    def query_selector(self, selector: str) -> "_HtmlElement | None":
        return next(iter(self.query_selector_all(selector)), None)

    def closest(self, selector: str) -> "_HtmlElement | None":
        current: _HtmlElement | None = self
        while current is not None:
            if _matches_selector(current, selector):
                return current
            current = current.parent_element
        return None

    def get_attribute(self, name: str) -> str | None:
        return self.attributes.get(name)

    def has_attribute(self, name: str) -> bool:
        return name in self.attributes

    def text_content(self) -> str:
        return "".join(
            child if isinstance(child, str) else child.text_content() for child in self.children
        )


class _FixtureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlElement("#document", {}, None)
        self.current = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = _HtmlElement(
            tag,
            {name: value or "" for name, value in attrs},
            self.current,
        )
        self.current.children.append(element)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.current = element

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.current.tag == tag:
            self.current = self.current.parent_element or self.root

    def handle_endtag(self, tag: str) -> None:
        current: _HtmlElement | None = self.current
        while current is not None and current.tag != tag:
            current = current.parent_element
        if current is not None and current.parent_element is not None:
            self.current = current.parent_element

    def handle_data(self, data: str) -> None:
        self.current.children.append(data)


def _ancestors(element: _HtmlElement) -> list[_HtmlElement]:
    ancestors: list[_HtmlElement] = []
    current = element.parent_element
    while current is not None:
        ancestors.append(current)
        current = current.parent_element
    return ancestors


def _has_class(element: _HtmlElement, name: str) -> bool:
    return name in (element.get_attribute("class") or "").split()


def _inline_styles(element: _HtmlElement) -> dict[str, str]:
    return {
        part.split(":", 1)[0].strip().casefold(): part.split(":", 1)[1].strip().casefold()
        for part in (element.get_attribute("style") or "").split(";")
        if ":" in part
    }


def _is_hidden(element: _HtmlElement) -> bool:
    return any(
        (styles := _inline_styles(current)).get("display") == "none"
        or styles.get("visibility") == "hidden"
        for current in [element, *_ancestors(element)]
    )


def _matches_selector(element: _HtmlElement, selector: str) -> bool:
    if selector == "h2":
        return element.tag == "h2"
    if selector == 'input[type="date"]':
        return element.tag == "input" and element.get_attribute("type") == "date"
    if selector == "div.flex.border-b":
        return (
            element.tag == "div"
            and _has_class(element, "flex")
            and _has_class(element, "border-b")
        )
    if selector == "[data-tracking-property-time][data-tracking-property-duration]":
        return element.tag != "#document" and all(
            element.has_attribute(attribute)
            for attribute in (
                "data-tracking-property-time",
                "data-tracking-property-duration",
            )
        )
    return False


def _is_visible(element: _HtmlElement) -> bool:
    if _is_hidden(element):
        return False
    for current in [element, *_ancestors(element)]:
        styles = _inline_styles(current)
        if styles.get("width") in {"0", "0px"} or styles.get("height") in {"0", "0px"}:
            return False
    return True


def _visible_text(element: _HtmlElement) -> str:
    if _is_hidden(element):
        return ""
    return "".join(
        child if isinstance(child, str) else _visible_text(child) for child in element.children
    )


class _SelectorPage:
    def __init__(self, html: str) -> None:
        parser = _FixtureParser()
        parser.feed(html)
        self.body = parser.root

    def evaluate(self, expression: str, arg: object = None) -> object:
        del arg
        assert expression == _VISIBLE_DOM_SCRIPT
        headings = self.body.query_selector_all("h2")
        heading = any(
            _is_visible(element)
            and re.search(
                r"available courts|terrains disponibles", _visible_text(element), re.IGNORECASE
            )
            is not None
            for element in headings
        )
        date_controls = [
            element
            for element in self.body.query_selector_all('input[type="date"]')
            if element.parent_element is not None and _is_visible(element.parent_element)
        ]
        dates = [element.get_attribute("value") or "" for element in date_controls]
        date_value = dates[0] if dates and all(value == dates[0] for value in dates) else ""
        slots: list[dict[str, Any]] = []
        for element in self.body.query_selector_all(
            "[data-tracking-property-time][data-tracking-property-duration]"
        ):
            if not _is_visible(element):
                continue
            row = element.closest("div.flex.border-b")
            court = row.query_selector("div.shrink-0 .truncate") if row is not None else None
            slots.append(
                {
                    "external_id": element.get_attribute("data-slot-id"),
                    "time": element.get_attribute("data-tracking-property-time"),
                    "duration": element.get_attribute("data-tracking-property-duration"),
                    "class": element.get_attribute("class") or "",
                    "disabled": element.has_attribute("disabled")
                    or element.get_attribute("aria-disabled") == "true",
                    "court": court.text_content().strip() if court is not None else None,
                }
            )
        court_rows = [
            row
            for row in self.body.query_selector_all("div.flex.border-b")
            if row.query_selector("div.shrink-0 .truncate") is not None
        ]
        return {
            "view": "booking" if heading else "unknown",
            "date": date_value,
            "dates": dates,
            "slots": slots,
            "empty_grid": heading and not slots and bool(court_rows),
            "visible_text": _visible_text(self.body),
        }


def _fixture_payload(name: str, browser: Any | None = None) -> dict[str, Any]:
    html = (FIXTURE_ROOT / f"{name}.html").read_text(encoding="utf-8")
    if browser is None:
        payload = _SelectorPage(html).evaluate(_VISIBLE_DOM_SCRIPT)
        assert isinstance(payload, dict)
        return cast(dict[str, Any], payload)
    context = browser.new_context()
    page = context.new_page()
    try:
        page.set_content(html)
        page.add_style_tag(
            content="[data-tracking-property-time] { display: block; width: 100px; height: 20px; }"
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


class _SequencePage(_FakePage):
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        super().__init__(payloads[0])
        self.payloads = payloads[1:]

    def evaluate(self, expression: str, arg: object = None) -> object:
        self.calls.append((expression, arg))
        if arg is not None and isinstance(arg, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", arg):
            return True
        return dict(self.payloads.pop(0))


class _ProgrammingErrorPage(_FakePage):
    def evaluate(self, expression: str, arg: object = None) -> object:
        del expression, arg
        raise TypeError("test programming error")


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
    observations = parse_visible_dom(
        _fixture_payload(fixture_name), date(2026, 9, 22)
    )

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


@pytest.mark.parametrize("zero_style", ["width:0", "height:0", "width:0px", "height:0px"])
@pytest.mark.parametrize("on_ancestor", [False, True])
def test_selector_fake_excludes_zero_size_slots(zero_style: str, on_ancestor: bool) -> None:
    ancestor_style = zero_style if on_ancestor else ""
    slot_style = "" if on_ancestor else zero_style
    payload = _SelectorPage(
        f"""
        <h2>Available courts</h2>
        <input type="date" value="2026-09-22">
        <div class="flex border-b" style="{ancestor_style}">
          <div class="shrink-0"><div class="truncate">Padel A</div></div>
          <div data-slot-id="slot-1" data-tracking-property-time="3:30 PM"
               data-tracking-property-duration="90" class="bg-white"
               style="{slot_style}"></div>
        </div>
        """
    ).evaluate(_VISIBLE_DOM_SCRIPT)

    assert isinstance(payload, dict)
    assert payload["slots"] == []


def test_selector_fake_inner_text_omits_hidden_no_slot_marker() -> None:
    payload = _SelectorPage(
        """
        <h2>Available courts</h2>
        <input type="date" value="2026-09-22">
        <div style="display:none">No available courts</div>
        <div style="visibility:hidden">No available courts</div>
        """
    ).evaluate(_VISIBLE_DOM_SCRIPT)

    assert isinstance(payload, dict)
    dom_payload = cast(dict[str, Any], payload)
    visible_text = dom_payload["visible_text"]
    assert isinstance(visible_text, str)
    assert "no available courts" not in visible_text.casefold()
    with pytest.raises(PlaytomicBrowserError, match="no explicit availability state"):
        parse_visible_dom(dom_payload, date(2026, 9, 22))


def test_selector_fake_recognizes_a_loaded_empty_booking_grid() -> None:
    payload = _SelectorPage(
        """
        <h2>Terrains disponibles</h2>
        <input type="date" value="2026-09-22">
        <div class="flex border-b">
          <div class="shrink-0"><div class="truncate">Padel A</div></div>
        </div>
        """
    ).evaluate(_VISIBLE_DOM_SCRIPT)

    assert isinstance(payload, dict)
    assert payload["empty_grid"] is True


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


def test_changed_date_stale_unchanged_slots_do_not_make_requested_date_ready() -> None:
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
        "visible_text": "Available courts",
    }

    stale_payload = {
        **previous_payload,
        "date": "2026-09-23",
        "dates": ["2026-09-23"],
    }

    assert not _payload_is_ready(stale_payload, date(2026, 9, 23), previous_payload)


def test_changed_date_accepts_refreshed_slots_with_opaque_utc_shaped_id() -> None:
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
                "court": "Padel A",
            }
        ],
        "visible_text": "Available courts",
    }
    refreshed_payload = {
        **previous_payload,
        "date": "2026-09-23",
        "dates": ["2026-09-23"],
        "slots": [
            {
                "external_id": "slot-2026-09-22T05-00Z-90",
                "time": "4:30 PM",
                "duration": "90",
                "class": "bg-white",
                "disabled": False,
                "court": "Padel A",
            }
        ],
    }

    assert _payload_is_ready(refreshed_payload, date(2026, 9, 23), previous_payload)
    observations = parse_visible_dom(refreshed_payload, date(2026, 9, 23))

    assert observations[0].external_id == "slot-2026-09-22T05-00Z-90"
    assert observations[0].starts_at == "2026-09-23T16:30:00+02:00"


def test_changed_date_loading_marker_does_not_make_refreshed_slots_ready() -> None:
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
        "visible_text": "Available courts",
    }
    loading_payload = {
        **previous_payload,
        "date": "2026-09-23",
        "dates": ["2026-09-23"],
        "slots": [
            {
                "external_id": "slot-2026-09-23T05-00Z-90",
                "time": "4:30 PM",
                "duration": "90",
                "class": "bg-white",
                "disabled": False,
            }
        ],
        "visible_text": "Available courts Chargement en cours…",
    }

    assert not _payload_is_ready(loading_payload, date(2026, 9, 23), previous_payload)


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
        "visible_text": "Available courts No available courts Wed, Sep 23",
    }

    assert not _payload_is_ready(stale_payload, date(2026, 9, 23), previous_payload)


def test_loaded_empty_grid_requires_refresh_for_a_changed_date() -> None:
    previous_payload = {
        "view": "booking",
        "date": "2026-09-22",
        "dates": ["2026-09-22"],
        "slots": [],
        "empty_grid": True,
        "visible_text": "Terrains disponibles",
    }
    empty_payload = {
        **previous_payload,
        "date": "2026-09-23",
        "dates": ["2026-09-23"],
    }

    assert not _payload_is_ready(empty_payload, date(2026, 9, 23), previous_payload)
    assert _payload_is_ready(
        empty_payload,
        date(2026, 9, 23),
        previous_payload,
        refresh_observed=True,
    )


def test_first_loaded_empty_grid_can_follow_the_initial_booking_shell() -> None:
    initial_payload = {
        "view": "unknown",
        "date": "",
        "dates": [],
        "slots": [],
        "empty_grid": False,
        "visible_text": "Pour les joueurs",
    }
    empty_payload = {
        "view": "booking",
        "date": "2026-09-22",
        "dates": ["2026-09-22"],
        "slots": [],
        "empty_grid": True,
        "visible_text": "Terrains disponibles",
    }

    assert _payload_is_ready(empty_payload, date(2026, 9, 22), initial_payload)


def test_loaded_empty_grid_parses_as_zero_slots() -> None:
    payload = {
        "view": "booking",
        "date": "2026-09-22",
        "dates": ["2026-09-22"],
        "slots": [],
        "empty_grid": True,
        "visible_text": "Terrains disponibles",
    }

    assert parse_visible_dom(payload, date(2026, 9, 22)) == ()


def test_adjacent_empty_dates_complete_after_observed_loading_transition() -> None:
    def payload(day: str, text: str) -> dict[str, Any]:
        return {
            "view": "booking",
            "date": day,
            "dates": [day],
            "slots": [],
            "visible_text": f"Available courts {text}".strip(),
        }

    events: list[str] = []
    page = _SequencePage(
        [
            payload("2026-09-22", "No available courts"),
            payload("2026-09-22", "No available courts"),
            payload("2026-09-22", "No available courts"),
            payload("2026-09-23", "No available courts Chargement en cours"),
            payload("2026-09-23", "No available courts"),
        ]
    )
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

    result = connector.collect(
        location,
        run_id="run-browser",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 24),
        collected_at="2026-09-22T07:00:00Z",
    )
    connector.close()

    assert result.run.status == "success"
    assert result.slots == ()


def test_browser_programming_errors_propagate_and_cleanup() -> None:
    events: list[str] = []
    page = _ProgrammingErrorPage({})
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

    with pytest.raises(TypeError, match="test programming error"):
        connector.collect(
            location,
            run_id="run-browser",
            window_start=date(2026, 9, 22),
            window_end=date(2026, 9, 23),
            collected_at="2026-09-22T07:00:00Z",
        )
    connector.close()

    assert page.closed


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


def test_disabled_slot_is_reported_as_unavailable() -> None:
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
        "visible_text": "Available courts",
    }

    observations = parse_visible_dom(payload, date(2026, 9, 22))

    assert len(observations) == 1
    assert observations[0].status == "unavailable"


def test_visible_slots_extract_optional_ids_and_unknown_state() -> None:
    payload = {
        "view": "booking",
        "date": "2026-09-22",
        "dates": ["2026-09-22"],
        "slots": [
            {
                "external_id": None,
                "time": "3:30 PM",
                "duration": "90",
                "class": "bg-white",
                "disabled": False,
                "court": "Padel 1",
            },
            {
                "external_id": "disabled-slot",
                "time": "5:00 PM",
                "duration": "60",
                "class": "bg-primary-40",
                "disabled": True,
                "court": "Padel 1",
            },
            {
                "external_id": None,
                "time": "6:00 PM",
                "duration": "60",
                "class": "bg-primary-40",
                "disabled": False,
                "court": "Padel 1",
            },
        ],
        "visible_text": "Available courts",
    }

    observations = parse_visible_dom(payload, date(2026, 9, 22))

    assert [observation.external_id for observation in observations] == [
        None,
        "disabled-slot",
        None,
    ]
    assert [observation.status for observation in observations] == [
        "available",
        "unavailable",
        "unknown",
    ]


def test_missing_id_dom_slots_use_hash_and_reject_hash_collisions() -> None:
    payload = {
        "view": "booking",
        "date": "2026-09-22",
        "dates": ["2026-09-22"],
        "slots": [
            {
                "external_id": None,
                "time": "3:30 PM",
                "duration": "90",
                "class": "bg-white",
                "disabled": False,
                "court": "Padel 1",
            },
            {
                "external_id": None,
                "time": "3:30 PM",
                "duration": "90",
                "class": "bg-primary-40",
                "disabled": False,
                "court": "Padel 1",
            },
        ],
        "visible_text": "Available courts",
    }

    observations = parse_visible_dom(payload, date(2026, 9, 22))

    assert observations[0].external_id is None
    with pytest.raises(PlaytomicSourceError, match="conflicting duplicate slot hash"):
        parse_browser_observations(
            observations,
            location_id="padel-station",
            run_id="run-browser",
            window_start=date(2026, 9, 22),
            window_end=date(2026, 9, 23),
        )


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

    connector.close()
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

    connector.close()
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


def test_browser_observations_allow_reused_external_id_on_different_local_dates() -> None:
    external_id = "slot-2026-09-22T19-30Z-90"
    observations = tuple(
        BrowserSlotObservation(
            external_id,
            "Court 1",
            starts_at,
            ends_at,
            "available",
        )
        for starts_at, ends_at in (
            ("2026-09-22T21:30:00+02:00", "2026-09-22T23:00:00+02:00"),
            ("2026-09-23T21:30:00+02:00", "2026-09-23T23:00:00+02:00"),
        )
    )

    slots = parse_browser_observations(
        observations,
        location_id="padel-station",
        run_id="run-browser",
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 24),
    )

    assert len(slots) == 2
    assert [slot.external_id for slot in slots] == [external_id, external_id]
