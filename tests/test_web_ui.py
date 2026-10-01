from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from threading import Thread
from typing import cast
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import Browser, Page, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from werkzeug.serving import make_server

from padel_availability.web import create_app

ROOT = Path(__file__).parents[1]
DATA = ROOT / "data"
LOCAL_TZ = ZoneInfo("Europe/Zurich")


def _utc(day: date, hour: int, minute: int) -> str:
    local = datetime.combine(day, time(hour, minute), tzinfo=LOCAL_TZ)
    return local.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _availability(day: date) -> dict[str, object]:
    locations: dict[str, dict[str, object]] = {
        "cologny": {
            "location_id": "cologny",
            "canonical_name": "Padel Indoor",
            "municipality": "Cologny",
            "overall_cover_status": "indoor",
            "booking_url": "https://booking.example/cologny",
            "snapshot_status": "success",
            "window_start": day.isoformat(),
            "window_end": (day + timedelta(days=7)).isoformat(),
            "last_success_at": "2026-09-29T10:00:00Z",
            "error": None,
            "slots": [
                {
                    "court_label": "Indoor 1",
                    "starts_at": _utc(day, 18, 30),
                    "ends_at": _utc(day, 20, 0),
                    "status": "available",
                }
            ],
        },
        "collonge-bellerive": {
            "location_id": "collonge-bellerive",
            "canonical_name": "Padel Outdoor",
            "municipality": "Collonge-Bellerive",
            "overall_cover_status": "outdoor",
            "booking_url": "https://booking.example/outdoor",
            "snapshot_status": "success",
            "window_start": day.isoformat(),
            "window_end": (day + timedelta(days=7)).isoformat(),
            "last_success_at": "2026-09-29T10:00:00Z",
            "error": None,
            "slots": [
                {
                    "court_label": "Court extérieur 2",
                    "starts_at": _utc(day, 21, 30),
                    "ends_at": _utc(day, 22, 30),
                    "status": "available",
                },
                {
                    "court_label": "Court extérieur 1",
                    "starts_at": _utc(day, 19, 0),
                    "ends_at": _utc(day, 20, 0),
                    "status": "unknown",
                },
                {
                    "court_label": "Court extérieur 3",
                    "starts_at": _utc(day, 19, 30),
                    "ends_at": _utc(day, 20, 30),
                    "status": "available",
                },
                {
                    "court_label": "Court extérieur 4",
                    "starts_at": _utc(day, 19, 30),
                    "ends_at": _utc(day, 20, 30),
                    "status": "available",
                },
                {
                    "court_label": "Court extérieur 5",
                    "starts_at": _utc(day, 21, 30),
                    "ends_at": _utc(day, 22, 0),
                    "status": "available",
                },
                {
                    "court_label": "Court extérieur 0",
                    "starts_at": _utc(day, 18, 0),
                    "ends_at": _utc(day, 19, 0),
                    "status": "available",
                },
                {
                    "court_label": None,
                    "starts_at": _utc(day, 18, 0),
                    "ends_at": _utc(day, 19, 0),
                    "status": "available",
                },
                {
                    "court_label": None,
                    "starts_at": _utc(day, 18, 30),
                    "ends_at": _utc(day, 19, 30),
                    "status": "available",
                },
                {
                    "court_label": None,
                    "starts_at": _utc(day, 18, 30),
                    "ends_at": _utc(day, 19, 30),
                    "status": "available",
                },
                {
                    "court_label": "Court extérieur 6",
                    "starts_at": _utc(day, 19, 0),
                    "ends_at": _utc(day, 20, 0),
                    "status": "unknown",
                },
            ],
        },
        "csu-champel": {
            "location_id": "csu-champel",
            "canonical_name": "CSU Champel",
            "municipality": "Genève",
            "overall_cover_status": "partially_covered",
            "booking_url": "https://booking.example/champel",
            "snapshot_status": "stale",
            "window_start": day.isoformat(),
            "window_end": (day + timedelta(days=7)).isoformat(),
            "last_success_at": "2026-09-28T10:00:00Z",
            "error": "source unavailable",
            "slots": [
                {
                    "court_label": "Court 1",
                    "starts_at": _utc(day, 20, 0),
                    "ends_at": _utc(day, 21, 30),
                    "status": "available",
                },
                {
                    "court_label": "Court 2",
                    "starts_at": _utc(day, 20, 0),
                    "ends_at": _utc(day, 21, 30),
                    "status": "available",
                },
            ],
        },
        "drizia-miremont": {
            "location_id": "drizia-miremont",
            "canonical_name": "Drizia-Miremont",
            "municipality": "Genève",
            "overall_cover_status": "unknown",
            "booking_url": "https://booking.example/drizia",
            "snapshot_status": "no_data",
            "window_start": None,
            "window_end": None,
            "last_success_at": None,
            "error": None,
            "slots": [],
        },
    }
    return {"generated_at": "2026-09-29T10:00:00Z", "locations": locations}


