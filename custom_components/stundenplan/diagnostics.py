"""Diagnostics support for the Stundenplan integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import DayPlan, Stundenplan24Coordinator

TO_REDACT = {"password", "username", "school_number"}


def _day_plan_summary(day_plan: DayPlan) -> dict[str, Any]:
    return {
        "target_date": day_plan.target_date.isoformat(),
        "plan_not_found": day_plan.plan_not_found,
        "skipped_reason": day_plan.skipped_reason,
        "lesson_count": len(day_plan.lessons),
        "has_first_lesson": day_plan.first_lesson is not None,
        "has_last_lesson": day_plan.last_lesson is not None,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Provides diagnostics data for a config entry (without credentials)."""
    coordinator: Stundenplan24Coordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": dict(entry.options),
        "coordinator_data": (
            {
                "today": _day_plan_summary(data.today),
                "tomorrow": _day_plan_summary(data.tomorrow),
            }
            if data is not None
            else None
        ),
    }
