"""Diagnostics-Unterstützung für Stundenplan24 / Indiware."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import Stundenplan24Coordinator

TO_REDACT = {"password", "username", "schulnummer"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Stellt Diagnosedaten für einen Config-Entry bereit (ohne Zugangsdaten)."""
    coordinator: Stundenplan24Coordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": dict(entry.options),
        "coordinator_data": (
            {
                "ziel_datum": data.ziel_datum.isoformat(),
                "kein_plan_gefunden": data.kein_plan_gefunden,
                "uebersprungen_grund": data.uebersprungen_grund,
                "anzahl_stunden": len(data.stunden),
                "erste_stunde_vorhanden": data.erste_stunde is not None,
            }
            if data is not None
            else None
        ),
    }
