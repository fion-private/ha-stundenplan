"""Async API client + XML parser for Stundenplan24 / Indiware (PlanKl files)."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, timedelta

import aiohttp

from .const import BASE_URL, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

_BOM = b"\xef\xbb\xbf"


class Stundenplan24Error(Exception):
    """Base class for all errors raised by this integration."""


class Stundenplan24AuthError(Stundenplan24Error):
    """Credentials were rejected by the server (HTTP 401/403)."""


class Stundenplan24ConnectionError(Stundenplan24Error):
    """Connection failed / unexpected server error."""


class Stundenplan24NotFoundError(Stundenplan24Error):
    """No plan has been published for the requested date (HTTP 404)."""


@dataclass
class Lesson:
    """A single lesson/period entry (<Std>) for a class."""

    period: int
    start: str
    end: str
    subject: str
    teacher: str
    room: str
    note: str
    subject_changed: bool
    teacher_changed: bool
    room_changed: bool
    course: str | None = None

    @property
    def cancelled(self) -> bool:
        """True if the lesson is fully cancelled (subject == '---')."""
        return self.subject == "---"

    @property
    def status(self) -> str:
        if self.cancelled:
            return "cancelled"
        if self.subject_changed or self.teacher_changed or self.room_changed:
            return "changed"
        return "regular"

    @property
    def note_candidate(self) -> str | None:
        """Best subject/course code for a fully cancelled lesson.

        For split course groups, <Ku2> is preserved even when the lesson is
        cancelled. Where it's missing (e.g. non-split subjects), we try to
        extract the code from the free-text hint (e.g. "MA Mr Miller
        cancelled" -> "MA"). This is a heuristic and may occasionally be
        wrong for unusual phrasing.
        """
        if self.course:
            return self.course
        if not self.cancelled:
            return None
        text = self.note.strip()
        if not text:
            return None
        if ";" in text:
            text = text.split(";", 1)[1].strip()
        if text.startswith("für "):
            text = text[4:].strip()
        token = text.split(" ", 1)[0] if text else ""
        return token or None


@dataclass
class ParsedClass:
    """Everything parsed for a single class."""

    short_name: str
    subjects: set[str] = field(default_factory=set)
    courses: set[str] = field(default_factory=set)
    lessons: list[Lesson] = field(default_factory=list)


@dataclass
class ParsedPlan:
    """The fully parsed XML document."""

    target_date: date
    free_days: list[date]
    classes: dict[str, ParsedClass]


def _strip_bom(data: bytes) -> bytes:
    if data.startswith(_BOM):
        return data[len(_BOM) :]
    return data


def _parse_free_days(root: ET.Element) -> list[date]:
    """Parses <FreieTage><ft>YYMMDD</ft>...</FreieTage> into a list of dates."""
    free_days: list[date] = []
    for ft in root.findall("./FreieTage/ft"):
        text = (ft.text or "").strip()
        if len(text) != 6:
            continue
        try:
            year = 2000 + int(text[0:2])
            month = int(text[2:4])
            day = int(text[4:6])
            free_days.append(date(year, month, day))
        except ValueError:
            _LOGGER.debug("Could not parse FreieTage entry: %s", text)
    return free_days


def _text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def _changed(el: ET.Element, tag: str) -> bool:
    """True if the element carries a *Ae attribute (e.g. FaAe="FaGeaendert")."""
    child = el.find(tag)
    return child is not None and child.get(f"{tag}Ae") is not None


def _parse_classes(root: ET.Element) -> dict[str, ParsedClass]:
    classes: dict[str, ParsedClass] = {}
    for kl in root.findall("./Klassen/Kl"):
        short_name_el = kl.find("Kurz")
        short_name = (
            (short_name_el.text or "").strip() if short_name_el is not None else ""
        )
        if not short_name:
            continue
        parsed = ParsedClass(short_name=short_name)

        # Full subject catalog for the class (independent of the day plan) -
        # used for the subject picker in the config/options flow.
        for ue in kl.findall("./Unterricht/Ue/UeNr"):
            subject = (ue.get("UeFa") or "").strip()
            if subject:
                parsed.subjects.add(subject)

        # Course-group catalog (e.g. for split lessons like TC1/TC2 or
        # DeHS/DeRS) - used for the course picker.
        for kkz in kl.findall("./Kurse/Ku/KKz"):
            course = (kkz.text or "").strip()
            if course:
                parsed.courses.add(course)

        for std in kl.findall("./Pl/Std"):
            period_text = _text(std, "St")
            try:
                period = int(period_text)
            except ValueError:
                continue

            lesson = Lesson(
                period=period,
                start=_text(std, "Beginn"),
                end=_text(std, "Ende"),
                subject=_text(std, "Fa"),
                teacher=_text(std, "Le"),
                room=_text(std, "Ra"),
                note=_text(std, "If"),
                subject_changed=_changed(std, "Fa"),
                teacher_changed=_changed(std, "Le"),
                room_changed=_changed(std, "Ra"),
                course=_text(std, "Ku2") or None,
            )
            parsed.lessons.append(lesson)
            # A cancelled lesson shows up in the plan as "---", so the
            # actual subject is no longer in <Fa>. We therefore also add
            # every regular subject code found in the day plan itself to
            # the catalog (covers e.g. courses that don't appear in
            # <Unterricht>).
            if lesson.subject and lesson.subject != "---":
                parsed.subjects.add(lesson.subject)
            if lesson.course:
                parsed.courses.add(lesson.course)

        classes[short_name] = parsed
    return classes


def parse_plan_xml(data: bytes, target_date: date) -> ParsedPlan:
    """Parses a Stundenplan24 'PlanKl*.xml' document."""
    root = ET.fromstring(_strip_bom(data))
    return ParsedPlan(
        target_date=target_date,
        free_days=_parse_free_days(root),
        classes=_parse_classes(root),
    )


class Stundenplan24Client:
    """Thin async client for the Stundenplan24 mobile export."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        school_number: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._school_number = school_number
        self._auth = aiohttp.BasicAuth(username, password)

    def _url_for(self, target_date: date) -> str:
        return f"{BASE_URL}/{self._school_number}/mobil/mobdaten/PlanKl{target_date:%Y%m%d}.xml"

    async def async_fetch_raw(self, target_date: date) -> bytes:
        """Fetches the raw XML bytes for a date.

        Raises Stundenplan24AuthError, Stundenplan24NotFoundError or
        Stundenplan24ConnectionError.
        """
        url = self._url_for(target_date)
        try:
            async with self._session.get(
                url,
                auth=self._auth,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status in (401, 403):
                    raise Stundenplan24AuthError(
                        f"Credentials were rejected (HTTP {response.status})"
                    )
                if response.status == 404:
                    raise Stundenplan24NotFoundError(
                        f"No plan published for {target_date.isoformat()}"
                    )
                if response.status != 200:
                    raise Stundenplan24ConnectionError(
                        f"Unexpected status {response.status} from Stundenplan24"
                    )
                return await response.read()
        except Stundenplan24Error:
            raise
        except aiohttp.ClientError as err:
            raise Stundenplan24ConnectionError(str(err)) from err
        except TimeoutError as err:
            raise Stundenplan24ConnectionError(
                "Timed out while requesting Stundenplan24"
            ) from err

    async def async_fetch_plan(self, target_date: date) -> ParsedPlan:
        """Fetches and parses the plan for a date."""
        raw = await self.async_fetch_raw(target_date)
        return parse_plan_xml(raw, target_date)

    async def async_verify_credentials(self) -> None:
        """Checks only whether the credentials are accepted.

        A 404 (no plan today) counts as success here - this is only about
        authentication, not about plan data.
        """
        try:
            await self.async_fetch_raw(date.today())
        except Stundenplan24NotFoundError:
            return

    async def async_probe(self, start: date, max_days: int) -> ParsedPlan | None:
        """Searches day by day, starting at `start`, for the next published plan.

        Used by the config/options flow to discover available classes and
        the subject/course catalog. Auth and connection errors are raised
        immediately; a single 404 is skipped. If no plan is found within
        `max_days` (e.g. during summer holidays), returns None instead of
        raising.
        """
        last_connection_error: Stundenplan24ConnectionError | None = None
        for offset in range(max_days):
            probe_date = start + timedelta(days=offset)
            try:
                return await self.async_fetch_plan(probe_date)
            except Stundenplan24NotFoundError:
                continue
            except Stundenplan24ConnectionError as err:
                last_connection_error = err
                continue
        if last_connection_error is not None:
            raise last_connection_error
        return None
