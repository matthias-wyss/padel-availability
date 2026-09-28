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
from .everness import (
    EVERNESS_BOOKING_URL,
    EVERNESS_LOCATION_IDS,
    EvernessSource,
    EvernessSourceError,
    EvernessStatus,
    load_everness_sources,
)
from .everness_browser import (
    EvernessBrowserConnector,
    EvernessBrowserConnectorFactory,
    EvernessBrowserError,
)
from .matchpoint import (
    MATCHPOINT_BOOKING_URLS,
    MATCHPOINT_LOCATION_IDS,
    MatchpointSource,
    MatchpointSourceError,
    MatchpointStatus,
    load_matchpoint_sources,
)
from .matchpoint_browser import (
    MatchpointBrowserConnector,
    MatchpointBrowserConnectorFactory,
    MatchpointBrowserError,
)
from .padelfirst import (
    PADEL_FIRST_BOOKING_URL,
    PADEL_FIRST_LOCATION_IDS,
    PADEL_FIRST_SLOT_MINUTES,
    PadelFirstSource,
    PadelFirstSourceError,
    PadelFirstStatus,
    load_padelfirst_sources,
)
from .padelfirst_browser import (
    PadelFirstBrowserConnector,
    PadelFirstBrowserConnectorFactory,
    PadelFirstBrowserError,
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
from .plugin import (
    PLUGIN_BOOKING_URLS,
    PLUGIN_LOCATION_IDS,
    PluginSource,
    PluginSourceError,
    PluginStatus,
    load_plugin_sources,
)
from .plugin_browser import (
    PluginBrowserConnector,
    PluginBrowserConnectorFactory,
    PluginBrowserError,
)

__all__ = [
    "AIRPAD_LOCATION_IDS",
    "AIRPAD_LOCATION_LABELS",
    "EVERNESS_BOOKING_URL",
    "EVERNESS_LOCATION_IDS",
    "MATCHPOINT_BOOKING_URLS",
    "MATCHPOINT_LOCATION_IDS",
    "PADEL_FIRST_BOOKING_URL",
    "PADEL_FIRST_LOCATION_IDS",
    "PADEL_FIRST_SLOT_MINUTES",
    "PLUGIN_BOOKING_URLS",
    "PLUGIN_LOCATION_IDS",
    "AirpadBrowserConnector",
    "AirpadBrowserConnectorFactory",
    "AirpadBrowserError",
    "AirpadSource",
    "AirpadSourceError",
    "BrowserConnector",
    "BrowserConnectorFactory",
    "BrowserSlotObservation",
    "EvernessBrowserConnector",
    "EvernessBrowserConnectorFactory",
    "EvernessBrowserError",
    "EvernessSource",
    "EvernessSourceError",
    "EvernessStatus",
    "JsonFetcher",
    "MatchpointBrowserConnector",
    "MatchpointBrowserConnectorFactory",
    "MatchpointBrowserError",
    "MatchpointSource",
    "MatchpointSourceError",
    "MatchpointStatus",
    "PadelFirstBrowserConnector",
    "PadelFirstBrowserConnectorFactory",
    "PadelFirstBrowserError",
    "PadelFirstSource",
    "PadelFirstSourceError",
    "PadelFirstStatus",
    "PlaytomicBrowserConnector",
    "PlaytomicBrowserError",
    "PlaytomicConnector",
    "PlaytomicSource",
    "PlaytomicSourceError",
    "PluginBrowserConnector",
    "PluginBrowserConnectorFactory",
    "PluginBrowserError",
    "PluginSource",
    "PluginSourceError",
    "PluginStatus",
    "extract_browser_observations",
    "fetch_public_json",
    "load_airpad_sources",
    "load_everness_sources",
    "load_matchpoint_sources",
    "load_padelfirst_sources",
    "load_playtomic_sources",
    "load_plugin_sources",
    "parse_browser_observations",
    "parse_playtomic_slots",
    "parse_visible_dom",
]
