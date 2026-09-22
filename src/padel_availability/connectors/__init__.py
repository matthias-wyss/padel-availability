"""Availability connectors."""

from .airpad import (
    AIRPAD_LOCATION_IDS,
    AIRPAD_LOCATION_LABELS,
    AirpadSource,
    AirpadSourceError,
    load_airpad_sources,
)
from .airpad_browser import (
    AirpadBrowserConnector,
    AirpadBrowserConnectorFactory,
    AirpadBrowserError,
)
from .playtomic import (
    JsonFetcher,
    PlaytomicConnector,
    PlaytomicSource,
    PlaytomicSourceError,
    fetch_public_json,
    load_playtomic_sources,
    parse_playtomic_slots,
)
from .playtomic_browser import (
    BrowserConnector,
    BrowserConnectorFactory,
    BrowserSlotObservation,
    PlaytomicBrowserConnector,
    PlaytomicBrowserError,
    extract_browser_observations,
    parse_browser_observations,
    parse_visible_dom,
)

__all__ = [
    "AIRPAD_LOCATION_IDS",
    "AIRPAD_LOCATION_LABELS",
    "AirpadBrowserConnector",
    "AirpadBrowserConnectorFactory",
    "AirpadBrowserError",
    "AirpadSource",
    "AirpadSourceError",
    "BrowserConnector",
    "BrowserConnectorFactory",
    "BrowserSlotObservation",
    "JsonFetcher",
    "PlaytomicBrowserConnector",
    "PlaytomicBrowserError",
    "PlaytomicConnector",
    "PlaytomicSource",
    "PlaytomicSourceError",
    "extract_browser_observations",
    "fetch_public_json",
    "load_airpad_sources",
    "load_playtomic_sources",
    "parse_browser_observations",
    "parse_playtomic_slots",
    "parse_visible_dom",
]
