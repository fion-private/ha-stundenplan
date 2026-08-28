"""Die Stundenplan24 / Indiware Integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change

from .api import Stundenplan24Client
from .const import CONF_ABRUFZEIT, CONF_SCHULNUMMER, DEFAULT_ABRUFZEIT, DOMAIN
from .coordinator import Stundenplan24Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SERVICE_REFRESH = "refresh"
SERVICE_REFRESH_SCHEMA = vol.Schema({vol.Optional("entry_id"): str})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Richtet einen Stundenplan24-Config-Entry ein."""
    session = async_get_clientsession(hass)
    daten = {**entry.data, **entry.options}
    client = Stundenplan24Client(
        session,
        daten[CONF_SCHULNUMMER],
        daten[CONF_USERNAME],
        daten[CONF_PASSWORD],
    )

    coordinator = Stundenplan24Coordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    async def _geplanter_abruf(_now) -> None:
        await coordinator.async_request_refresh()

    stunde, minute, sekunde = _parse_zeit(daten.get(CONF_ABRUFZEIT, DEFAULT_ABRUFZEIT))
    entry.async_on_unload(
        async_track_time_change(
            hass, _geplanter_abruf, hour=stunde, minute=minute, second=sekunde
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entlädt einen Config-Entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Lädt die Integration neu, wenn sich Optionen ändern (z.B. neue Abrufzeit)."""
    await hass.config_entries.async_reload(entry.entry_id)


def _parse_zeit(text: str) -> tuple[int, int, int]:
    teile = text.split(":")
    stunde = int(teile[0])
    minute = int(teile[1]) if len(teile) > 1 else 0
    sekunde = int(teile[2]) if len(teile) > 2 else 0
    return stunde, minute, sekunde


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    async def _handle_refresh(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        coordinators: dict[str, Stundenplan24Coordinator] = hass.data.get(DOMAIN, {})
        ziele = [coordinators[entry_id]] if entry_id else list(coordinators.values())
        for coordinator in ziele:
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _handle_refresh, schema=SERVICE_REFRESH_SCHEMA
    )
