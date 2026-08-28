"""Async API-Client + XML-Parser für Stundenplan24 / Indiware (PlanKl-Dateien)."""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, timedelta

import aiohttp

from .const import BASE_URL, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

_BOM = b"\xef\xbb\xbf"

# Erkennt bei komplett ausgefallenen Stunden (Fa == "---") das ursprüngliche
# Fach aus dem freien Hinweistext, z.B.:
#   "KU Herr Mai fällt aus"                      -> KU
#   "für MA Frau Matthes"                        -> MA
#   "verlegt von St.4; GEO Frau Korb verlegt..."  -> GEO
# Der gefundene Kandidat wird zusätzlich gegen den bekannten Fächerkatalog
# der Klasse geprüft, um Fehltreffer bei untypischen Hinweistexten zu
# vermeiden.
_FACH_AUS_HINWEIS_RE = re.compile(
    r"(?:verlegt von St\.\d+;\s*)?(?:für\s+)?"
    r"([A-Za-zÄÖÜäöüß0-9]+)\s+(?:Herrn?|Frau|Fr\.|Frl\.?|Hr\.?)\b"
)


def _rate_urspruengliches_fach(hinweis: str, bekannte_faecher: set[str]) -> str | None:
    """Best-effort-Ermittlung des Originalfachs einer ausgefallenen Stunde."""
    if not hinweis:
        return None
    match = _FACH_AUS_HINWEIS_RE.search(hinweis)
    if not match:
        return None
    kandidat = match.group(1)
    return kandidat if kandidat in bekannte_faecher else None


class Stundenplan24Error(Exception):
    """Basisklasse für alle Fehler dieser Integration."""


class Stundenplan24AuthError(Stundenplan24Error):
    """Zugangsdaten wurden vom Server abgelehnt (HTTP 401/403)."""


class Stundenplan24ConnectionError(Stundenplan24Error):
    """Verbindung fehlgeschlagen / unerwarteter Serverfehler."""


class Stundenplan24NotFoundError(Stundenplan24Error):
    """Für das angefragte Datum wurde kein Plan veröffentlicht (HTTP 404)."""


@dataclass
class Lesson:
    """Ein einzelner Unterrichts-/Plan-Eintrag (<Std>) einer Klasse."""

    stunde: int
    beginn: str
    ende: str
    fach: str
    lehrer: str
    raum: str
    hinweis: str
    fach_geaendert: bool
    lehrer_geaendert: bool
    raum_geaendert: bool
    kurs: str | None = None  # <Ku2>: Kürzel der Kursgruppe bei geteiltem Unterricht

    @property
    def entfaellt(self) -> bool:
        """True, wenn die Stunde komplett ausfällt (Fach == '---')."""
        return self.fach == "---"

    @property
    def status(self) -> str:
        if self.entfaellt:
            return "entfaellt"
        if self.fach_geaendert or self.lehrer_geaendert or self.raum_geaendert:
            return "geaendert"
        return "regulaer"

    @property
    def hinweis_kandidat(self) -> str | None:
        """Bestes Fach-/Kurskürzel für einen komplett ausgefallenen Eintrag.

        Bei geteiltem Unterricht bleibt <Ku2> auch bei Ausfall erhalten. Fehlt
        es (z.B. bei nicht geteilten Fächern), wird versucht, das Kürzel aus
        dem freien Hinweistext zu extrahieren (z.B. "MA Frau Matthes fällt
        aus" -> "MA"). Das ist eine Heuristik und kann in Einzelfällen daneben
        liegen.
        """
        if self.kurs:
            return self.kurs
        if not self.entfaellt:
            return None
        text = self.hinweis.strip()
        if not text:
            return None
        if ";" in text:
            text = text.split(";", 1)[1].strip()
        if text.startswith("für "):
            text = text[4:].strip()
        token = text.split(" ", 1)[0] if text else ""
        return token or None


