"""Sensor platform for the Stundenplan integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CLASS_NAME, DOMAIN
from .coordinator import DayPlan, Stundenplan24Coordinator

_DAYS = ("today", "tomorrow")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Sets up the sensor entities for a config entry."""
    coordinator: Stundenplan24Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for day in _DAYS:
        entities.append(StundenplanLessonStartSensor(coordinator, entry, day))
        entities.append(StundenplanLessonEndSensor(coordinator, entry, day))
        entities.append(StundenplanDayPlanSensor(coordinator, entry, day))
    async_add_entities(entities)


class StundenplanBaseEntity(CoordinatorEntity[Stundenplan24Coordinator]):
    """Shared base for all entities of this integration."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Stundenplan24Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        class_name = entry.options.get(CONF_CLASS_NAME, entry.data.get(CONF_CLASS_NAME))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Stundenplan {class_name}",
            manufacturer="Stundenplan24 / Indiware",
            model="Class timetable and substitution plan",
        )

    def _day_plan(self, day: str) -> DayPlan | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.today if day == "today" else data.tomorrow


class StundenplanLessonStartSensor(StundenplanBaseEntity, SensorEntity):
    """Start time of the first lesson of the day (cancellations and ignored subjects/courses excluded)."""

    _attr_icon = "mdi:clock-start"

    def __init__(
        self, coordinator: Stundenplan24Coordinator, entry: ConfigEntry, day: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._day = day
        self._attr_translation_key = f"lesson_start_{day}"
        self._attr_unique_id = f"{entry.entry_id}_lesson_start_{day}"

    @property
    def native_value(self) -> str | None:
        day_plan = self._day_plan(self._day)
        if day_plan is None or day_plan.first_lesson is None:
            return None
        return day_plan.first_lesson["start"]

    @property
    def extra_state_attributes(self) -> dict:
        day_plan = self._day_plan(self._day)
        if day_plan is None:
            return {}
        attrs: dict = {
            "target_date": day_plan.target_date.isoformat(),
            "plan_not_found": day_plan.plan_not_found,
            "skipped_reason": day_plan.skipped_reason,
        }
        if day_plan.first_lesson is not None:
            attrs["period"] = day_plan.first_lesson["period"]
            attrs["end"] = day_plan.first_lesson["end"]
            attrs["subjects"] = day_plan.first_lesson["subjects"]
        return attrs


class StundenplanLessonEndSensor(StundenplanBaseEntity, SensorEntity):
    """End time of the last lesson of the day (cancellations and ignored subjects/courses excluded)."""

    _attr_icon = "mdi:clock-end"

    def __init__(
        self, coordinator: Stundenplan24Coordinator, entry: ConfigEntry, day: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._day = day
        self._attr_translation_key = f"lesson_end_{day}"
        self._attr_unique_id = f"{entry.entry_id}_lesson_end_{day}"

    @property
    def native_value(self) -> str | None:
        day_plan = self._day_plan(self._day)
        if day_plan is None or day_plan.last_lesson is None:
            return None
        return day_plan.last_lesson["end"]

    @property
    def extra_state_attributes(self) -> dict:
        day_plan = self._day_plan(self._day)
        if day_plan is None:
            return {}
        attrs: dict = {
            "target_date": day_plan.target_date.isoformat(),
            "plan_not_found": day_plan.plan_not_found,
            "skipped_reason": day_plan.skipped_reason,
        }
        if day_plan.last_lesson is not None:
            attrs["period"] = day_plan.last_lesson["period"]
            attrs["start"] = day_plan.last_lesson["start"]
            attrs["subjects"] = day_plan.last_lesson["subjects"]
        return attrs


class StundenplanDayPlanSensor(StundenplanBaseEntity, SensorEntity):
    """Complete, filtered day plan as an attribute list (basis for a dashboard)."""

    _attr_icon = "mdi:timetable"

    def __init__(
        self, coordinator: Stundenplan24Coordinator, entry: ConfigEntry, day: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._day = day
        self._attr_translation_key = f"day_plan_{day}"
        self._attr_unique_id = f"{entry.entry_id}_day_plan_{day}"

    @property
    def native_value(self) -> str | None:
        day_plan = self._day_plan(self._day)
        if day_plan is None:
            return None
        if day_plan.skipped_reason:
            return "skipped"
        if day_plan.plan_not_found:
            return "not_found"
        return day_plan.target_date.isoformat()

    @property
    def extra_state_attributes(self) -> dict:
        day_plan = self._day_plan(self._day)
        if day_plan is None:
            return {}
        return {
            "target_date": day_plan.target_date.isoformat(),
            "plan_not_found": day_plan.plan_not_found,
            "skipped_reason": day_plan.skipped_reason,
            "lesson_count": len(day_plan.lessons),
            "lessons": day_plan.lessons,
        }
