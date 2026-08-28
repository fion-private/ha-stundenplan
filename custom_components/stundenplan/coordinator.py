"""Coordinator für Stundenplan24 / Indiware.

Es wird bewusst NICHT in einem festen Intervall gepollt. Der Abruf wird
stattdessen von außen (siehe __init__.py, async_track_time_change) genau
zur konfigurierten Uhrzeit ausgelöst. Vor jedem echten Abruf prüft der
Coordinator, ob für den Zieltag überhaupt Schule ist (Wochenende, aus dem
letzten Plan bekannte Ferientage, optionaler Ferienkalender).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    Lesson,
    Stundenplan24AuthError,
    Stundenplan24Client,
    Stundenplan24ConnectionError,
    Stundenplan24NotFoundError,
)
from .const import (
    CONF_FERIEN_KALENDER,
    CONF_IGNORIERTE_FAECHER,
    CONF_IGNORIERTE_KURSE,
    CONF_KLASSE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class PlanData:
    """Den Entitäten zur Verfügung gestellte, bereits gefilterte Daten."""

    ziel_datum: date
    kein_plan_gefunden: bool = False
    uebersprungen_grund: str | None = None
    erste_stunde: dict | None = None
    stunden: list[dict] = field(default_factory=list)


class Stundenplan24Coordinator(DataUpdateCoordinator[PlanData]):
    """Holt einmal täglich (zeitgesteuert) den Plan der konfigurierten Klasse."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: Stundenplan24Client,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # kein Polling - Abruf wird extern getriggert
        )
        self._entry = entry
        self._client = client
        self._cached_freie_tage: set[date] = set()
        self._aktualisiere_konfiguration()

    def _aktualisiere_konfiguration(self) -> None:
        daten = {**self._entry.data, **self._entry.options}
        self._klasse: str = daten.get(CONF_KLASSE, "")
        self._ignorierte_faecher: set[str] = set(daten.get(CONF_IGNORIERTE_FAECHER, []))
        self._ignorierte_kurse: set[str] = set(daten.get(CONF_IGNORIERTE_KURSE, []))
        self._ferien_kalender: str | None = daten.get(CONF_FERIEN_KALENDER)

    @staticmethod
    def _ziel_datum() -> date:
        """Wir wollen immer den Plan für den nächsten Kalendertag."""
        return dt_util.now().date() + timedelta(days=1)

    async def _ist_kalender_ferientag(self, ziel_datum: date) -> bool:
        """Prüft die optionale Ferienkalender-Entität für den Zieltag."""
        if not self._ferien_kalender:
            return False
        if self.hass.states.get(self._ferien_kalender) is None:
            _LOGGER.warning(
                "Konfigurierte Ferienkalender-Entität %s wurde nicht gefunden",
                self._ferien_kalender,
            )
            return False

        start = dt_util.as_local(datetime.combine(ziel_datum, time.min))
        end = start + timedelta(days=1)
        try:
            antwort = await self.hass.services.async_call(
                "calendar",
                "get_events",
                service_data={
                    "start_date_time": start.isoformat(),
                    "end_date_time": end.isoformat(),
                },
                target={"entity_id": self._ferien_kalender},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - Kalenderabruf darf den Abruf nicht crashen
            _LOGGER.warning("Abfrage des Ferienkalenders fehlgeschlagen: %s", err)
            return False

        if not antwort:
            return False
        events = antwort.get(self._ferien_kalender, {}).get("events", [])
        return len(events) > 0

    async def _async_update_data(self) -> PlanData:
        self._aktualisiere_konfiguration()
        ziel_datum = self._ziel_datum()

        if ziel_datum.weekday() >= 5:  # Samstag=5, Sonntag=6
            return self._uebersprungen(ziel_datum, "wochenende")

        if ziel_datum in self._cached_freie_tage:
            return self._uebersprungen(ziel_datum, "ferien")

        if await self._ist_kalender_ferientag(ziel_datum):
            return self._uebersprungen(ziel_datum, "ferien_kalender")

        try:
            plan = await self._client.async_fetch_plan(ziel_datum)
        except Stundenplan24NotFoundError:
            _LOGGER.debug("Kein Plan für %s veröffentlicht", ziel_datum)
            return PlanData(ziel_datum=ziel_datum, kein_plan_gefunden=True)
        except Stundenplan24AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except Stundenplan24ConnectionError as err:
            raise UpdateFailed(str(err)) from err

        # Die im Plan enthaltene Ferienliste für künftige Skip-Prüfungen merken.
        self._cached_freie_tage = set(plan.freie_tage)

        klasse_daten = plan.klassen.get(self._klasse)
        if klasse_daten is None:
            _LOGGER.warning(
                "Klasse '%s' wurde im Plan vom %s nicht gefunden", self._klasse, ziel_datum
            )
            return PlanData(ziel_datum=ziel_datum, kein_plan_gefunden=True)

        gefilterte_stunden = [
            lesson for lesson in klasse_daten.lessons if not self._wird_ignoriert(lesson)
        ]
        gefilterte_stunden.sort(key=lambda lesson: (lesson.stunde, lesson.beginn))

        return PlanData(
            ziel_datum=ziel_datum,
            kein_plan_gefunden=False,
            erste_stunde=self._ermittle_erste_stunde(gefilterte_stunden),
            stunden=[self._lesson_zu_dict(l) for l in gefilterte_stunden],
        )

    def _wird_ignoriert(self, lesson: Lesson) -> bool:
        """Prüft, ob eine Stunde laut Konfiguration ausgeschlossen werden soll.

        Berücksichtigt sowohl das Fach als auch - falls vorhanden bzw. aus
        dem Hinweistext ableitbar - die Kursgruppe (z.B. bei geteiltem
        Unterricht wie TC1/TC2, oder wenn eine Stunde ausgefallen ist und
        nur noch über den Hinweistext erkennbar ist).
        """
        if lesson.fach and lesson.fach != "---" and lesson.fach in self._ignorierte_faecher:
            return True

        kandidat = lesson.hinweis_kandidat
        if kandidat and (
            kandidat in self._ignorierte_kurse or kandidat in self._ignorierte_faecher
        ):
            return True

        return False

    @staticmethod
    def _ermittle_erste_stunde(stunden: list[Lesson]) -> dict | None:
        """Erste Stunde, die weder ausgefallen noch (bereits vorher) ignoriert wurde."""
        relevante = [s for s in stunden if not s.entfaellt]
        if not relevante:
            return None
        erste_nummer = min(s.stunde for s in relevante)
        eintraege = [s for s in relevante if s.stunde == erste_nummer]
        return {
            "stunde": erste_nummer,
            "beginn": eintraege[0].beginn,
            "ende": eintraege[0].ende,
            "faecher": [Stundenplan24Coordinator._lesson_zu_dict(e) for e in eintraege],
        }

    @staticmethod
    def _lesson_zu_dict(lesson: Lesson) -> dict:
        return {
            "stunde": lesson.stunde,
            "beginn": lesson.beginn,
            "ende": lesson.ende,
            "fach": lesson.fach,
            "kurs": lesson.kurs,
            "lehrer": lesson.lehrer,
            "raum": lesson.raum,
            "hinweis": lesson.hinweis,
            "status": lesson.status,
            "faellt_aus": lesson.entfaellt,
        }

    def _uebersprungen(self, ziel_datum: date, grund: str) -> PlanData:
        _LOGGER.debug("Abruf für %s übersprungen (%s)", ziel_datum, grund)
        vorherige = self.data
        if vorherige is not None and vorherige.ziel_datum == ziel_datum:
            # Bereits vorhandene Daten für diesen Tag nicht verwerfen.
            return vorherige
        return PlanData(ziel_datum=ziel_datum, uebersprungen_grund=grund)