@dataclass
class ParsedKlasse:
    """Alle für eine Klasse geparsten Daten."""

    kurz: str
    faecher: set[str] = field(default_factory=set)
    kurse: set[str] = field(default_factory=set)
    lessons: list[Lesson] = field(default_factory=list)


@dataclass
class ParsedPlan:
    """Das komplett geparste XML-Dokument."""

    ziel_datum: date
    freie_tage: list[date]
    klassen: dict[str, ParsedKlasse]


def _strip_bom(data: bytes) -> bytes:
    if data.startswith(_BOM):
        return data[len(_BOM) :]
    return data


def _parse_freie_tage(root: ET.Element) -> list[date]:
    """Parst <FreieTage><ft>YYMMDD</ft>...</FreieTage> zu einer Liste von date-Objekten."""
    freie_tage: list[date] = []
    for ft in root.findall("./FreieTage/ft"):
        text = (ft.text or "").strip()
        if len(text) != 6:
            continue
        try:
            jahr = 2000 + int(text[0:2])
            monat = int(text[2:4])
            tag = int(text[4:6])
            freie_tage.append(date(jahr, monat, tag))
        except ValueError:
            _LOGGER.debug("Konnte FreieTage-Eintrag nicht parsen: %s", text)
    return freie_tage


def _text(el: ET.Element, tag: str) -> str:
    kind = el.find(tag)
    return (kind.text or "").strip() if kind is not None and kind.text else ""


def _changed(el: ET.Element, tag: str) -> bool:
    """True, wenn das Element ein *Ae-Attribut trägt (z.B. FaAe="FaGeaendert")."""
    kind = el.find(tag)
    return kind is not None and kind.get(f"{tag}Ae") is not None


def _parse_klassen(root: ET.Element) -> dict[str, ParsedKlasse]:
    klassen: dict[str, ParsedKlasse] = {}
    for kl in root.findall("./Klassen/Kl"):
        kurz_el = kl.find("Kurz")
        if kurz_el is None or not (kurz_el.text or "").strip():
            continue
        kurz = kurz_el.text.strip()
        parsed = ParsedKlasse(kurz=kurz)

        # Kompletter Fächerkatalog der Klasse (unabhängig vom Tagesplan) -
        # wird für die Fächer-Auswahl im Config-/Options-Flow verwendet.
        for ue in kl.findall("./Unterricht/Ue/UeNr"):
            fach = (ue.get("UeFa") or "").strip()
            if fach:
                parsed.faecher.add(fach)

        # Katalog der Kursgruppen (z.B. bei geteiltem Unterricht wie
        # TC1/TC2 oder DeHS/DeRS) - wird für die Kurs-Auswahl verwendet.
        for kkz in kl.findall("./Kurse/Ku/KKz"):
            kurs = (kkz.text or "").strip()
            if kurs:
                parsed.kurse.add(kurs)

        for std in kl.findall("./Pl/Std"):
            st_text = _text(std, "St")
            try:
                stunde = int(st_text)
            except ValueError:
                continue

            lesson = Lesson(
                stunde=stunde,
                beginn=_text(std, "Beginn"),
                ende=_text(std, "Ende"),
                fach=_text(std, "Fa"),
                lehrer=_text(std, "Le"),
                raum=_text(std, "Ra"),
                hinweis=_text(std, "If"),
                fach_geaendert=_changed(std, "Fa"),
                lehrer_geaendert=_changed(std, "Le"),
                raum_geaendert=_changed(std, "Ra"),
                kurs=_text(std, "Ku2") or None,
            )
            parsed.lessons.append(lesson)
            # Ein ausgefallenes Fach taucht im Plan als "---" auf, das
            # eigentliche Fach steht dann nicht mehr in <Fa>. Wir nehmen
            # daher zusätzlich alle regulären Fachkürzel aus dem Tagesplan
            # selbst in den Katalog auf (deckt z.B. Kurse ab, die nicht in
            # <Unterricht> auftauchen).
            if lesson.fach and lesson.fach != "---":
                parsed.faecher.add(lesson.fach)
            if lesson.kurs:
                parsed.kurse.add(lesson.kurs)

        klassen[kurz] = parsed
    return klassen


