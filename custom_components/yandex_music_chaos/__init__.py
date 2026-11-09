from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig

from .api import register_views
from .const import (
    CONF_SOURCE_ENTITY,
    DATA_SERVICE,
    DATA_STATIC_REGISTERED,
    DOMAIN,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL,
    STATIC_PREFIX,
)
from .yandex import YandexMusicService
from .radio import RadioController

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = []


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    source_entity = (entry.options or {}).get(
        CONF_SOURCE_ENTITY,
        entry.data.get(CONF_SOURCE_ENTITY, ""),
    )
    service = YandexMusicService(hass, source_entity)
    service.radio = RadioController(service)
    entry.async_on_unload(hass.bus.async_listen(EVENT_STATE_CHANGED, service.radio.handle_event))
    entry.async_on_unload(async_track_time_interval(hass, service.radio.retry_waiting, timedelta(seconds=10)))
    entry.async_on_unload(service.radio.close)
    hass.data[DOMAIN] = service
    hass.data[DATA_SERVICE] = service

    web_dir = Path(__file__).parent / "www"
    if not hass.data.get(DATA_STATIC_REGISTERED):
        static_config = StaticPathConfig(STATIC_PREFIX, str(web_dir), cache_headers=False)
        if hasattr(hass.http, "async_register_static_paths"):
            await hass.http.async_register_static_paths([static_config])
        else:
            # Compatibility with older Home Assistant releases.
            hass.http.register_static_path(STATIC_PREFIX, str(web_dir), cache_headers=False)
        hass.data[DATA_STATIC_REGISTERED] = True
    register_views(hass, service)

    frontend.async_register_built_in_panel(
        hass,
        "custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL,
        require_admin=False,
        update=True,
        config={
            "_panel_custom": {
                "name": "yandex-music-chaos-panel",
                "embed_iframe": False,
                "module_url": f"{STATIC_PREFIX}/panel.js?v=0.3.5",
            },
            "entry_id": entry.entry_id,
        },
    )

    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    frontend.async_remove_panel(hass, PANEL_URL, warn_if_unknown=False)
    service = hass.data.pop(DOMAIN, None)
    if hass.data.get(DATA_SERVICE) is service:
        hass.data.pop(DATA_SERVICE, None)
    return True
