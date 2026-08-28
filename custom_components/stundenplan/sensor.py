"""Sensor-Plattform für Stundenplan24 / Indiware."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_KLASSE, DOMAIN
from .coordinator import Stundenplan24Coordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt die Sensor-Entitäten für einen Config-Entry an."""
    coordinator: Stundenplan24Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            Stundenplan24ErsteStundeSensor(coordinator, entry),
            Stundenplan24TagesplanSensor(coordinator, entry),
        ]
    )


class Stundenplan24BaseEntity(CoordinatorEntity[Stundenplan24Coordinator]):
    """Gemeinsame Basis für alle Entitäten dieser Integration."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Stundenplan24Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        klasse = entry.options.get(CONF_KLASSE, entry.data.get(CONF_KLASSE))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Stundenplan {klasse}",
            manufacturer="Stundenplan24 / Indiware",
            model="Klassen- und Vertretungsplan",
        )


class Stundenplan24ErsteStundeSensor(Stundenplan24BaseEntity, SensorEntity):
    """Erste Unterrichtsstunde des Zieltags (Ausfälle & ignorierte Fächer ausgeschlossen)."""

    _attr_translation_key = "erste_stunde"
    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator: Stundenplan24Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_erste_stunde"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data is None or data.erste_stunde is None:
            return None
        return data.erste_stunde["beginn"]

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if data is None:
            return {}
        attrs: dict = {
            "ziel_datum": data.ziel_datum.isoformat(),
            "kein_plan_gefunden": data.kein_plan_gefunden,
            "uebersprungen_grund": data.uebersprungen_grund,
        }
        if data.erste_stunde is not None:
            attrs["stunde"] = data.erste_stunde["stunde"]
            attrs["ende"] = data.erste_stunde["ende"]
            attrs["faecher"] = data.erste_stunde["faecher"]
        return attrs


class Stundenplan24TagesplanSensor(Stundenplan24BaseEntity, SensorEntity):
    """Kompletter, gefilterter Tagesplan als Attribut-Liste (Basis für ein Dashboard)."""

    _attr_translation_key = "tagesplan"
    _attr_icon = "mdi:timetable"

    def __init__(self, coordinator: Stundenplan24Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_tagesplan"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data is None:
            return None
        if data.uebersprungen_grund:
            return "uebersprungen"
        if data.kein_plan_gefunden:
            return "kein_plan"
        return data.ziel_datum.isoformat()

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "ziel_datum": data.ziel_datum.isoformat(),
            "kein_plan_gefunden": data.kein_plan_gefunden,
            "uebersprungen_grund": data.uebersprungen_grund,
            "anzahl_stunden": len(data.stunden),
            "stunden": data.stunden,
        }