def parse_plan_xml(data: bytes, ziel_datum: date) -> ParsedPlan:
    """Parst ein Stundenplan24 'PlanKl*.xml'-Dokument."""
    root = ET.fromstring(_strip_bom(data))
    return ParsedPlan(
        ziel_datum=ziel_datum,
        freie_tage=_parse_freie_tage(root),
        klassen=_parse_klassen(root),
    )


class Stundenplan24Client:
    """Schlanker asynchroner Client für den Stundenplan24-Mobil-Export."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        schulnummer: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._schulnummer = schulnummer
        self._auth = aiohttp.BasicAuth(username, password)

    def _url_for(self, ziel_datum: date) -> str:
        return f"{BASE_URL}/{self._schulnummer}/mobil/mobdaten/PlanKl{ziel_datum:%Y%m%d}.xml"

    async def async_fetch_raw(self, ziel_datum: date) -> bytes:
        """Ruft die rohen XML-Bytes für ein Datum ab.

        Wirft Stundenplan24AuthError, Stundenplan24NotFoundError oder
        Stundenplan24ConnectionError.
        """
        url = self._url_for(ziel_datum)
        try:
            async with self._session.get(
                url,
                auth=self._auth,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status in (401, 403):
                    raise Stundenplan24AuthError(
                        f"Zugangsdaten wurden abgelehnt (HTTP {response.status})"
                    )
                if response.status == 404:
                    raise Stundenplan24NotFoundError(
                        f"Kein Plan für {ziel_datum.isoformat()} veröffentlicht"
                    )
                if response.status != 200:
                    raise Stundenplan24ConnectionError(
                        f"Unerwarteter Status {response.status} von Stundenplan24"
                    )
                return await response.read()
        except Stundenplan24Error:
            raise
        except aiohttp.ClientError as err:
            raise Stundenplan24ConnectionError(str(err)) from err
        except TimeoutError as err:
            raise Stundenplan24ConnectionError(
                "Zeitüberschreitung bei der Anfrage an Stundenplan24"
            ) from err

    async def async_fetch_plan(self, ziel_datum: date) -> ParsedPlan:
        """Ruft den Plan für ein Datum ab und parst ihn."""
        raw = await self.async_fetch_raw(ziel_datum)
        return parse_plan_xml(raw, ziel_datum)

    async def async_verify_credentials(self) -> None:
        """Prüft nur, ob die Zugangsdaten akzeptiert werden.

        Ein 404 (kein Plan für heute) gilt dabei als Erfolg - es geht nur
        um Authentifizierung, nicht um Plandaten.
        """
        try:
            await self.async_fetch_raw(date.today())
        except Stundenplan24NotFoundError:
            return

    async def async_probe(self, start: date, max_days: int) -> ParsedPlan | None:
        """Sucht ab `start` tageweise nach dem nächsten veröffentlichten Plan.

        Wird im Config-/Options-Flow verwendet, um die verfügbaren Klassen
        und den Fächerkatalog zu ermitteln. Auth- und Verbindungsfehler
        werden sofort weitergereicht, ein einzelnes 404 wird übersprungen.
        Wird in `max_days` Tagen kein Plan gefunden (z.B. während der
        Sommerferien), liefert die Methode None statt eines Fehlers.
        """
        letzter_verbindungsfehler: Stundenplan24ConnectionError | None = None
        for offset in range(max_days):
            probe_datum = start + timedelta(days=offset)
            try:
                return await self.async_fetch_plan(probe_datum)
            except Stundenplan24NotFoundError:
                continue
            except Stundenplan24ConnectionError as err:
                letzter_verbindungsfehler = err
                continue
        if letzter_verbindungsfehler is not None:
            raise letzter_verbindungsfehler
        return None