@pytest.fixture
def browser_page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        try:
            browser: Browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-gpu", "--disable-dev-shm-usage"],
            )
        except PlaywrightError as error:
            pytest.skip(f"Install browser with `uv run playwright install chromium`: {error}")
        context = browser.new_context(
            timezone_id="Europe/Zurich",
            reduced_motion="reduce",
            viewport={"width": 375, "height": 812},
        )
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


@pytest.fixture
def web_server(tmp_path: Path) -> Iterator[str]:
    app = create_app(tmp_path / "catalog.sqlite3", DATA)
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_homepage_is_served(tmp_path: Path) -> None:
    response = create_app(tmp_path / "catalog.sqlite3", DATA).test_client().get("/")
    assert response.status_code == 200


def test_evening_search_keeps_statuses_and_local_club_selection(
    browser_page: Page, web_server: str
) -> None:
    today = datetime.now(LOCAL_TZ).date()
    fixed_now = int(datetime.combine(today, time(14, 0), tzinfo=LOCAL_TZ).timestamp() * 1000)
    browser_page.add_init_script(f"Date.now = () => {fixed_now}")
    fixture = _availability(today)
    refresh_status: dict[str, object] = {
        "job_id": None,
        "trigger": None,
        "status": "idle",
        "requested_at": None,
        "started_at": None,
        "finished_at": None,
        "completed_locations": 0,
        "total_locations": 23,
        "next_allowed_at": None,
        "next_scheduled_at": None,
        "error": None,
    }

    def serve_refresh_status(route: Route) -> None:
        route.fulfill(status=200, json=dict(refresh_status))

    def queue_refresh(route: Route) -> None:
        refresh_status.update(
            {
                "job_id": "browser-test-refresh",
                "trigger": "manual",
                "status": "queued",
                "requested_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        route.fulfill(status=202, json=dict(refresh_status))

    browser_page.route(
        "**/api/availability",
        lambda route: route.fulfill(status=200, json=fixture),
    )
    browser_page.route("**/api/refresh/status", serve_refresh_status)
    browser_page.route("**/api/refresh", queue_refresh)
    browser_page.goto(web_server)
    browser_page.locator("#filter-panel summary").click()
    browser_page.wait_for_selector("#club-cologny")

    for location_id in cast(dict[str, object], fixture["locations"]):
        assert browser_page.locator(f"#club-{location_id}").is_checked()

    evening_button = browser_page.get_by_role("button", name="Ce soir")
    evening_button.focus()
    browser_page.keyboard.press("Enter")
    assert browser_page.evaluate(
        "getComputedStyle(document.activeElement).outlineStyle === 'solid'"
    )
    button_box = evening_button.bounding_box()
    assert button_box is not None and button_box["height"] >= 44
    assert browser_page.locator("#date-from").input_value() == today.isoformat()
    assert browser_page.locator("#date-to").input_value() == today.isoformat()
    browser_page.locator("#club-cologny").uncheck()

    outdoor_cards = browser_page.locator(
        "#available-results [data-location-id='collonge-bellerive']"
    )
    assert outdoor_cards.count() == 5
    assert browser_page.locator(
        "#available-results .slot-time time:first-child"
    ).all_text_contents() == ["18:00", "18:30", "19:30", "21:30", "21:30"]
    assert browser_page.locator("#available-results").get_by_text("2 terrains libres").is_visible()
    assert browser_page.locator("#available-results").get_by_text("2 possibilités").count() == 1
    assert (
        browser_page.locator("#available-results")
        .get_by_text("1 terrain identifié · 1 possibilité non identifiée")
        .is_visible()
    )
    assert (
        browser_page.locator("#available-results")
        .get_by_text("Court extérieur 3 · Court extérieur 4")
        .is_visible()
    )
    assert browser_page.locator("#result-summary").get_by_text("5 créneaux").is_visible()
    assert (
        browser_page.locator("#result-summary")
        .get_by_text("3 possibilités non identifiées")
        .is_visible()
    )
    edge_card = outdoor_cards.filter(has_text="Court extérieur 2")
    assert edge_card.get_by_text("22:30").is_visible()
    assert edge_card.get_by_text("60 min").is_visible()
    booking = edge_card.get_by_role("link", name="Réserver")
    assert booking.get_attribute("href") == "https://booking.example/outdoor"
    assert booking.get_attribute("rel") == "noopener noreferrer"
    assert browser_page.locator("#available-results [data-location-id='cologny']").count() == 0
    assert browser_page.locator("#available-results [data-location-id='csu-champel']").count() == 0
    assert browser_page.locator("#available-results").get_by_text("Court extérieur 1").count() == 0

    assert browser_page.locator("#unknown-results").get_by_text("Court extérieur 1").is_visible()
    assert (
        browser_page.locator("#unknown-results [data-location-id='collonge-bellerive']").count()
        == 1
    )
    assert browser_page.locator("#stale-results").get_by_text("CSU Champel").is_visible()
    assert browser_page.locator("#stale-results [data-location-id='csu-champel']").count() == 1
    assert (
        browser_page.locator("#stale-results")
        .get_by_text("2 terrains avec données anciennes")
        .is_visible()
    )
    assert browser_page.get_by_text("Pas encore collecté").is_visible()
    assert (
        browser_page.locator("#stale-results")
        .get_by_text("Données anciennes", exact=True)
        .is_visible()
    )
    assert (
        browser_page.locator("#unknown-results").get_by_text("À vérifier", exact=True).is_visible()
    )

    date_to = browser_page.locator("#date-to")
    date_to.fill((today + timedelta(days=10)).isoformat())
    date_to.press("Tab")
    assert (
        browser_page.locator("#location-status-results")
        .get_by_text("Hors période publiée après", exact=False)
        .count()
        > 0
    )

    locations = cast(dict[str, dict[str, object]], fixture["locations"])
    outdoor_slots = cast(list[dict[str, object]], locations["collonge-bellerive"]["slots"])
    outdoor_slots.append(
        {
            "court_label": "Court ajouté après actualisation",
            "starts_at": _utc(today, 20, 30),
            "ends_at": _utc(today, 21, 30),
            "status": "available",
        }
    )
    browser_page.locator("#refresh-button").click()
    browser_page.wait_for_function(
        "document.querySelector('#refresh-message').textContent.includes('Actualisation en cours')"
    )
    refresh_status.update(
        {
            "status": "success",
            "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "completed_locations": 23,
        }
    )
    browser_page.locator("#available-results").get_by_text(
        "Court ajouté après actualisation"
    ).wait_for(timeout=8000)

    browser_page.reload()
    assert browser_page.locator("#club-cologny").is_checked() is False
    browser_page.set_viewport_size({"width": 1440, "height": 900})
    desktop_card = browser_page.locator("#available-results .slot-card").filter(
        has_text="Court extérieur 2"
    )
    desktop_card.wait_for()
    card_box = desktop_card.bounding_box()
    assert card_box is not None and card_box["height"] <= 160
    for width in (375, 768, 1024, 1440):
        browser_page.set_viewport_size({"width": width, "height": 900})
        assert browser_page.evaluate("document.documentElement.scrollWidth === window.innerWidth")


def test_past_and_duration_filters_apply_before_grouping(
    browser_page: Page, web_server: str
) -> None:
    today = datetime.now(LOCAL_TZ).date()
    fixed_now = int(datetime.combine(today, time(14, 0), tzinfo=LOCAL_TZ).timestamp() * 1000)
    browser_page.add_init_script(f"Date.now = () => {fixed_now}")
    fixture = _availability(today)
    locations = cast(dict[str, dict[str, object]], fixture["locations"])
    for location in locations.values():
        location["slots"] = []

    def slot(start: time, end: time, court: str, status: str) -> dict[str, object]:
        return {
            "court_label": court,
            "starts_at": _utc(today, start.hour, start.minute),
            "ends_at": _utc(today, end.hour, end.minute),
            "status": status,
        }

    locations["collonge-bellerive"]["slots"] = [
        slot(time(13), time(13, 30), "Déjà passé", "available"),
        slot(time(13, 30), time(14, 30), "Déjà commencé", "available"),
        slot(time(14), time(14, 30), "Commence maintenant", "available"),
        slot(time(15), time(15, 30), "30 minutes", "available"),
        slot(time(16), time(17), "Une heure", "available"),
        slot(time(17), time(18, 30), "Une heure trente", "available"),
        slot(time(19), time(21), "Deux heures", "available"),
    ]
    locations["cologny"]["slots"] = [slot(time(12), time(13), "À vérifier", "unknown")]
    locations["csu-champel"]["slots"] = [slot(time(12, 30), time(14), "Ancien", "available")]

    browser_page.route(
        "**/api/availability",
        lambda route: route.fulfill(status=200, json=fixture),
    )
    browser_page.route(
        "**/api/refresh/status",
        lambda route: route.fulfill(
            status=200,
            json={"status": "idle", "next_allowed_at": None, "next_scheduled_at": None},
        ),
    )
    browser_page.goto(web_server)
    browser_page.locator("#filter-panel summary").click()
    browser_page.locator("#duration-options input").first.wait_for()

    available = browser_page.locator("#available-results .slot-card")
    duration_options = browser_page.locator("#duration-options")
    duration_inputs = duration_options.locator("input[name=duration]")
    assert [
        duration_inputs.nth(index).get_attribute("value")
        for index in range(duration_inputs.count())
    ] == ["30", "60", "90", "120"]
    assert all(duration_inputs.nth(index).is_checked() for index in range(duration_inputs.count()))
    assert available.count() == 4
    assert available.get_by_text("Commence maintenant").count() == 0
    assert browser_page.locator("#unknown-results .slot-card").count() == 0
    assert browser_page.locator("#stale-results .slot-card").count() == 0

    duration_options.locator("input[value='60']").uncheck()
    duration_options.locator("input[value='90']").uncheck()
    duration_options.locator("input[value='120']").uncheck()
    assert available.count() == 1
    assert browser_page.locator("#available-count").inner_text() == "1"
    assert available.get_by_text("30 min", exact=True).is_visible()

    duration_options.locator("input[value='60']").check()
    assert available.count() == 2
    assert browser_page.locator("#result-summary").get_by_text("2 créneaux").is_visible()


def test_slot_disappears_when_its_start_time_passes(browser_page: Page, web_server: str) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    today = now.astimezone(LOCAL_TZ).date()
    starts_at = now + timedelta(seconds=5)
    fixture = _availability(today)
    locations = cast(dict[str, dict[str, object]], fixture["locations"])
    for location in locations.values():
        location["slots"] = []
    locations["collonge-bellerive"]["slots"] = [
        {
            "court_label": "Bientôt expiré",
            "starts_at": starts_at.isoformat().replace("+00:00", "Z"),
            "ends_at": (starts_at + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
            "status": "available",
        }
    ]
    browser_page.route(
        "**/api/availability",
        lambda route: route.fulfill(status=200, json=fixture),
    )
    browser_page.route(
        "**/api/refresh/status",
        lambda route: route.fulfill(
            status=200,
            json={"status": "idle", "next_allowed_at": None, "next_scheduled_at": None},
        ),
    )
    browser_page.goto(web_server)

    browser_page.get_by_text("Bientôt expiré").wait_for()
    browser_page.wait_for_function(
        "document.querySelectorAll('#available-results .slot-card').length === 0",
        timeout=10_000,
    )


def test_booking_links_open_the_verified_local_date(browser_page: Page, web_server: str) -> None:
    today = datetime.now(LOCAL_TZ).date()
    fixed_now = int(datetime.combine(today, time(0), tzinfo=LOCAL_TZ).timestamp() * 1000)
    browser_page.add_init_script(f"Date.now = () => {fixed_now}")
    urls = {
        "padel-station": "https://playtomic.com/fr/clubs/padel-station1",
        "vaudoise-arena": (
            "https://playtomic.io/vaudoise-arena/53b5aaf2-7449-4691-96f8-a582ce37144b"
            "?q=PADEL~2025-03-17~~~"
        ),
        "everness": "https://padel.everness.ch/",
        "bernex": "https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx",
    }
    locations = {
        location_id: {
            "location_id": location_id,
            "canonical_name": location_id,
            "municipality": "Genève",
            "overall_cover_status": "outdoor",
            "booking_url": booking_url,
            "snapshot_status": "success",
            "window_start": today.isoformat(),
            "window_end": (today + timedelta(days=7)).isoformat(),
            "last_success_at": "2026-09-29T10:00:00Z",
            "slots": [
                {
                    "court_label": "Court 1",
                    "starts_at": _utc(today, 0, 30),
                    "ends_at": _utc(today, 2, 0),
                    "status": "available",
                }
            ],
        }
        for location_id, booking_url in urls.items()
    }
    payload = {"generated_at": "2026-09-29T10:00:00Z", "locations": locations}
    browser_page.route(
        "**/api/availability",
        lambda route: route.fulfill(status=200, json=payload),
    )
    browser_page.route(
        "**/api/refresh/status",
        lambda route: route.fulfill(
            status=200,
            json={
                "status": "idle",
                "completed_locations": 0,
                "total_locations": 23,
                "next_allowed_at": None,
                "next_scheduled_at": None,
            },
        ),
    )
    browser_page.goto(web_server)

    for location_id, booking_url in urls.items():
        link = browser_page.locator(
            f"#available-results [data-location-id='{location_id}']"
        ).get_by_role("link", name="Réserver")
        href = link.get_attribute("href")
        assert href is not None
        query = parse_qs(urlsplit(href).query, keep_blank_values=True)
        if location_id in {"padel-station", "vaudoise-arena", "everness"}:
            assert query["date"] == [today.isoformat()]
        else:
            assert href == booking_url
        if location_id == "vaudoise-arena":
            assert query["q"] == ["PADEL~2025-03-17~~~"]
