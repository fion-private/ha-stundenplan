"""Coordinator for the Stundenplan integration.

Polling runs on a fixed hourly interval (see const.UPDATE_INTERVAL) via
Home Assistant's built-in DataUpdateCoordinator scheduling. Before every
fetch, the coordinator checks whether the target day is a school day at
all (weekend, holidays known from the last fetched plan, optional holiday
calendar).

Both today's and tomorrow's plan are fetched on every update, so entities
can show "today" and "tomorrow" data side by side.
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
    CONF_CLASS_NAME,
    CONF_HOLIDAY_CALENDAR,
    CONF_IGNORED_COURSES,
    CONF_IGNORED_SUBJECTS,
    DOMAIN,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class DayPlan:
    """Filtered, ready-to-display data for a single day."""

    target_date: date
    plan_not_found: bool = False
    skipped_reason: str | None = None
    first_lesson: dict | None = None
    last_lesson: dict | None = None
    lessons: list[dict] = field(default_factory=list)


@dataclass
class PlanData:
    """Data made available to entities: today's and tomorrow's day plan."""

    today: DayPlan
    tomorrow: DayPlan


class Stundenplan24Coordinator(DataUpdateCoordinator[PlanData]):
    """Fetches today's and tomorrow's plan for the configured class, on a schedule."""

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
            update_interval=UPDATE_INTERVAL,
        )
        self._entry = entry
        self._client = client
        self._cached_free_days: set[date] = set()
        self._reload_config()

    def _reload_config(self) -> None:
        data = {**self._entry.data, **self._entry.options}
        self._class_name: str = data.get(CONF_CLASS_NAME, "")
        self._ignored_subjects: set[str] = set(data.get(CONF_IGNORED_SUBJECTS, []))
        self._ignored_courses: set[str] = set(data.get(CONF_IGNORED_COURSES, []))
        self._holiday_calendar: str | None = data.get(CONF_HOLIDAY_CALENDAR)

    async def _is_calendar_holiday(self, target_date: date) -> bool:
        """Checks the optional holiday calendar entity for the target date."""
        if not self._holiday_calendar:
            return False
        if self.hass.states.get(self._holiday_calendar) is None:
            _LOGGER.warning(
                "Configured holiday calendar entity %s was not found",
                self._holiday_calendar,
            )
            return False

        start = dt_util.as_local(datetime.combine(target_date, time.min))
        end = start + timedelta(days=1)
        try:
            response = await self.hass.services.async_call(
                "calendar",
                "get_events",
                service_data={
                    "start_date_time": start.isoformat(),
                    "end_date_time": end.isoformat(),
                },
                target={"entity_id": self._holiday_calendar},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - a calendar lookup must never crash the fetch
            _LOGGER.warning("Holiday calendar lookup failed: %s", err)
            return False

        if not response or not isinstance(response, dict):
            return False
        calendar_result = response.get(self._holiday_calendar)
        if not isinstance(calendar_result, dict):
            return False
        events = calendar_result.get("events", [])
        return isinstance(events, list) and len(events) > 0

    async def _async_update_data(self) -> PlanData:
        self._reload_config()
        today = dt_util.now().date()
        tomorrow = today + timedelta(days=1)
        # Fetched sequentially and deliberately not shielded from each
        # other: if either fetch hits a real connection error, the whole
        # update fails (raising UpdateFailed) and the coordinator keeps
        # serving the last known-good data until the next attempt, rather
        # than mixing fresh and stale per-day data.
        return PlanData(
            today=await self._fetch_day(today),
            tomorrow=await self._fetch_day(tomorrow),
        )

    async def _fetch_day(self, target_date: date) -> DayPlan:
        if target_date.weekday() >= 5:  # Saturday=5, Sunday=6
            return self._skipped(target_date, "weekend")

        if target_date in self._cached_free_days:
            return self._skipped(target_date, "holiday")

        if await self._is_calendar_holiday(target_date):
            return self._skipped(target_date, "holiday_calendar")

        try:
            plan = await self._client.async_fetch_plan(target_date)
        except Stundenplan24NotFoundError:
            _LOGGER.debug("No plan published for %s", target_date)
            return DayPlan(target_date=target_date, plan_not_found=True)
        except Stundenplan24AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except Stundenplan24ConnectionError as err:
            raise UpdateFailed(str(err)) from err

        # Remember the holiday list contained in the plan for future skip checks.
        self._cached_free_days = set(plan.free_days)

        class_data = plan.classes.get(self._class_name)
        if class_data is None:
            _LOGGER.warning(
                "Class '%s' was not found in the plan for %s", self._class_name, target_date
            )
            return DayPlan(target_date=target_date, plan_not_found=True)

        filtered_lessons = [
            lesson for lesson in class_data.lessons if not self._is_ignored(lesson)
        ]
        filtered_lessons.sort(key=lambda lesson: (lesson.period, lesson.start))

        return DayPlan(
            target_date=target_date,
            plan_not_found=False,
            first_lesson=self._determine_first_lesson(filtered_lessons),
            last_lesson=self._determine_last_lesson(filtered_lessons),
            lessons=[self._lesson_to_dict(lesson) for lesson in filtered_lessons],
        )

    def _is_ignored(self, lesson: Lesson) -> bool:
        """Checks whether a lesson should be excluded per the configuration.

        Considers both the subject and - where available or derivable from
        the free-text note - the course group (e.g. for split lessons like
        TC1/TC2, or when a lesson is cancelled and only recognizable via
        its note text).
        """
        if lesson.subject and lesson.subject != "---" and lesson.subject in self._ignored_subjects:
            return True

        candidate = lesson.note_candidate
        if not candidate:
            return False
        return candidate in self._ignored_courses or candidate in self._ignored_subjects

    @staticmethod
    def _determine_first_lesson(lessons: list[Lesson]) -> dict | None:
        """First lesson that is neither cancelled nor (already) ignored."""
        relevant = [lesson for lesson in lessons if not lesson.cancelled]
        if not relevant:
            return None
        first_period = min(lesson.period for lesson in relevant)
        entries = [lesson for lesson in relevant if lesson.period == first_period]
        return {
            "period": first_period,
            "start": entries[0].start,
            "end": entries[0].end,
            "subjects": [Stundenplan24Coordinator._lesson_to_dict(e) for e in entries],
        }

    @staticmethod
    def _determine_last_lesson(lessons: list[Lesson]) -> dict | None:
        """Last lesson that is neither cancelled nor (already) ignored."""
        relevant = [lesson for lesson in lessons if not lesson.cancelled]
        if not relevant:
            return None
        last_period = max(lesson.period for lesson in relevant)
        entries = [lesson for lesson in relevant if lesson.period == last_period]
        return {
            "period": last_period,
            "start": entries[0].start,
            "end": entries[0].end,
            "subjects": [Stundenplan24Coordinator._lesson_to_dict(e) for e in entries],
        }

    @staticmethod
    def _lesson_to_dict(lesson: Lesson) -> dict:
        return {
            "period": lesson.period,
            "start": lesson.start,
            "end": lesson.end,
            "subject": lesson.subject,
            "course": lesson.course,
            "teacher": lesson.teacher,
            "room": lesson.room,
            "note": lesson.note,
            "status": lesson.status,
            "cancelled": lesson.cancelled,
        }

    def _skipped(self, target_date: date, reason: str) -> DayPlan:
        _LOGGER.debug("Fetch for %s skipped (%s)", target_date, reason)
        previous = self.data
        if previous is not None:
            for day_plan in (previous.today, previous.tomorrow):
                if day_plan.target_date == target_date:
                    # Keep already-available data for this date instead of
                    # discarding it.
                    return day_plan
        return DayPlan(target_date=target_date, skipped_reason=reason)
