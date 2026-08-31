"""The Stundenplan integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import Stundenplan24Client
from .const import CONF_SCHOOL_NUMBER, DOMAIN
from .coordinator import Stundenplan24Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SERVICE_REFRESH = "refresh"
SERVICE_REFRESH_SCHEMA = vol.Schema({vol.Optional("entry_id"): str})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Sets up a Stundenplan config entry."""
    session = async_get_clientsession(hass)
    data = {**entry.data, **entry.options}
    client = Stundenplan24Client(
        session,
        data[CONF_SCHOOL_NUMBER],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
    )

    # The coordinator's own update_interval (see const.UPDATE_INTERVAL)
    # drives the hourly polling - no external scheduling is needed here.
    coordinator = Stundenplan24Coordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unloads a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reloads the integration when options change (e.g. class or filters)."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    async def _handle_refresh(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        coordinators: dict[str, Stundenplan24Coordinator] = hass.data.get(DOMAIN, {})
        targets = [coordinators[entry_id]] if entry_id else list(coordinators.values())
        for coordinator in targets:
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _handle_refresh, schema=SERVICE_REFRESH_SCHEMA
    )
